"""add_sar_narrative_embedding

Revision ID: 39bdd34b60db
Revises: 190b0161cf65
Create Date: 2026-06-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "39bdd34b60db"
down_revision: Union[str, None] = "190b0161cf65"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sar_reports",
        sa.Column("narrative_embedding", Vector(1536), nullable=True),
    )
    # HNSW index — fast approximate nearest-neighbour search for similar case retrieval
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sar_reports_embedding "
        "ON sar_reports USING hnsw (narrative_embedding vector_l2_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sar_reports_embedding")
    op.drop_column("sar_reports", "narrative_embedding")
