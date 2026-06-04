#!/usr/bin/env python3
"""
FinSight Transaction Simulator
--------------------------------
Fires realistic transaction scenarios at the local API for end-to-end testing.
Each scenario is designed to trigger (or not trigger) a specific compliance rule.

Usage:
    python scripts/simulate_transactions.py                  # all scenarios
    python scripts/simulate_transactions.py --scenario arjun_mehta
    python scripts/simulate_transactions.py --scenario structuring
"""
import argparse
import random
import sys
import time
import uuid

import requests

BASE_URL  = "http://localhost:8000/api/v1"
API_URL   = f"{BASE_URL}/transactions"

ADMIN_EMAIL    = "admin@finsight.dev"
ADMIN_PASSWORD = "Admin@123"
TENANT_ID      = "00000000-0000-0000-0000-000000000001"

_token: str | None = None


def get_token() -> str:
    global _token
    if _token:
        return _token
    try:
        resp = requests.post(
            f"{BASE_URL}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=5,
        )
        resp.raise_for_status()
        _token = resp.json()["access_token"]
        print(f"  Authenticated as {ADMIN_EMAIL}")
        return _token
    except Exception as e:
        print(f"  Login failed: {e}")
        print("  Make sure the server is running and seed_admin.py has been run.")
        sys.exit(1)


def _headers() -> dict:
    return {"Authorization": f"Bearer {get_token()}"}


def _post(data: dict) -> None:
    # Remove tenant_id from body — it now comes from the JWT
    data.pop("tenant_id", None)
    try:
        resp = requests.post(API_URL, json=data, headers=_headers(), timeout=5)
        symbol = "✓" if resp.status_code == 202 else "✗"
        print(f"  {symbol} [{resp.status_code}] {data['transaction_ref']} — ₹{float(data['amount']):>14,.2f}")
        if resp.status_code not in (202, 200):
            print(f"    → {resp.json().get('detail', resp.text)[:100]}")
    except requests.exceptions.ConnectionError:
        print("  ✗ Cannot connect to API. Is the server running? (poetry run uvicorn app.main:app --reload)")


def scenario_normal():
    """Normal day trader — low amounts, regular frequency. Should NOT be flagged."""
    print("\n📊  Scenario A — Normal Day Trader (expect: no flags)")
    for i in range(5):
        _post({
            "transaction_ref": f"NORMAL-{uuid.uuid4().hex[:8].upper()}",
            "sender_account": "normal.trader@okaxis",
            "receiver_account": f"merchant_{i}@ybl",
            "amount": str(round(random.uniform(5_000, 45_000), 2)),
            "currency": "INR",
            "channel": "UPI",
            "tenant_id": TENANT_ID,
            "metadata": {"scenario": "normal"},
        })
        time.sleep(0.4)


def scenario_arjun_mehta():
    """
    Insider trading pattern — ₹48L micro-cap buy followed by same-day sell.
    Triggers: volume anomaly, income-to-trade ratio breach, micro-cap concentration.
    """
    print("\n🚨  Scenario B — Arjun Mehta (Insider Trading) (expect: FLAGGED)")
    _post({
        "transaction_ref": f"ARJUN-BUY-{uuid.uuid4().hex[:8].upper()}",
        "sender_account": "arjun.mehta@okaxis",
        "receiver_account": "zerodha_broker@ybl",
        "amount": "4800000.00",
        "currency": "INR",
        "channel": "NEFT",
        "tenant_id": TENANT_ID,
        "metadata": {"stock": "ALPHAGEARS", "action": "buy", "quantity": 12000, "scenario": "insider_trading"},
    })
    print("  ⏱  Simulating 5-hour trading gap...")
    time.sleep(2)
    _post({
        "transaction_ref": f"ARJUN-SELL-{uuid.uuid4().hex[:8].upper()}",
        "sender_account": "zerodha_broker@ybl",
        "receiver_account": "arjun.mehta@okaxis",
        "amount": "6100000.00",
        "currency": "INR",
        "channel": "NEFT",
        "tenant_id": TENANT_ID,
        "metadata": {"stock": "ALPHAGEARS", "action": "sell", "profit": 1_300_000, "scenario": "insider_trading"},
    })


