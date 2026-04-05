# FinSight-Compliance-Engine
Real-time fintech compliance system: Kafka event streaming, PyFlink anomaly detection, LangChain + GPT-4o SAR generation, PostgreSQL + pgvector, Redis, FastAPI, JWT/RBAC, Prometheus/Grafana, Terraform IaC. Built for Razorpay/Zerodha-scale workloads.

## Why This Exists

Every fintech in India — Razorpay, Zerodha, Groww, CRED — and every GCC operating here (JP Morgan, Goldman, Citi) faces the same operational crisis: **RBI mandates real-time transaction monitoring, immutable audit trails, SAR filing within 7 days, and continuous KYC compliance.**

Their current stack fails them in three ways:

| Problem | Current Reality | Cost |
|---|---|---|
| Rule-based fraud engines | 200+ false positives per day | Analyst burnout, missed real threats |
| Manual compliance review | 4–6 hours per case | SAR filing SLA breaches, regulatory risk |
| PDF reports | Unstructured, non-auditable | SEBI/RBI investigation exposure |

**There is no open-source, production-grade system that solves all three layers together.**

This project does.

---

## 📜 A Real Case: Why This Matters

> *This is the scenario this platform was designed to solve.*

**Arjun Mehta** — 31 years old, salaried software engineer in Pune, Zerodha account active for 2 years. Declared income: ₹14 LPA. Average monthly trading volume: ₹3–4 lakhs.

**Day 1, 9:07 AM** — Arjun buys ₹48 lakh worth of ALPHAGEARS (a micro-cap) in a single order. That is 12x his average volume and 23% of the stock's entire daily traded volume. ALPHAGEARS had announced a board meeting for a potential acquisition the previous evening.

**Day 1, 2:15 PM** — He sells the entire position for ₹61 lakhs. ₹13 lakh profit in 5 hours.

**Day 2, 10:30 AM** — ₹55 lakhs withdrawn to savings account.

**Day 3** — The exact same pattern repeats.

### What the old stack does

A rule fires: "volume exceeds 10x average." Correct — but so do 200 other rules that day. A compliance analyst opens the case on Day 4, manually reads PDF statements, cross-references KYC income, writes a Word doc summary, and decides. This takes 4–6 hours. With 200 such alerts pending, they are already past the 7-day FIU-IND filing window.

### What this platform does

**In under 60 seconds of the trade executing**, the system:

1. **Ingests** the `trade.executed` event via Kafka
2. **Flags** simultaneously: volume anomaly, income-to-trade ratio breach (48L vs 14 LPA income), micro-cap concentration, and a corporate action correlation (board meeting announcement the prior evening)
3. **Generates this narrative automatically:**
4. **Routes** the case to the senior analyst queue, scored 94/100
5. **Auto-drafts** the SAR in FIU-IND compliant format

The analyst reviews, verifies, approves — in **15 minutes**, not 6 hours. SAR filed well within the 7-day window. Full reasoning chain logged immutably for audit.

---

