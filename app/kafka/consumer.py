import json
import logging
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal

from kafka import KafkaConsumer
from kafka.errors import KafkaError
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.models import Transaction, TransactionStatus
from app.kafka.dlq import send_to_dlq
from app.kafka.schemas import TransactionEventSchema

logger = logging.getLogger(__name__)

# Transactions above this amount get pre-flagged for Module 3 (Flink)
SUSPICIOUS_AMOUNT_THRESHOLD = Decimal("500000")  # ₹5 lakh

# Sync DB engine — the consumer runs in a background thread, not async
_engine = create_engine(settings.database_sync_url, pool_size=5, max_overflow=10)
_SyncSession = sessionmaker(bind=_engine)

# Used to gracefully stop the consumer on app shutdown
_stop_event = threading.Event()


def _persist_transaction(event: TransactionEventSchema) -> bool:
    """
    Write a validated transaction to PostgreSQL.

    Returns True  → transaction was written (new record)
    Returns False → transaction already exists (idempotent skip)

    The idempotency check prevents duplicate records when Kafka delivers
    the same message more than once (at-least-once delivery guarantee).
    The IntegrityError catch handles the race condition where two consumer
    instances check simultaneously and both try to insert.
    """
    with _SyncSession() as session:
        existing = session.execute(
            select(Transaction).where(
                Transaction.transaction_ref == event.transaction_ref
            )
        ).scalar_one_or_none()

        if existing:
            logger.info(f"Duplicate skipped: {event.transaction_ref}")
            return False

        is_suspicious = event.amount >= SUSPICIOUS_AMOUNT_THRESHOLD

        txn = Transaction(
            tenant_id=event.tenant_id,
            transaction_ref=event.transaction_ref,
            sender_account=event.sender_account,
            receiver_account=event.receiver_account,
            amount=event.amount,
            currency=event.currency,
            channel=event.channel.value,
            status=TransactionStatus.PENDING,
            is_suspicious=is_suspicious,
            metadata_json={
                "ingested_at": datetime.now(timezone.utc).isoformat(),
                "original_timestamp": event.timestamp.isoformat(),
                **event.metadata,
            },
        )
        session.add(txn)

        try:
            session.commit()
            logger.info(
                f"Saved: {event.transaction_ref} | "
                f"₹{event.amount:,} | "
                f"{'🚨 SUSPICIOUS' if is_suspicious else '✓ clean'}"
            )
            return True
        except IntegrityError:
            session.rollback()
            logger.info(f"Race condition on {event.transaction_ref} — skipped")
            return False


def _process_message(raw_value: bytes) -> None:
    """
    Process a single raw Kafka message bytes through 3 stages:
      1. JSON parsing     — malformed bytes → DLQ
      2. Schema validation — wrong shape/types → DLQ
      3. DB persistence   — idempotent write to PostgreSQL
    """
    source = settings.kafka_topic_raw_transactions

    try:
        data = json.loads(raw_value.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        send_to_dlq(raw_value, f"JSON parse error: {e}", source)
        return

    try:
        event = TransactionEventSchema(**data)
    except ValidationError as e:
        send_to_dlq(raw_value, f"Schema invalid: {e.error_count()} error(s)", source)
        return

    _persist_transaction(event)


def run_consumer() -> None:
    """
    Blocking consumer loop — designed to run in a background thread.

    Key behaviours:
    - Commits Kafka offsets ONLY after a message is fully processed.
      If the process crashes mid-write, the offset is not committed and
      the message is reprocessed on restart (safe due to idempotency check).
    - Reconnects automatically on Kafka broker restarts or network drops.
    - Stops cleanly when stop_consumer() is called at app shutdown.
    """
    while not _stop_event.is_set():
        consumer = None
        try:
            consumer = KafkaConsumer(
                settings.kafka_topic_raw_transactions,
                bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
                group_id="finsight-compliance-consumer",
                auto_offset_reset="earliest",
                enable_auto_commit=False,
                value_deserializer=None,
                consumer_timeout_ms=1000,
            )
            logger.info(f"Consumer connected → topic: {settings.kafka_topic_raw_transactions}")

            for message in consumer:
                if _stop_event.is_set():
                    break
                try:
                    _process_message(message.value)
                except Exception as e:
                    logger.error(f"Unexpected error on message: {e}")
                    send_to_dlq(
                        message.value or b"",
                        f"Unexpected processing error: {e}",
                        settings.kafka_topic_raw_transactions,
                    )
                finally:
                    consumer.commit()

        except KafkaError as e:
            logger.error(f"Kafka connection error: {e} — reconnecting in 5s")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Consumer crashed: {e} — restarting in 5s")
            time.sleep(5)
        finally:
            if consumer:
                try:
                    consumer.close()
                except Exception:
                    pass


def stop_consumer() -> None:
    """Signal the consumer loop to exit gracefully."""
    _stop_event.set()
