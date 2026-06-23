from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Transaction

HISTORY_LIMIT = 200


@dataclass
class HistoryRow:
    amount: object
    receiver_account: str
    created_at: datetime


@dataclass
class AccountHistory:
    rows: list[HistoryRow]


def fetch_account_history(txn: Transaction, session: Session) -> AccountHistory:
    """
    Single shared query for an account's transaction history, used by all
    sender-account-scoped operators (velocity, structuring, zscore, dormant,
    isolation_forest) instead of each operator querying independently.

    This is the throughput fix: 5 separate per-operator DB round-trips per
    transaction collapsed into 1. The graph_cycle_detector is intentionally
    excluded — its query is tenant-wide, not sender-scoped, a different shape
    that can't be served from this same result set.

    created_at <= txn.created_at keeps this causally correct: in live
    streaming, "future" transactions can't exist yet, so history is
    naturally everything-before-now. When batch-scoring already-loaded
    historical data, all rows already exist in the table regardless of
    timestamp — without this filter, an operator could "see" transactions
    that happen after the one being scored, which is not a valid history.
    """
    reference_time = txn.created_at or datetime.utcnow()
    rows = session.execute(
        select(
            Transaction.amount,
            Transaction.receiver_account,
            Transaction.created_at,
        ).where(
            Transaction.sender_account == txn.sender_account,
            Transaction.tenant_id == txn.tenant_id,
            Transaction.id != txn.id,
            Transaction.created_at <= reference_time,
        ).order_by(Transaction.created_at.desc()).limit(HISTORY_LIMIT)
    ).all()

    return AccountHistory(rows=[HistoryRow(r.amount, r.receiver_account, r.created_at) for r in rows])
