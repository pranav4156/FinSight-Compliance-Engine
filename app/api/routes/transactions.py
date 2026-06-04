import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.compliance.sanctions import screen_transaction
from app.core.dependencies import get_current_user, require_role
from app.core.rate_limiter import check_rate_limit
from app.db.models import Transaction, User, UserRole
from app.db.session import get_db
from app.kafka.producer import publish_transaction
from app.kafka.schemas import (
    TransactionAPIRequest,
    TransactionAPIResponse,
    TransactionEventSchema,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Transactions"])


@router.post(
    "/transactions",
    response_model=TransactionAPIResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a financial transaction event",
)
async def ingest_transaction(
    payload: TransactionAPIRequest,
    current_user: User = Depends(
        require_role(UserRole.ADMIN, UserRole.COMPLIANCE_ANALYST, UserRole.RISK_MANAGER)
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Accepts a transaction, runs sanctions screening, applies rate limiting,
    publishes to Kafka, and returns immediately. Processing is asynchronous.

    Tenant isolation: the transaction is always tagged with the authenticated
    user's tenant_id — the request body tenant_id is ignored.
    """
    # ── Rate limiting (100 transactions/minute per tenant) ────────────────────
    allowed, count = await check_rate_limit(
        tenant_id=str(current_user.tenant_id),
        endpoint="transactions",
        limit=100,
        window_seconds=60,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded ({count}/100 per minute). Retry after 60 seconds.",
        )

    # ── Sanctions screening ───────────────────────────────────────────────────
    screen = screen_transaction(payload.sender_account, payload.receiver_account)
    if screen["flagged"]:
        logger.warning(
            f"SANCTIONS HIT: {payload.transaction_ref} | "
            f"{screen['sender']['message'] or screen['receiver']['message']}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Transaction blocked — sanctions match detected: "
                   f"{screen['sender'].get('message') or screen['receiver'].get('message')}",
        )

    # ── Build Kafka event — tenant_id from JWT, not request body ─────────────
    event = TransactionEventSchema(
        transaction_ref=payload.transaction_ref,
        sender_account=payload.sender_account,
        receiver_account=payload.receiver_account,
        amount=payload.amount,
        currency=payload.currency,
        channel=payload.channel,
        tenant_id=current_user.tenant_id,   # enforced from JWT
        timestamp=datetime.now(timezone.utc),
        metadata={
            **(payload.metadata or {}),
            "sanctions_risk": screen["risk"],
        },
    )

    published = publish_transaction(event)
    if not published:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Kafka unavailable — transaction could not be queued. Retry shortly.",
        )

    return TransactionAPIResponse(
        status="accepted",
        transaction_ref=payload.transaction_ref,
        message="Transaction queued for real-time compliance processing.",
    )


@router.get(
    "/transactions",
    summary="List recent transactions for the current tenant",
)
async def list_transactions(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Tenant isolation enforced — analysts only see their own tenant's transactions.
    Covers edge case #42.
    """
    result = await db.execute(
        select(Transaction)
        .where(Transaction.tenant_id == current_user.tenant_id)
        .order_by(Transaction.created_at.desc())
        .limit(limit)
    )
    txns = result.scalars().all()

    return [
        {
            "id":              str(t.id),
            "transaction_ref": t.transaction_ref,
            "sender_account":  t.sender_account,
            "receiver_account":t.receiver_account,
            "amount":          str(t.amount),
            "currency":        t.currency,
            "channel":         t.channel,
            "status":          t.status.value,
            "anomaly_score":   t.anomaly_score,
            "is_suspicious":   t.is_suspicious,
            "created_at":      str(t.created_at),
        }
        for t in txns
    ]
