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
