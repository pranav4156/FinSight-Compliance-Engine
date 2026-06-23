from decimal import Decimal
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class TransactionChannel(str, Enum):
    UPI = "UPI"
    NEFT = "NEFT"
    RTGS = "RTGS"
    IMPS = "IMPS"
    CARD = "CARD"
    CASH = "CASH"


class TransactionEventSchema(BaseModel):
    """
    The strict contract for every transaction event travelling through Kafka.
    If a message does not match this shape exactly, it is rejected to the DLQ.
    """
    transaction_ref: str
    sender_account: str
    receiver_account: str
    amount: Decimal
    currency: str = "INR"
    channel: TransactionChannel
    tenant_id: UUID
    timestamp: datetime
    metadata: dict = {}

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Amount must be greater than zero")
        return v

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("Timestamp must include timezone info (e.g. +05:30 or UTC)")
        return v

    @field_validator("transaction_ref")
    @classmethod
    def ref_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("transaction_ref cannot be empty or blank")
        return v.strip()

    @field_validator("sender_account", "receiver_account")
    @classmethod
    def accounts_must_differ(cls, v: str) -> str:
        return v.strip()


class TransactionAPIRequest(BaseModel):
    """What external systems (payment gateways, simulator) send to POST /api/v1/transactions.
    tenant_id is optional — the route handler always overrides it with the JWT's tenant_id.
    """
    transaction_ref: str
    sender_account: str
    receiver_account: str
    amount: Decimal
    currency: str = "INR"
    channel: TransactionChannel
    tenant_id: Optional[UUID] = None
    metadata: Optional[dict] = {}

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Amount must be greater than zero")
        return v


class TransactionAPIResponse(BaseModel):
    """What the API returns immediately after queuing a transaction."""
    status: str
    transaction_ref: str
    message: str
