from datetime import datetime, timedelta

from app.db.models import Transaction
from app.flink.operators.history import AccountHistory


def check_velocity(txn: Transaction, history: AccountHistory) -> float:
    """
    Detect velocity attacks: too many transactions from the same account
    in a short window.

    Rules:
      ≥ 8 transactions in 60 seconds → 1.0  (critical)
      ≥ 5 transactions in 60 seconds → 0.7  (high)
      ≥ 3 transactions in 60 seconds → 0.4  (medium)

    Edge case covered: #12 (velocity burst)

    Window is anchored to the transaction's own created_at, not wall-clock
    now(). For live streaming these are the same moment; for batch-scoring
    historical data long after ingestion they are not — anchoring to now()
    would make every window comparison meaningless for anything but the
    most recently-loaded row.
    """
    reference_time = txn.created_at or datetime.utcnow()
    window_start = reference_time - timedelta(seconds=60)

    count = sum(1 for h in history.rows if h.created_at and h.created_at >= window_start)

    if count >= 8:
        return 1.0
    if count >= 5:
        return 0.7
    if count >= 3:
        return 0.4
    return 0.0
