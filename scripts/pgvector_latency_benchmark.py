#!/usr/bin/env python3
"""
pgvector latency benchmark for FinSight.

The real find_similar_cases() query (app/compliance/embeddings.py) does:
    SELECT * FROM sar_reports
    WHERE tenant_id = :tenant_id AND narrative_embedding IS NOT NULL
    ORDER BY narrative_embedding <-> :embedding LIMIT :limit

We only have a handful of REAL SAR embeddings (each costs a real OpenAI
call to generate). To measure query latency at 100K+ scale honestly, we
bulk-insert synthetic random vectors matching the real embedding model's
dimensionality (1536, same as text-embedding-3-small) directly into the
table — standard load-testing practice. This measures real index/query
performance at scale; it does NOT claim 100K real case narratives.

Usage:
    python scripts/pgvector_latency_benchmark.py --count 100000 --queries 50
"""
import argparse
import random
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text

from app.core.config import settings

DEMO_TENANT_ID = "00000000-0000-0000-0000-000000000001"
DIM = 1536
BATCH = 1000


def random_vector() -> str:
    return "[" + ",".join(f"{random.uniform(-1, 1):.6f}" for _ in range(DIM)) + "]"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100_000)
    parser.add_argument("--queries", type=int, default=50)
    args = parser.parse_args()

    engine = create_engine(settings.database_sync_url)

    print(f"Inserting {args.count:,} synthetic {DIM}-d vectors into sar_reports...")
    for i in range(0, args.count, BATCH):
        batch_size = min(BATCH, args.count - i)
        rows = [
            {
                "id": str(uuid.uuid4()),
                "tenant_id": DEMO_TENANT_ID,
                "narrative": f"SYNTHETIC-LOAD-TEST-{i + j}",
                "embedding": random_vector(),
            }
            for j in range(batch_size)
        ]
        with engine.begin() as conn:  # commit per batch — visible progress, no giant open transaction
            conn.execute(
                text(
                    "INSERT INTO sar_reports (id, tenant_id, narrative, narrative_embedding, created_at) "
                    "VALUES (:id, :tenant_id, :narrative, :embedding, now())"
                ),
                rows,
            )
        print(f"  inserted {min(i + BATCH, args.count):,} / {args.count:,}", flush=True)
    print("Insertion complete.")

    print(f"\nRunning {args.queries} real similarity queries (HNSW index, L2 distance)...")
    latencies = []
    with engine.connect() as conn:
        for _ in range(args.queries):
            query_vec = random_vector()
            start = time.perf_counter()
            conn.execute(
                text(
                    "SELECT id FROM sar_reports "
                    "WHERE tenant_id = :tenant_id AND narrative_embedding IS NOT NULL "
                    "ORDER BY narrative_embedding <-> :embedding LIMIT 3"
                ),
                {"tenant_id": DEMO_TENANT_ID, "embedding": query_vec},
            ).fetchall()
            latencies.append((time.perf_counter() - start) * 1000)

    latencies.sort()
    avg = sum(latencies) / len(latencies)
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[min(int(len(latencies) * 0.99), len(latencies) - 1)]

    print(f"\nResults over {args.queries} queries against {args.count:,} vectors:")
    print(f"  avg: {avg:.2f}ms | p50: {p50:.2f}ms | p95: {p95:.2f}ms | p99: {p99:.2f}ms")


if __name__ == "__main__":
    main()
