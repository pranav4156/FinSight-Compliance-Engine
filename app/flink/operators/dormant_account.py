from datetime import datetime

from app.db.models import Transaction
from app.flink.operators.history import AccountHistory

DORMANCY_DAYS = 90
AMOUNT_MULTIPLIER = 2.0
MIN_HISTORY = 5
HISTORY_LIMIT = 100


def check_dormant(txn: Transaction, history: AccountHistory) -> float:
    """
    Detect dormant account revival: an account silent for 90+ days that
    suddenly processes a large transaction.

    An account being dormant then suddenly active is suspicious on its own.
    It's even more suspicious if the amount is significantly above their
    historical average — suggesting the account may have been taken over
    or is being used as a one-time money mule.

    Score:
      Dormant + amount > 2× average  → 1.0
      Dormant + normal amount         → 0.5
      Active account                  → 0.0

    Edge cases covered: #16 (dormant account revival), #19 (account takeover)

    "Days inactive" is measured relative to the transaction's own created_at,
    not wall-clock now() — see velocity_check.py for why this matters for
    batch scoring.
    """
    rows = history.rows[:HISTORY_LIMIT]

    if len(rows) < MIN_HISTORY:
        return 0.0  # not enough history to classify as dormant

    last_date = rows[0].created_at
    reference_time = txn.created_at or datetime.utcnow()

    # Normalize to UTC naive for comparison
    if hasattr(last_date, "tzinfo") and last_date.tzinfo is not None:
        last_date = last_date.replace(tzinfo=None)
    if hasattr(reference_time, "tzinfo") and reference_time.tzinfo is not None:
        reference_time = reference_time.replace(tzinfo=None)

    days_inactive = (reference_time - last_date).days

    if days_inactive < DORMANCY_DAYS:
        return 0.0  # account has been active recently

    # Account was dormant — check if amount is abnormally large
    avg = sum(float(h.amount) for h in rows) / len(rows)

    if float(txn.amount) > avg * AMOUNT_MULTIPLIER:
        return 1.0

    return 0.5  # dormant revival alone warrants moderate suspicion
