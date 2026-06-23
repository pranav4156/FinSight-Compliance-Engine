#!/usr/bin/env python3
"""
FinSight End-to-End Demo
--------------------------
Runs the complete compliance pipeline in a single command and prints results.

What this demonstrates:
  1. JWT authentication
  2. Transaction ingestion with sanctions screening
  3. Real-time anomaly detection (Isolation Forest + 5 rules)
  4. Alert creation with severity scoring
  5. SAR narrative generation via GPT-4o
  6. PDF download link

Prerequisites:
  docker compose up -d
  poetry run alembic upgrade head
  python scripts/seed_admin.py
  poetry run uvicorn app.main:app --reload   (in another terminal)

Usage:
  python scripts/demo.py
"""
import sys
import time
import uuid

import requests

BASE_URL       = "http://localhost:8000/api/v1"
ADMIN_EMAIL    = "admin@finsight.dev"
ADMIN_PASSWORD = "Admin@123"

DIVIDER = "━" * 60


def step(n: int, title: str):
    print(f"\n{DIVIDER}")
    print(f"  Step {n}: {title}")
    print(DIVIDER)


def ok(msg: str):  print(f"  ✓  {msg}")
def warn(msg: str): print(f"  ⚠  {msg}")
def fail(msg: str): print(f"  ✗  {msg}"); sys.exit(1)


# ── Step 1: Authenticate ──────────────────────────────────────────────────────
step(1, "Authenticate as admin")
try:
    resp = requests.post(f"{BASE_URL}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=5)
    resp.raise_for_status()
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    ok(f"Logged in as {ADMIN_EMAIL} (role: {resp.json()['role']})")
except Exception as e:
    fail(f"Login failed: {e}\n  Is the server running? (uvicorn app.main:app --reload)")

# ── Step 2: Check system health ───────────────────────────────────────────────
step(2, "Verify system health")
resp = requests.get("http://localhost:8000/health", timeout=5)
data = resp.json()
ok(f"API status    : {data['status']}")
ok(f"Environment   : {data['environment']}")

# ── Step 3a: Build account history (so Z-score and Isolation Forest work) ────
step(3, "Building account history (12 normal transactions)")
print("  Submitting normal trades to establish ₹50,000–₹1,00,000 baseline...")
import random
for i in range(12):
    r = requests.post(f"{BASE_URL}/transactions", headers=headers, json={
        "transaction_ref": f"HIST-{uuid.uuid4().hex[:8].upper()}",
        "sender_account": "arjun.mehta@okaxis",
        "receiver_account": f"broker_{i % 3}@ybl",
        "amount": str(round(random.uniform(50000, 100000), 2)),
        "currency": "INR",
        "channel": "NEFT",
        "metadata": {"demo": "history_building"},
    }, timeout=10)
    print(f"  {'✓' if r.status_code == 202 else '✗'} history txn {i+1}/12")
    time.sleep(0.3)

ok("History built. Waiting 5s for consumer to process...")
time.sleep(5)

# ── Step 3b: Submit the suspicious Arjun Mehta transaction ────────────────────
print()
print(f"  {'━'*54}")
print(f"  Now submitting the anomalous transaction — ₹48L (12x above average)")
print(f"  {'━'*54}")
txn_ref = f"DEMO-ARJUN-{uuid.uuid4().hex[:6].upper()}"
resp = requests.post(f"{BASE_URL}/transactions",
    headers=headers,
    json={
        "transaction_ref": txn_ref,
        "sender_account": "arjun.mehta@okaxis",
        "receiver_account": "zerodha_broker@ybl",
        "amount": "4800000.00",
        "currency": "INR",
        "channel": "NEFT",
        "metadata": {
            "stock": "ALPHAGEARS",
            "action": "buy",
            "quantity": 12000,
            "demo": True,
        },
    },
    timeout=10,
)
if resp.status_code == 202:
    ok(f"Transaction queued : {txn_ref}")
    ok(f"Amount             : ₹48,00,000 (12x personal average of ~₹75,000)")
else:
    warn(f"Unexpected status {resp.status_code}: {resp.text[:200]}")

# ── Step 4: Wait for anomaly scoring ──────────────────────────────────────────
step(4, "Waiting for anomaly detection to complete")
print("  (Consumer reads Kafka → scores all 6 operators → creates alert)")
for i in range(10):
    time.sleep(2)
    txns = requests.get(f"{BASE_URL}/transactions?limit=10", headers=headers, timeout=5)
    if txns.status_code == 200:
        scored = [t for t in txns.json()
                  if t.get("transaction_ref") == txn_ref
                  and t.get("status") in ("flagged", "cleared")]
        if scored:
            txn_data = scored[0]
            ok(f"Transaction scored!")
            ok(f"  Anomaly score : {txn_data['anomaly_score']:.3f}")
            ok(f"  Status        : {txn_data['status'].upper()}")
            ok(f"  Suspicious    : {txn_data['is_suspicious']}")
            break
    print(f"  ... checking ({i+1}/10)")
else:
    warn("Transaction not yet scored — anomaly detection may be catching up")

# ── Step 5: Fetch alert ───────────────────────────────────────────────────────
step(5, "Fetch the generated alert")
alerts_resp = requests.get(f"{BASE_URL}/alerts", headers=headers, timeout=5)
alerts = alerts_resp.json()

if not alerts:
    warn("No alerts found yet — the consumer may still be processing")
    sys.exit(0)

alert = alerts[0]
ok(f"Alert ID   : {alert['id'][:8].upper()}")
ok(f"Severity   : {alert['severity'].upper()}")
ok(f"Rule fired : {alert['rule_triggered']}")

# ── Step 6: Generate SAR ──────────────────────────────────────────────────────
step(6, "Generate SAR report (GPT-4o via LangChain)")
print("  Calling GPT-4o — this takes 10–20 seconds...")

sar_resp = requests.post(
    f"{BASE_URL}/alerts/{alert['id']}/generate-sar",
    headers=headers,
    timeout=120,
)

if sar_resp.status_code == 201:
    sar = sar_resp.json()
    ok(f"SAR generated!")
    ok(f"  SAR ID     : {sar['id'][:8].upper()}")
    ok(f"  PDF path   : {sar.get('pdf_path', 'not yet rendered')}")
    print()
    print("  ── SAR Narrative Preview (first 500 chars) ──")
    print()
    narrative = sar.get("narrative", "")
    print("  " + narrative[:500].replace("\n", "\n  "))
    if len(narrative) > 500:
        print("  ...")
elif sar_resp.status_code == 404:
    warn(f"Alert not found or no transaction linked: {sar_resp.text[:200]}")
else:
    warn(f"SAR generation returned {sar_resp.status_code}: {sar_resp.text[:300]}")

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{DIVIDER}")
print("  DEMO COMPLETE")
print(DIVIDER)
print(f"  Kafka UI   → http://localhost:8080   (see raw-transactions topic)")
print(f"  API docs   → http://localhost:8000/docs")
print(f"  Prometheus → http://localhost:9090")
print(f"  Grafana    → http://localhost:3000   (admin / finsight123)")
print(f"  PDF        → reports/ directory on your machine")
print(DIVIDER)
