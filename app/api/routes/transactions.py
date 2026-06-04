import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

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
    description=(
        "Accepts a transaction payload from a payment gateway or simulator. "
        "Validates the payload, publishes it to Kafka, and returns immediately. "
        "Actual compliance processing happens asynchronously in the background consumer."
    ),
)
async def ingest_transaction(payload: TransactionAPIRequest):
    """
    Returns 202 Accepted — not 201 Created — because the transaction has been
    queued in Kafka but not yet written to the database. The consumer does that
    asynchronously. This keeps the API response time under 5ms regardless of
    DB load.
    """
    event = TransactionEventSchema(
        transaction_ref=payload.transaction_ref,
        sender_account=payload.sender_account,
        receiver_account=payload.receiver_account,
        amount=payload.amount,
        currency=payload.currency,
        channel=payload.channel,
        tenant_id=payload.tenant_id,
        timestamp=datetime.now(timezone.utc),
        metadata=payload.metadata or {},
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
