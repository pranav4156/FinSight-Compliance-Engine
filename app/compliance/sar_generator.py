import logging
import time
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.compliance.embeddings import find_similar_cases, store_embedding
from app.compliance.pdf_renderer import render_sar_pdf
from app.core.config import settings
from app.core.metrics import sar_generated_total, sar_generation_latency
from app.db.models import Alert, AlertSeverity, SARReport, Transaction, TransactionStatus

logger = logging.getLogger(__name__)

# Model routing based on severity — cost control (edge case from design doc)
MODEL_BY_SEVERITY = {
    AlertSeverity.CRITICAL: "gpt-4o",
    AlertSeverity.HIGH:     "gpt-4o",
    AlertSeverity.MEDIUM:   "gpt-4o-mini",
    AlertSeverity.LOW:      "gpt-4o-mini",
}

SYSTEM_PROMPT = """You are a senior compliance analyst at a regulated Indian fintech institution.
Your task is to write a Suspicious Activity Report (SAR) narrative in the format required by
FIU-IND (Financial Intelligence Unit — India) under the Prevention of Money Laundering Act (PMLA).

CRITICAL RULES — you must follow these without exception:
1. Use ONLY the transaction data and account information provided below.
2. Do NOT invent, assume, or infer any details not explicitly present in the data.
3. Do NOT mention specific individuals by name unless provided.
4. Write in formal, precise compliance language suitable for a regulatory filing.
5. Structure: (a) Subject and Account Overview → (b) Suspicious Transaction Pattern →
   (c) Why This Activity is Suspicious → (d) Regulatory Basis for Filing.
6. Keep the narrative factual, specific, and between 200–400 words."""

HUMAN_PROMPT = """Generate a SAR narrative for the following suspicious activity:

ALERT INFORMATION:
- Alert ID     : {alert_id}
- Severity     : {severity}
- Rules Fired  : {rules_triggered}
- Anomaly Score: {anomaly_score:.3f} / 1.000

TRANSACTION DETAILS:
- Reference    : {transaction_ref}
- Sender       : {sender_account}
- Receiver     : {receiver_account}
- Amount       : ₹{amount}
- Currency     : {currency}
- Channel      : {channel}
- Timestamp    : {transaction_time}

{similar_cases_section}

Write the SAR narrative now:"""


JUDGE_MODEL = "gpt-4o-mini"

JUDGE_SYSTEM_PROMPT = """You are an independent compliance reviewer auditing a SAR narrative
drafted by another analyst (or AI system) for a regulated Indian fintech institution.

You are NOT the author. Your job is to critique, not rewrite.

Score the narrative on three dimensions, each 0.0-1.0:
1. FACTUAL ACCURACY: every amount, account, channel, and rule referenced in the narrative
   must exactly match the source data below. Any invented or mismatched detail is a failure.
2. COMPLETENESS: must cover all four required sections — Subject/Account Overview,
   Suspicious Transaction Pattern, Why This Activity is Suspicious, Regulatory Basis for Filing.
3. REGULATORY TONE: formal, precise, free of speculation or casual language.

Respond ONLY with valid JSON in this exact shape, no markdown fences:
{{"factual_accuracy": <float>, "completeness": <float>, "regulatory_tone": <float>, "critique": "<2-4 sentence explanation>"}}"""

JUDGE_HUMAN_PROMPT = """SOURCE DATA (ground truth — the narrative must not contradict or invent beyond this):
- Transaction Reference : {transaction_ref}
- Sender                : {sender_account}
- Receiver              : {receiver_account}
- Amount                : ₹{amount}
- Currency              : {currency}
- Channel               : {channel}
- Rules Triggered       : {rules_triggered}
- Anomaly Score         : {anomaly_score:.3f}

NARRATIVE TO AUDIT:
{narrative}

Return your JSON evaluation now:"""

JUDGE_PASS_THRESHOLD = 0.7


