import json
import logging
from datetime import datetime, timezone

from kafka import KafkaProducer

from app.core.config import settings

logger = logging.getLogger(__name__)

_dlq_producer: KafkaProducer | None = None


def _get_dlq_producer() -> KafkaProducer:
    global _dlq_producer
    if _dlq_producer is None:
        _dlq_producer = KafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks=1,
        )
    return _dlq_producer


def send_to_dlq(raw_message: bytes, error_reason: str, source_topic: str) -> None:
    """
    Park a failed message in the dead letter queue with full context.

    Every DLQ entry contains:
    - The original raw message bytes (for replay if the bug is fixed)
    - The exact error that caused the failure
    - Which topic the message came from
    - When the failure occurred

    If the DLQ write itself fails, we log at CRITICAL level — this means
    messages are being silently dropped and on-call must be notified.
    """
    payload = {
        "original_message": raw_message.decode("utf-8", errors="replace"),
        "error_reason": error_reason,
        "source_topic": source_topic,
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _get_dlq_producer().send(topic=settings.kafka_topic_dlq, value=payload)
        logger.warning(f"DLQ ← {source_topic} | {error_reason[:120]}")
    except Exception as e:
        logger.critical(
            f"FAILED TO WRITE TO DLQ — message is being dropped. "
            f"DLQ error: {e} | Original error: {error_reason}"
        )
