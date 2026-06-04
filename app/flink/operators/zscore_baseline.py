import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Transaction

# Minimum past transactions needed before Z-score is meaningful
MIN_HISTORY = 10

# How many past transactions to use as the baseline window
HISTORY_LIMIT = 100


def check_zscore(txn: Transaction, session: Session) -> float:
    """
    Detect amount anomalies relative to an account's own personal history.

    Z-score formula: z = (current_amount - personal_mean) / personal_std_dev

    A fixed threshold like 'flag if amount > ₹5L' is wrong — ₹5L is normal
    for a trader but suspicious for a student. Z-score is relative: it flags
    transactions that are unusually large FOR THIS SPECIFIC ACCOUNT, regardless
    of the absolute amount.

    Score mapping:
      z > 5  → 1.0  (5 standard deviations above personal mean — extreme)
      z > 3  → 0.8  (3 std devs — very unusual)
      z > 2  → 0.4  (2 std devs — moderately unusual)

    Edge case covered: #15 (legitimate high-volume vs suspicious high-volume)
    """
    history = session.execute(
        select(Transaction.amount).where(
            Transaction.sender_account == txn.sender_account,
            Transaction.tenant_id == txn.tenant_id,
            Transaction.id != txn.id,
        ).order_by(Transaction.created_at.desc()).limit(HISTORY_LIMIT)
    ).scalars().all()

    if len(history) < MIN_HISTORY:
        return 0.0  # not enough history for a reliable baseline

    amounts = [float(a) for a in history]
    mean = sum(amounts) / len(amounts)
    variance = sum((x - mean) ** 2 for x in amounts) / len(amounts)
    std_dev = math.sqrt(variance)

    if std_dev == 0:
        return 0.0  # all past transactions were the same amount — no variance

    z = (float(txn.amount) - mean) / std_dev

    if z > 5:
        return 1.0
    if z > 3:
        return 0.8
    if z > 2:
        return 0.4
    return 0.0
