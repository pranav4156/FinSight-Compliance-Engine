import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.kafka.schemas import TransactionAPIRequest, TransactionChannel, TransactionEventSchema


def _valid_event(**overrides) -> dict:
    base = {
        "transaction_ref": "TXN-TEST-001",
        "sender_account": "sender@okaxis",
        "receiver_account": "receiver@ybl",
        "amount": Decimal("5000.00"),
        "currency": "INR",
        "channel": TransactionChannel.UPI,
        "tenant_id": uuid.uuid4(),
        "timestamp": datetime.now(timezone.utc),
        "metadata": {},
    }
    base.update(overrides)
    return base


def test_valid_event_passes():
    event = TransactionEventSchema(**_valid_event())
    assert event.transaction_ref == "TXN-TEST-001"
    assert event.amount == Decimal("5000.00")


def test_negative_amount_rejected():
    with pytest.raises(ValidationError, match="greater than zero"):
        TransactionEventSchema(**_valid_event(amount=Decimal("-100")))


def test_zero_amount_rejected():
    with pytest.raises(ValidationError, match="greater than zero"):
        TransactionEventSchema(**_valid_event(amount=Decimal("0")))


def test_timezone_naive_timestamp_rejected():
    with pytest.raises(ValidationError, match="timezone"):
        TransactionEventSchema(**_valid_event(timestamp=datetime.utcnow()))


def test_blank_transaction_ref_rejected():
    with pytest.raises(ValidationError):
        TransactionEventSchema(**_valid_event(transaction_ref="   "))


def test_invalid_channel_rejected():
    with pytest.raises(ValidationError):
        TransactionAPIRequest(
            transaction_ref="TXN-001",
            sender_account="a@okaxis",
            receiver_account="b@ybl",
            amount=Decimal("1000"),
            channel="WIRE_TRANSFER",   # not in enum
            tenant_id=uuid.uuid4(),
        )


def test_amount_stored_as_decimal():
    event = TransactionEventSchema(**_valid_event(amount=Decimal("48000000.50")))
    # Must be exact — no float rounding
    assert event.amount == Decimal("48000000.50")