def scenario_structuring():
    """
    Smurfing / Structuring — 8 transactions just below the ₹50,000 PMLA threshold.
    Triggers: structuring detection (sliding window sum approaches reporting limit).
    """
    print("\n🔄  Scenario C — Structuring / Smurfing (expect: FLAGGED)")
    for i in range(8):
        _post({
            "transaction_ref": f"STRUCT-{uuid.uuid4().hex[:8].upper()}",
            "sender_account": "suspicious.smurf@paytm",
            "receiver_account": f"shell_company_{i % 3}@ybl",
            "amount": str(round(random.uniform(47_000, 49_500), 2)),
            "currency": "INR",
            "channel": "UPI",
            "tenant_id": TENANT_ID,
            "metadata": {"scenario": "structuring"},
        })
        time.sleep(0.3)


def scenario_velocity():
    """
    Velocity burst — 10 transactions fired in under 10 seconds from one account.
    Triggers: velocity check (>5 transactions in 60-second window).
    """
    print("\n⚡  Scenario D — Velocity Burst (expect: FLAGGED)")
    for i in range(10):
        _post({
            "transaction_ref": f"VEL-{uuid.uuid4().hex[:8].upper()}",
            "sender_account": "velocity.attacker@okicici",
            "receiver_account": f"receiver_{i}@paytm",
            "amount": str(round(random.uniform(1_000, 10_000), 2)),
            "currency": "INR",
            "channel": "IMPS",
            "tenant_id": TENANT_ID,
            "metadata": {"scenario": "velocity"},
        })
        time.sleep(0.1)


def scenario_round_trip():
    """
    Round-trip money cycle — A → B → C → A (₹5L each leg).
    Triggers: graph cycle detection in Module 3.
    """
    print("\n🔁  Scenario E — Round-Trip Money Cycle (expect: FLAGGED)")
    accounts = ["account_A@okaxis", "account_B@ybl", "account_C@paytm"]
    for i in range(len(accounts)):
        sender = accounts[i]
        receiver = accounts[(i + 1) % len(accounts)]
        _post({
            "transaction_ref": f"CYCLE-{uuid.uuid4().hex[:8].upper()}",
            "sender_account": sender,
            "receiver_account": receiver,
            "amount": "500000.00",
            "currency": "INR",
            "channel": "RTGS",
            "tenant_id": TENANT_ID,
            "metadata": {"scenario": "round_trip", "leg": i + 1},
        })
        time.sleep(0.5)


def scenario_dormant():
    """
    Dormant account revival — account silent for 200+ days, suddenly ₹8L.
    Triggers: dormant account flag in Module 3.
    """
    print("\n😴  Scenario F — Dormant Account Revival (expect: FLAGGED)")
    _post({
        "transaction_ref": f"DORMANT-{uuid.uuid4().hex[:8].upper()}",
        "sender_account": "dormant.account@okhdfc",
        "receiver_account": "unknown.entity@paytm",
        "amount": "800000.00",
        "currency": "INR",
        "channel": "NEFT",
        "tenant_id": TENANT_ID,
        "metadata": {"scenario": "dormant_revival", "days_since_last_active": 200},
    })


SCENARIOS = {
    "normal": scenario_normal,
    "arjun_mehta": scenario_arjun_mehta,
    "structuring": scenario_structuring,
    "velocity": scenario_velocity,
    "round_trip": scenario_round_trip,
    "dormant": scenario_dormant,
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FinSight Transaction Simulator")
    parser.add_argument(
        "--scenario",
        choices=[*SCENARIOS.keys(), "all"],
        default="all",
        help="Which scenario to run (default: all)",
    )
    args = parser.parse_args()

    print("━" * 55)
    print("  🏦  FinSight Transaction Simulator")
    print(f"  Target : {API_URL}")
    print(f"  Tenant : {TENANT_ID}")
    print("━" * 55)

    if args.scenario == "all":
        for fn in SCENARIOS.values():
            fn()
            time.sleep(1)
    else:
        SCENARIOS[args.scenario]()

    print("\n━" * 55)
    print("  Simulation complete.")
    print("  → Check Kafka UI  : http://localhost:8080")
    print("  → Check API docs  : http://localhost:8000/docs")
    print("━" * 55)
