from prometheus_client import Counter, Gauge, Histogram

# ── Transaction pipeline ──────────────────────────────────────────────────────

transactions_ingested = Counter(
    "finsight_transactions_ingested_total",
    "Total transactions successfully written to the database",
    ["channel", "currency"],
)

transactions_flagged = Counter(
    "finsight_transactions_flagged_total",
    "Total transactions flagged as suspicious after anomaly scoring",
)

# ── Anomaly scoring ───────────────────────────────────────────────────────────

anomaly_scores = Histogram(
    "finsight_anomaly_score",
    "Distribution of final anomaly scores (0.0 = normal, 1.0 = suspicious)",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

# ── Alerts ────────────────────────────────────────────────────────────────────

alerts_created = Counter(
    "finsight_alerts_created_total",
    "Total alerts created, broken down by severity",
    ["severity"],
)

# ── SAR generation ────────────────────────────────────────────────────────────

sar_generation_latency = Histogram(
    "finsight_sar_generation_seconds",
    "End-to-end latency of SAR narrative generation (LLM call + PDF render)",
    buckets=[1, 2, 5, 10, 20, 30, 60, 120],
)

sar_generated_total = Counter(
    "finsight_sar_generated_total",
    "Total SAR reports generated",
    ["model"],
)

# ── Dead letter queue ─────────────────────────────────────────────────────────

dlq_messages = Counter(
    "finsight_dlq_messages_total",
    "Total messages sent to the dead letter queue",
    ["reason_type"],
)

# ── Sanctions screening ───────────────────────────────────────────────────────

sanctions_hits = Counter(
    "finsight_sanctions_hits_total",
    "Total transactions blocked by sanctions screening",
)

sanctions_partial = Counter(
    "finsight_sanctions_partial_total",
    "Total transactions with a partial (MEDIUM risk) sanctions match",
)
