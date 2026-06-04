#!/usr/bin/env python3
"""
Train the Isolation Forest anomaly detection model.

Generates synthetic 'normal' transaction data and trains the model to learn
what normal looks like. At runtime, transactions that deviate significantly
from this learned normal get high anomaly scores.

Run once before starting the application:
    python scripts/train_model.py
"""
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

MODELS_DIR = Path(__file__).parent.parent / "models"
MODEL_PATH = MODELS_DIR / "isolation_forest.pkl"
N_SAMPLES = 10_000
RANDOM_SEED = 42

# Feature order (must match isolation_forest_scorer.py exactly):
# [amount_normalized, hour_of_day, day_of_week, is_new_counterparty, txn_count_1h, txn_count_24h]


def generate_normal_transactions(n: int) -> np.ndarray:
    """
    Simulate realistic 'normal' transaction behaviour for training.

    Normal transactions look like:
    - Amount close to the account's own average (normalized ≈ 0.5–2.0)
    - Business hours (9 AM–9 PM peak)
    - Weekdays busier than weekends
    - Mostly known counterparties (85% repeat)
    - Low frequency (1–3 per hour, 5–15 per day)
    """
    rng = np.random.default_rng(RANDOM_SEED)
    samples = []

    for _ in range(n):
        amount_normalized = float(rng.lognormal(mean=0.0, sigma=0.5))

        hour_weights_raw = (
            [0.005] * 5       # 00:00–04:59  almost no activity
            + [0.010] * 3     # 05:00–07:59  early morning
            + [0.060] * 3     # 08:00–10:59  morning rush
            + [0.070] * 4     # 11:00–14:59  midday peak
            + [0.060] * 4     # 15:00–18:59  afternoon
            + [0.040] * 3     # 19:00–21:59  evening
            + [0.010] * 2     # 22:00–23:59  late night
        )
        total = sum(hour_weights_raw)
        hour_weights = [w / total for w in hour_weights_raw]
        hour_of_day = int(rng.choice(24, p=hour_weights))

        day_of_week = int(rng.choice(7, p=[0.17, 0.17, 0.17, 0.17, 0.17, 0.08, 0.07]))

        is_new_counterparty = float(rng.choice([0.0, 1.0], p=[0.85, 0.15]))

        txn_count_1h = int(rng.integers(0, 4))
        txn_count_24h = int(rng.integers(1, 15))

        samples.append([
            amount_normalized,
            hour_of_day,
            day_of_week,
            is_new_counterparty,
            txn_count_1h,
            txn_count_24h,
        ])

    return np.array(samples)


def train() -> None:
    print(f"Generating {N_SAMPLES:,} synthetic normal transactions...")
    X_train = generate_normal_transactions(N_SAMPLES)

    print("Training Isolation Forest...")
    model = IsolationForest(
        n_estimators=100,
        contamination=0.05,  # expect ~5% anomalies in real traffic
        random_state=RANDOM_SEED,
        n_jobs=-1,
    )
    model.fit(X_train)

    MODELS_DIR.mkdir(exist_ok=True)
    joblib.dump(model, MODEL_PATH)

    size_kb = MODEL_PATH.stat().st_size / 1024
    print(f"Model saved → {MODEL_PATH}  ({size_kb:.1f} KB)")

    # Sanity check: normal vs suspicious transaction
    normal    = np.array([[1.0,  14, 2, 0.0, 1,  5]])   # ₹avg amount, 2pm, Tuesday, known counterparty
    suspicious = np.array([[18.0,  2, 0, 1.0, 9, 22]])  # 18× avg, 2am, Monday, new counterparty

    print("\nSanity check (positive score = normal, negative = anomalous):")
    print(f"  Normal transaction    : {model.decision_function(normal)[0]:+.4f}")
    print(f"  Suspicious transaction: {model.decision_function(suspicious)[0]:+.4f}")
    print("\nModel ready. You can now start the application.")


if __name__ == "__main__":
    train()
