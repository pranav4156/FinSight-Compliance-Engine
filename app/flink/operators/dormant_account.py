from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Transaction

DORMANCY_DAYS = 90
AMOUNT_MULTIPLIER = 2.0
MIN_HISTORY = 5


def check_dormant(txn: Transaction, session: Session) -> float:
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
    """
    history = session.execute(
        select(Transaction.amount, Transaction.created_at).where(
            Transaction.sender_account == txn.sender_account,
            Transaction.tenant_id == txn.tenant_id,
            Transaction.id != txn.id,
        ).order_by(Transaction.created_at.desc()).limit(100)
    ).all()

    if len(history) < MIN_HISTORY:
        return 0.0  # not enough history to classify as dormant

    last_txn = history[0]
    last_date = last_txn.created_at

    # Normalize to UTC naive for comparison
    if hasattr(last_date, "tzinfo") and last_date.tzinfo is not None:
        last_date = last_date.replace(tzinfo=None)

    days_inactive = (datetime.utcnow() - last_date).days

    if days_inactive < DORMANCY_DAYS:
        return 0.0  # account has been active recently

    # Account was dormant — check if amount is abnormally large
    avg = sum(float(h.amount) for h in history) / len(history)

    if float(txn.amount) > avg * AMOUNT_MULTIPLIER:
        return 1.0

    return 0.5  # dormant revival alone warrants moderate suspicion
