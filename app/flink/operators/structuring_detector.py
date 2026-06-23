from datetime import datetime, timedelta
from decimal import Decimal

from app.db.models import Transaction
from app.flink.operators.history import AccountHistory

# RBI/PMLA reporting threshold — transactions below this don't need mandatory reporting
PMLA_THRESHOLD = Decimal("50000")

# Structuring window: lower bound for sub-threshold transactions we track
STRUCTURING_LOWER = Decimal("40000")

# Rolling window to aggregate transactions
WINDOW_HOURS = 24

# Minimum number of sub-threshold transactions to qualify as structuring
MIN_TXN_COUNT = 3


def check_structuring(txn: Transaction, history: AccountHistory) -> float:
    """
    Detect structuring (smurfing): deliberately splitting a large sum into
    multiple transactions just below the ₹50,000 PMLA reporting threshold
    to avoid triggering mandatory reporting.

    Classic pattern: 8 × ₹48,500 = ₹3.88L total, each transaction never
    crosses the ₹50,000 line individually, but together they clearly represent
    a deliberate evasion strategy.

    Edge case covered: #11 (structuring / smurfing)

    Window is anchored to the transaction's own created_at, not wall-clock
    now() — see velocity_check.py for why this matters for batch scoring.
    """
    reference_time = txn.created_at or datetime.utcnow()
    window_start = reference_time - timedelta(hours=WINDOW_HOURS)

    recent_amounts = [
        h.amount for h in history.rows
        if h.created_at and h.created_at >= window_start
        and STRUCTURING_LOWER <= h.amount < PMLA_THRESHOLD
    ]

    # Include the current transaction in the analysis
    all_amounts = list(recent_amounts)
    if STRUCTURING_LOWER <= txn.amount < PMLA_THRESHOLD:
        all_amounts.append(txn.amount)

    count = len(all_amounts)
    total = sum(all_amounts, Decimal("0"))

    # Multiple sub-threshold transactions whose total clearly exceeds the threshold
    if count >= MIN_TXN_COUNT and total >= PMLA_THRESHOLD:
        return 1.0

    # Two transactions that together approach or exceed the threshold
    if count >= 2 and total >= STRUCTURING_LOWER:
        return 0.5

    return 0.0