async def _judge_narrative(narrative: str, alert: Alert, txn: Transaction) -> dict:
    """
    Independent LLM-as-Judge pass over a freshly generated SAR narrative.
    Uses a separate (cheaper) model than the generator so the same model
    is never grading its own output. Returns a dict with score/critique/passed.
    Judge failures never block the pipeline — they're logged for analyst review.
    """
    import json

    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI

    judge_llm = ChatOpenAI(
        model=JUDGE_MODEL,
        temperature=0.0,
        openai_api_key=settings.openai_api_key,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", JUDGE_SYSTEM_PROMPT),
        ("human", JUDGE_HUMAN_PROMPT),
    ])

    chain = prompt | judge_llm | StrOutputParser()

    try:
        raw = await chain.ainvoke({
            "transaction_ref":  txn.transaction_ref,
            "sender_account":   txn.sender_account,
            "receiver_account": txn.receiver_account,
            "amount":           f"{txn.amount:,}",
            "currency":         txn.currency,
            "channel":          txn.channel or "UNKNOWN",
            "rules_triggered":  alert.rule_triggered or "anomaly_detection",
            "anomaly_score":    float(txn.anomaly_score or 0),
            "narrative":        narrative,
        })
        verdict = json.loads(raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
        score = (
            verdict["factual_accuracy"] + verdict["completeness"] + verdict["regulatory_tone"]
        ) / 3
        return {
            "score": round(score, 3),
            "critique": verdict["critique"],
            "passed": score >= JUDGE_PASS_THRESHOLD,
        }
    except Exception as e:
        logger.error(f"LLM-as-Judge evaluation failed: {e}")
        return {"score": None, "critique": f"Judge evaluation failed: {e}", "passed": None}


def _build_similar_cases_section(similar_cases: list[SARReport]) -> str:
    if not similar_cases:
        return "SIMILAR PAST CASES: None found — generate narrative from first principles."

    lines = ["SIMILAR PAST CASES (for context and consistency):"]
    for i, sar in enumerate(similar_cases, 1):
        preview = (sar.narrative or "")[:300].replace("\n", " ")
        lines.append(f"\nCase {i} (filed {sar.created_at.strftime('%Y-%m-%d') if sar.created_at else 'unknown'}):")
        lines.append(f"  {preview}...")

    return "\n".join(lines)


async def generate_sar(
    alert_id: UUID,
    session: AsyncSession,
    analyst_id: UUID | None = None,
) -> SARReport:
    """
    Full SAR generation pipeline:
      1. Load alert and associated transaction from DB
      2. Check for existing SAR (idempotency — edge case #27)
      3. Fetch similar past cases via pgvector for context
      4. Select LLM model based on alert severity (cost control)
      5. Run LangChain chain — strictly grounded in DB data (prevents hallucination)
      6. Save SAR narrative to DB
      7. Generate PDF
      8. Store narrative embedding for future similarity search
    """
    # ── 1. Load alert ────────────────────────────────────────────────────────
    alert = await session.execute(
        select(Alert).where(Alert.id == alert_id)
    )
    alert = alert.scalar_one_or_none()

    if alert is None:
        raise ValueError(f"Alert {alert_id} not found")

    # ── 2. Idempotency — return existing SAR if already generated ─────────────
    existing = await session.execute(
        select(SARReport).where(SARReport.alert_id == alert_id)
    )
    existing_sar = existing.scalar_one_or_none()
    if existing_sar:
        logger.info(f"SAR already exists for alert {alert_id} — returning existing")
        return existing_sar

    # ── 3. Load transaction ───────────────────────────────────────────────────
    txn = await session.execute(
        select(Transaction).where(Transaction.id == alert.transaction_id)
    )
    txn = txn.scalar_one_or_none()

    if txn is None:
        raise ValueError(f"Transaction not found for alert {alert_id}")

    # ── 4. Find similar past SARs via pgvector ────────────────────────────────
    search_query = (
        f"{alert.rule_triggered or ''} {txn.sender_account} "
        f"amount {txn.amount} {txn.channel or ''}"
    )
    similar_cases = await find_similar_cases(search_query, alert.tenant_id, session)
    logger.info(f"Found {len(similar_cases)} similar past case(s) for context")

    _start_time = time.time()

    # ── 5. Select model based on severity ─────────────────────────────────────
    model_name = MODEL_BY_SEVERITY.get(alert.severity, "gpt-4o-mini")
    logger.info(f"Using {model_name} for {alert.severity.value} severity alert")

    # Lazy imports — LangChain 0.2.x uses pydantic v1 which has issues with
    # Python 3.14+. Importing here (not at module level) prevents server
    # startup failure. SAR generation requires Python ≤ 3.12 or LangChain 0.3.x.
    try:
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI
    except Exception as e:
        raise RuntimeError(
            f"LangChain import failed: {e}. "
            "SAR generation requires Python ≤ 3.12 or LangChain ≥ 0.3.x."
        ) from e

    llm = ChatOpenAI(
        model=model_name,
        temperature=0.1,
        openai_api_key=settings.openai_api_key,
    )

    # ── 6. Build and run LangChain chain ──────────────────────────────────────
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", HUMAN_PROMPT),
    ])

    chain = prompt | llm | StrOutputParser()

    narrative = await chain.ainvoke({
        "alert_id":              str(alert_id),
        "severity":              alert.severity.value.upper(),
        "rules_triggered":       alert.rule_triggered or "anomaly_detection",
        "anomaly_score":         float(txn.anomaly_score or 0),
        "transaction_ref":       txn.transaction_ref,
        "sender_account":        txn.sender_account,
        "receiver_account":      txn.receiver_account,
        "amount":                f"{txn.amount:,}",
        "currency":              txn.currency,
        "channel":               txn.channel or "UNKNOWN",
        "transaction_time":      txn.created_at.strftime("%Y-%m-%d %H:%M UTC") if txn.created_at else "unknown",
        "similar_cases_section": _build_similar_cases_section(similar_cases),
    })

    logger.info(f"SAR narrative generated ({len(narrative)} chars)")

    # ── 6b. Independent LLM-as-Judge evaluation ────────────────────────────────
    verdict = await _judge_narrative(narrative, alert, txn)
    logger.info(
        f"LLM-as-Judge verdict for alert {alert_id}: score={verdict['score']} "
        f"passed={verdict['passed']}"
    )

    # ── 7. Save SAR to DB ─────────────────────────────────────────────────────
    sar = SARReport(
        tenant_id=alert.tenant_id,
        alert_id=alert_id,
        narrative=narrative,
        judge_score=verdict["score"],
        judge_critique=verdict["critique"],
        judge_passed=verdict["passed"],
        created_by=analyst_id,
    )
    session.add(sar)

    # Mark transaction as REPORTED and alert as resolved
    txn.status = TransactionStatus.REPORTED
    alert.is_resolved = True
    alert.resolved_by = analyst_id

    await session.commit()
    await session.refresh(sar)

    # ── 8. Generate PDF ───────────────────────────────────────────────────────
    # Narrative + judge verdict are already committed at this point (the core
    # compliance artifact). PDF/embedding are best-effort — a failure here must
    # not surface as a 500 and must not leave the SAR in a half-failed state
    # that's invisible to the analyst.
    try:
        sar.pdf_path = await render_sar_pdf(sar, alert, txn)
        await session.commit()
    except Exception as e:
        logger.error(f"PDF rendering failed for SAR {sar.id}: {e}")

    # ── 9. Store embedding for future similarity search ───────────────────────
    try:
        await store_embedding(sar.id, narrative, session)
    except Exception as e:
        logger.error(f"Embedding storage failed for SAR {sar.id}: {e}")

    elapsed = time.time() - _start_time
    sar_generation_latency.observe(elapsed)
    sar_generated_total.labels(model=model_name).inc()

    logger.info(f"SAR {sar.id} complete in {elapsed:.1f}s — PDF at {sar.pdf_path}")
    return sar
