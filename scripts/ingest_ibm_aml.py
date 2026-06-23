#!/usr/bin/env python3
"""
Ingest the IBM AML synthetic benchmark dataset (HI-Small_Trans.csv) into
FinSight, then run every ingested transaction through the real
anomaly-detection pipeline (5 rules + Isolation Forest).

Source: https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml

Sampling strategy (v2 — fixes the v1 near-zero detection rate):
  v1 kept all laundering-labeled rows + a RANDOM sample of unrelated normal
  rows. Result: the accounts involved in laundering patterns had almost no
  OTHER transactions in the sample, so history-dependent rules (velocity,
  z-score, dormant, isolation forest) had nothing to compare against and
  never fired. 0/5,177 known laundering transactions got flagged.

  v2 instead pulls EVERY transaction belonging to any account that appears
  in a labeled laundering pattern (sender or receiver) — this naturally
  includes their ordinary, non-laundering activity too, giving the
  history-dependent rules real account history to compare against.

Usage:
    python scripts/ingest_ibm_aml.py --csv /path/to/HI-Small_Trans.csv --score
"""
import argparse
import sys
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.models import Transaction, TransactionStatus
from app.flink.operators.aggregator import score_and_alert

DEMO_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

CURRENCY_MAP = {
    "US Dollar": "USD", "Euro": "EUR", "Yuan": "CNY", "Yen": "JPY",
    "UK Pound": "GBP", "Rupee": "INR", "Ruble": "RUB", "Saudi Riyal": "SAR",
    "Brazil Real": "BRL", "Mexican Peso": "MXN", "Canadian Dollar": "CAD",
    "Australian Dollar": "AUD", "Bitcoin": "BTC", "Shekel": "ILS", "Swiss Franc": "CHF",
}

CHUNK_SIZE = 250_000


def find_laundering_accounts(csv_path: str) -> set:
    rows = []
    for chunk in pd.read_csv(csv_path, chunksize=CHUNK_SIZE):
        rows.append(chunk[chunk["Is Laundering"] == 1])
    laundering = pd.concat(rows, ignore_index=True)
    return set(laundering["Account"]) | set(laundering["Account.1"])


def stream_account_history(csv_path: str, accounts: set) -> pd.DataFrame:
    """Second pass: keep every row touching any account in the laundering-pattern set."""
    matched = []
    scanned = 0
    for chunk in pd.read_csv(csv_path, chunksize=CHUNK_SIZE):
        mask = chunk["Account"].isin(accounts) | chunk["Account.1"].isin(accounts)
        matched.append(chunk[mask])
        scanned += len(chunk)
        print(f"  scanned {scanned:,} rows, matched {sum(len(m) for m in matched):,}...", end="\r")
    print()
    return pd.concat(matched, ignore_index=True)


def row_to_transaction_dict(row, time_shift) -> dict:
    """
    time_shift: timedelta added to the dataset's original timestamp so that
    transactions land within the rules' recency windows (last 1h/24h/30d are
    computed relative to wall-clock "now" — the IBM dataset is dated 2022,
    so without this shift every velocity/structuring/zscore/dormant rule and
    the Isolation Forest's amount_normalized feature silently degrade to
    their no-history defaults).
    """
    currency = CURRENCY_MAP.get(row["Payment Currency"], "USD")
    return {
        "id": uuid.uuid4(),
        "tenant_id": DEMO_TENANT_ID,
        "transaction_ref": f"IBM-{uuid.uuid4().hex[:12].upper()}",
        "sender_account": str(row["Account"]),
        "receiver_account": str(row["Account.1"]),
        "amount": Decimal(str(row["Amount Paid"])),
        "currency": currency,
        "channel": str(row["Payment Format"]),
        "status": TransactionStatus.PENDING,
        "anomaly_score": 0.0,
        "is_suspicious": False,
        "metadata_json": {
            "source": "IBM_AML_HI_Small",
            "true_label": int(row["Is Laundering"]),
        },
        "created_at": pd.to_datetime(row["Timestamp"]).to_pydatetime() + time_shift,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Path to HI-Small_Trans.csv")
    parser.add_argument("--score", action="store_true", help="Run anomaly scoring after ingestion")
    args = parser.parse_args()

    print("Pass 1: finding accounts involved in labeled laundering patterns...")
    accounts = find_laundering_accounts(args.csv)
    print(f"  {len(accounts):,} unique accounts involved in laundering patterns")

    print("Pass 2: pulling full transaction history for those accounts...")
    combined = stream_account_history(args.csv, accounts)
    laundering_count = int((combined["Is Laundering"] == 1).sum())
    print(f"Total rows to ingest  : {len(combined):,}  (includes {laundering_count:,} labeled laundering rows)")

    combined = combined.sample(frac=1, random_state=42).reset_index(drop=True)  # shuffle

    # Shift the dataset's 2022 timestamps so the latest transaction lands "now" —
    # preserves relative gaps (velocity/structuring patterns intact) while making
    # the rules' recency windows (1h/24h/30d) actually have something to compare against.
    max_ts = pd.to_datetime(combined["Timestamp"]).max()
    time_shift = datetime.utcnow() - max_ts.to_pydatetime()
    print(f"Time-shifting dataset by {time_shift} so it lands within recency windows")

    engine = create_engine(settings.database_sync_url)
    Session = sessionmaker(bind=engine)

    print("Bulk inserting transactions...")
    BATCH = 5000
    txn_ids = []
    with Session() as session:
        records = [row_to_transaction_dict(row, time_shift) for _, row in combined.iterrows()]
        for i in range(0, len(records), BATCH):
            batch = records[i:i + BATCH]
            session.bulk_insert_mappings(Transaction, batch)
            session.commit()
            txn_ids.extend(r["transaction_ref"] for r in batch)
            print(f"  inserted {min(i + BATCH, len(records)):,} / {len(records):,}", end="\r")
    print()
    print(f"Ingestion complete: {len(txn_ids):,} transactions loaded.")

    if args.score:
        print("Running anomaly-detection pipeline over ingested transactions...")
        flagged = 0
        with Session() as session:
            for i, ref in enumerate(txn_ids, 1):
                score = score_and_alert(ref, session)
                if score >= 0.60:
                    flagged += 1
                if i % 500 == 0:
                    print(f"  scored {i:,} / {len(txn_ids):,} (flagged so far: {flagged})", end="\r")
        print()
        print(f"Scoring complete: {flagged:,} / {len(txn_ids):,} flagged as suspicious.")


if __name__ == "__main__":
    main()
