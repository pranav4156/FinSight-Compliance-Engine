import logging
import math
from datetime import datetime, timedelta
from pathlib import Path

import joblib
import numpy as np

from app.db.models import Transaction
from app.flink.operators.history import AccountHistory

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent.parent.parent.parent / "models" / "isolation_forest.pkl"

# Feature order — must exactly match scripts/train_model.py
# [amount_normalized, hour_of_day, day_of_week, is_new_counterparty, txn_count_1h, txn_count_24h]

_model = None


def _load_model():
    global _model
    if _model is None:
        if not MODEL_PATH.exists():
            logger.warning(
                f"Isolation Forest model not found at {MODEL_PATH}. "
                "Run: python scripts/train_model.py"
            )
            return None
        _model = joblib.load(MODEL_PATH)
        logger.info("Isolation Forest model loaded")
    return _model


def _build_features(txn: Transaction, history: AccountHistory) -> list:
    """
    Extract the 6 features used during training.

    All recency windows are anchored to the transaction's own created_at,
    not wall-clock now() — see velocity_check.py for why this matters for
    batch scoring.
    """
    now = txn.created_at or datetime.utcnow()
    one_hour_ago = now - timedelta(hours=1)
    one_day_ago = now - timedelta(days=1)
    thirty_days_ago = now - timedelta(days=30)

    rows = history.rows

    # Feature 1: amount normalized to 30-day personal average
    recent_30d = [
        float(h.amount) for h in rows
        if h.created_at and h.created_at >= thirty_days_ago
    ]
    avg_30d = sum(recent_30d) / len(recent_30d) if recent_30d else float(txn.amount)
    amount_normalized = float(txn.amount) / avg_30d if avg_30d > 0 else 1.0

    # Feature 2 & 3: time of transaction
    txn_time = txn.created_at or now
    hour_of_day = txn_time.hour
    day_of_week = txn_time.weekday()

    # Feature 4: is this a new counterparty?
    known_receivers = {h.receiver_account for h in rows}
    is_new_counterparty = 0.0 if txn.receiver_account in known_receivers else 1.0

    # Feature 5 & 6: recent transaction frequency
    txn_count_1h = sum(1 for h in rows if h.created_at and h.created_at >= one_hour_ago)
    txn_count_24h = sum(1 for h in rows if h.created_at and h.created_at >= one_day_ago)

    return [amount_normalized, hour_of_day, day_of_week, is_new_counterparty, txn_count_1h, txn_count_24h]


def score_isolation_forest(txn: Transaction, history: AccountHistory) -> float:
    """
    Score a transaction using the trained Isolation Forest model.

    The model learned what 'normal' looks like from 10,000 synthetic
    transactions during training. Transactions that deviate from normal
    across multiple feature dimensions simultaneously get high scores.

    This catches patterns that individual rules miss — e.g., a transaction
    that passes velocity check AND Z-score check but is still suspicious
    because it combines an unusual amount + unusual time + new counterparty.

    Returns 0.0–1.0 (higher = more anomalous). Returns 0.0 if model not loaded.

    Edge cases covered: #14 (cold-start handled gracefully), #19 (account takeover),
                        #22 (score drift — retrain model periodically)
    """
    model = _load_model()
    if model is None:
        return 0.0

    try:
        features = _build_features(txn, history)
        X = np.array(features).reshape(1, -1)

        # decision_function: negative = anomaly, positive = normal
        raw_score = model.decision_function(X)[0]

        # Convert to 0–1 range using sigmoid:
        # raw_score very negative → sigmoid → close to 1.0 (anomalous)
        # raw_score positive       → sigmoid → close to 0.0 (normal)
        normalized = 1.0 / (1.0 + math.exp(raw_score * 5))

        return float(normalized)

    except Exception as e:
        logger.error(f"Isolation Forest scoring failed: {e}")
        return 0.0
