#!/usr/bin/env python3
"""
Kafka throughput benchmark for FinSight.

Measures two distinct numbers — don't conflate them:
  1. Producer throughput  : how fast we can publish events/sec to Kafka.
  2. End-to-end throughput: how fast events are actually consumed, validated,
     persisted to Postgres, and scored by all 6 anomaly-detection operators
     (the real, honest number — the one that matters for the resume claim).

Usage:
    python scripts/kafka_throughput_benchmark.py --count 20000 --consumers 6
"""
import argparse
import json
import sys
import threading
import time
import uuid
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from kafka import KafkaConsumer, KafkaProducer
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.models import Transaction
from app.flink.operators.aggregator import score_and_alert

TENANT_ID = "11111111-1111-1111-1111-111111111111"  # dedicated benchmark tenant — isolated from IBM dataset volume
TOPIC = settings.kafka_topic_raw_transactions


def make_event(i: int) -> dict:
    return {
        "transaction_ref": f"BENCH-{uuid.uuid4().hex[:10].upper()}",
        "sender_account": f"BENCH-SENDER-{i % 5000}",
        "receiver_account": f"BENCH-RECEIVER-{(i + 1) % 5000}",
        "amount": str(Decimal(100 + (i % 9000))),
        "currency": "INR",
        "channel": "UPI",
        "tenant_id": TENANT_ID,
        "timestamp": "2026-06-23T10:00:00+00:00",
        "metadata": {},
    }


def run_producer_benchmark(count: int) -> tuple[float, list[str]]:
    producer = KafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
        acks="all",
        retries=3,
    )

    refs = []
    start = time.time()
    for i in range(count):
        event = make_event(i)
        refs.append(event["transaction_ref"])
        producer.send(TOPIC, key=event["sender_account"], value=event)
    producer.flush()
    elapsed = time.time() - start
    producer.close()
    return elapsed, refs


def consumer_worker(stop_flag: threading.Event, processed_counter: list, lock: threading.Lock):
    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=settings.kafka_bootstrap_servers.split(","),
        group_id="finsight-benchmark-consumer",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        consumer_timeout_ms=2000,
    )
    engine = create_engine(settings.database_sync_url, pool_size=2, max_overflow=2)
    Session = sessionmaker(bind=engine)

    idle_polls = 0
    while not stop_flag.is_set() and idle_polls < 5:
        got_message = False
        for message in consumer:
            got_message = True
            try:
                data = json.loads(message.value.decode("utf-8"))
                ref = data["transaction_ref"]
                if not ref.startswith("BENCH-"):
                    continue
                with Session() as session:
                    existing = session.execute(
                        select(Transaction).where(Transaction.transaction_ref == ref)
                    ).scalar_one_or_none()
                    if existing is None:
                        txn = Transaction(
                            tenant_id=TENANT_ID,
                            transaction_ref=ref,
                            sender_account=data["sender_account"],
                            receiver_account=data["receiver_account"],
                            amount=Decimal(data["amount"]),
                            currency=data["currency"],
                            channel=data["channel"],
                        )
                        session.add(txn)
                        session.commit()
                        score_and_alert(ref, session)
                with lock:
                    processed_counter[0] += 1
            except Exception:
                pass
            finally:
                consumer.commit()
            if stop_flag.is_set():
                break
        if not got_message:
            idle_polls += 1
    consumer.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20000)
    parser.add_argument("--consumers", type=int, default=6)
    args = parser.parse_args()

    print(f"Publishing {args.count:,} events to '{TOPIC}'...")
    publish_elapsed, refs = run_producer_benchmark(args.count)
    producer_rate = args.count / publish_elapsed
    print(f"Producer throughput : {producer_rate:,.0f} events/sec ({publish_elapsed:.2f}s for {args.count:,} events)")

    print(f"\nStarting {args.consumers} parallel consumer threads for end-to-end processing...")
    stop_flag = threading.Event()
    processed_counter = [0]
    lock = threading.Lock()

    threads = [
        threading.Thread(target=consumer_worker, args=(stop_flag, processed_counter, lock))
        for _ in range(args.consumers)
    ]

    start = time.time()
    for t in threads:
        t.start()

    last_count = 0
    stall_ticks = 0
    while True:
        time.sleep(2)
        with lock:
            current = processed_counter[0]
        print(f"  processed {current:,} / {args.count:,}...", end="\r")
        if current >= args.count:
            break
        if current == last_count:
            stall_ticks += 1
            if stall_ticks > 10:
                print("\n  (stalled — stopping)")
                break
        else:
            stall_ticks = 0
        last_count = current

    elapsed = time.time() - start
    stop_flag.set()
    for t in threads:
        t.join(timeout=5)

    with lock:
        final_count = processed_counter[0]

    print()
    print(f"End-to-end throughput: {final_count / elapsed:,.0f} events/sec "
          f"({final_count:,} events fully consumed + persisted + scored in {elapsed:.2f}s "
          f"across {args.consumers} consumer threads)")


if __name__ == "__main__":
    main()
