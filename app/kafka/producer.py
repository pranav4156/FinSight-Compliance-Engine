import json
import logging
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from kafka import KafkaProducer
from kafka.errors import KafkaError

from app.core.config import settings
from app.kafka.schemas import TransactionEventSchema

logger = logging.getLogger(__name__)

_producer: KafkaProducer | None = None


class _EventEncoder(json.JSONEncoder):
    """Safely serialize Decimal and datetime types that standard JSON cannot handle."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        return super().default(obj)


def get_producer() -> KafkaProducer:
    global _producer
    if _producer is None:
        _producer = KafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
            value_serializer=lambda v: json.dumps(v, cls=_EventEncoder).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            acks="all",         # broker + all replicas must confirm before returning
            retries=3,
            retry_backoff_ms=500,
        )
    return _producer


def publish_transaction(event: TransactionEventSchema) -> bool:
    """
    Publish a transaction event to the raw-transactions Kafka topic.

    Partitioned by sender_account so all transactions from the same account
    always land on the same partition in order — required for velocity checks
    in Module 3 (Flink cannot count across partitions in a single window).
    """
    producer = get_producer()
    try:
        future = producer.send(
            topic=settings.kafka_topic_raw_transactions,
            key=event.sender_account,
            value=event.model_dump(mode="json"),
        )
        future.get(timeout=10)
        logger.info(f"Queued transaction {event.transaction_ref} → Kafka")
        return True
    except KafkaError as e:
        logger.error(f"Kafka publish failed for {event.transaction_ref}: {e}")
        return False


def close_producer():
    global _producer
    if _producer:
        _producer.close()
        _producer = None
