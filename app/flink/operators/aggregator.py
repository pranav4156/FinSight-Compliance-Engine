import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Alert, AlertSeverity, Transaction, TransactionStatus
from app.flink.operators.dormant_account import check_dormant
from app.flink.operators.graph_cycle_detector import check_graph_cycle
from app.flink.operators.isolation_forest_scorer import score_isolation_forest
from app.flink.operators.structuring_detector import check_structuring
from app.flink.operators.velocity_check import check_velocity
from app.flink.operators.zscore_baseline import check_zscore

logger = logging.getLogger(__name__)

# Weight of each operator in the final anomaly score (must sum to 1.0)
WEIGHTS = {
    "velocity":         0.20,
    "structuring":      0.20,
    "cycle":            0.20,
    "zscore":           0.15,
    "dormant":          0.10,
    "isolation_forest": 0.15,
}

# Final score threshold above which a transaction is flagged and an Alert is created
ALERT_THRESHOLD = 0.60

# Severity bands
SEVERITY_CRITICAL = 0.85
SEVERITY_HIGH = 0.70
SEVERITY_MEDIUM = 0.55


def _determine_severity(score: float) -> AlertSeverity:
    if score >= SEVERITY_CRITICAL:
        return AlertSeverity.CRITICAL
    if score >= SEVERITY_HIGH:
        return AlertSeverity.HIGH
    if score >= ALERT_THRESHOLD:
        return AlertSeverity.MEDIUM
    return AlertSeverity.LOW


def _build_rule_label(scores: dict) -> str:
    """Build a human-readable label of which rules fired."""
    fired = [name for name, score in scores.items() if score > 0]
    return " | ".join(fired) if fired else "isolation_forest_only"


def score_and_alert(transaction_ref: str, session: Session) -> float:
    """
    Run all anomaly detection operators against a transaction, compute
    a weighted final score, update the transaction record, and create
    an Alert if the score exceeds the threshold.

    Returns the final anomaly score (0.0–1.0).

    This is called by the Kafka consumer immediately after a transaction
    is persisted to the database.
    """
    txn = session.execute(
        select(Transaction).where(Transaction.transaction_ref == transaction_ref)
    ).scalar_one_or_none()

    if txn is None:
        logger.error(f"Transaction not found for scoring: {transaction_ref}")
        return 0.0

    # Run all operators and collect individual scores
    individual_scores = {
        "velocity":         check_velocity(txn, session),
        "structuring":      check_structuring(txn, session),
        "cycle":            check_graph_cycle(txn, session),
        "zscore":           check_zscore(txn, session),
        "dormant":          check_dormant(txn, session),
        "isolation_forest": score_isolation_forest(txn, session),
    }

    # Weighted average
    final_score = sum(
        individual_scores[name] * weight
        for name, weight in WEIGHTS.items()
    )

    is_suspicious = final_score >= ALERT_THRESHOLD

    # Update transaction record
    txn.anomaly_score = final_score
    txn.is_suspicious = is_suspicious
    txn.status = TransactionStatus.FLAGGED if is_suspicious else TransactionStatus.CLEARED
    txn.processed_at = datetime.utcnow()

    # Create alert if suspicious
    if is_suspicious:
        severity = _determine_severity(final_score)
        rule_label = _build_rule_label(individual_scores)

        alert = Alert(
            tenant_id=txn.tenant_id,
            transaction_id=txn.id,
            rule_triggered=rule_label,
            severity=severity,
        )
        session.add(alert)

        logger.warning(
            f"ALERT [{severity.value.upper()}] {transaction_ref} | "
            f"score={final_score:.3f} | rules={rule_label}"
        )
    else:
        logger.info(f"Clean: {transaction_ref} | score={final_score:.3f}")

    session.commit()

    return final_score
