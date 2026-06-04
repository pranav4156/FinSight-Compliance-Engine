import logging
from datetime import datetime, timedelta

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Transaction

logger = logging.getLogger(__name__)

# Only consider transactions within this window for cycle detection
CYCLE_WINDOW_HOURS = 2


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

    Algorithm: build graph of recent transactions, add current transaction
    as an edge, then check if any directed cycles exist involving both
    the sender and receiver of the current transaction.

    Library: NetworkX — industry-standard Python graph library.

    Edge case covered: #13 (round-tripping / money cycling)
    """
    window_start = datetime.utcnow() - timedelta(hours=CYCLE_WINDOW_HOURS)

    recent = session.execute(
        select(Transaction.sender_account, Transaction.receiver_account).where(
            Transaction.tenant_id == txn.tenant_id,
            Transaction.created_at >= window_start,
            Transaction.id != txn.id,
        )
    ).all()

    G = nx.DiGraph()
    for row in recent:
        G.add_edge(row.sender_account, row.receiver_account)

    # Add the current transaction edge
    G.add_edge(txn.sender_account, txn.receiver_account)

    try:
        for cycle in nx.simple_cycles(G):
            if txn.sender_account in cycle and txn.receiver_account in cycle:
                logger.warning(
                    f"Cycle detected involving {txn.sender_account} → {txn.receiver_account}: {cycle}"
                )
                return 1.0
    except Exception as e:
        logger.error(f"Graph cycle detection error: {e}")

    return 0.0
