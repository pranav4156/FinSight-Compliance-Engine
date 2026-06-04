from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Transaction


def check_velocity(txn: Transaction, session: Session) -> float:
    """
    Detect velocity attacks: too many transactions from the same account
    in a short window.

    Rules:
      ≥ 8 transactions in 60 seconds → 1.0  (critical)
      ≥ 5 transactions in 60 seconds → 0.7  (high)
      ≥ 3 transactions in 60 seconds → 0.4  (medium)

    Edge case covered: #12 (velocity burst)
    """
    window_start = datetime.utcnow() - timedelta(seconds=60)

    count = session.execute(
        select(func.count(Transaction.id)).where(
            Transaction.sender_account == txn.sender_account,
            Transaction.tenant_id == txn.tenant_id,
            Transaction.created_at >= window_start,
            Transaction.id != txn.id,  # exclude the transaction being scored
        )
    ).scalar() or 0

    if count >= 8:
        return 1.0
    if count >= 5:
        return 0.7
    if count >= 3:
        return 0.4
    return 0.0
