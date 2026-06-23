import logging
from datetime import datetime, timedelta

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Transaction

logger = logging.getLogger(__name__)

# Only consider transactions within this window for cycle detection.
# Widened from 2h to 7 days after validating against the IBM AML benchmark
# dataset — real multi-account laundering chains (fan-out/cycle patterns)
# unfold over hours to days, not seconds; a 2h window could only ever catch
# the fastest-moving schemes.
CYCLE_WINDOW_HOURS = 24 * 7

# Hard cap on rows considered — bounds worst-case cost as tenant volume grows
MAX_EDGES = 5000


def check_graph_cycle(txn: Transaction, session: Session) -> float:
    """
    Detect round-trip money cycling using directed graph cycle detection.

    Every transaction is an edge in a directed graph: sender → receiver.
    If adding the current transaction creates a cycle (A→B→C→A), it means
    money is flowing in a loop — a classic money laundering pattern.

    Example:
        Account A sends ₹5L to B  (leg 1)
        Account B sends ₹5L to C  (leg 2)
        Account C sends ₹5L to A  (leg 3) ← this transaction closes the cycle

    Algorithm: a directed cycle exists through this transaction's edge
    (sender → receiver) if and only if a path already exists from receiver
    back to sender. We check that directly with a single BFS (nx.has_path,
    O(V+E)) instead of enumerating every simple cycle in the graph
    (nx.simple_cycles, which is exponential in the worst case and becomes
    the dominant cost as transaction volume grows — this was the throughput
    bottleneck found during benchmarking).

    Library: NetworkX — industry-standard Python graph library.

    Edge case covered: #13 (round-tripping / money cycling)

    Window is anchored to the transaction's own created_at, not wall-clock
    now() — see velocity_check.py for why this matters for batch scoring.
    """
    reference_time = txn.created_at or datetime.utcnow()
    window_start = reference_time - timedelta(hours=CYCLE_WINDOW_HOURS)

    recent = session.execute(
        select(Transaction.sender_account, Transaction.receiver_account).where(
            Transaction.tenant_id == txn.tenant_id,
            Transaction.created_at >= window_start,
            Transaction.created_at <= reference_time,  # causality — no peeking at "future" rows
            Transaction.id != txn.id,
        ).limit(MAX_EDGES)
    ).all()

    G = nx.DiGraph()
    for row in recent:
        G.add_edge(row.sender_account, row.receiver_account)

    try:
        has_both_nodes = G.has_node(txn.receiver_account) and G.has_node(txn.sender_account)
        if has_both_nodes and nx.has_path(G, txn.receiver_account, txn.sender_account):
            logger.warning(
                f"Cycle detected: {txn.sender_account} → {txn.receiver_account} closes a loop back to sender"
            )
            return 1.0
    except Exception as e:
        logger.error(f"Graph cycle detection error: {e}")

    return 0.0
