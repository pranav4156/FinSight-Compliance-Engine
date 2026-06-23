"""add llm judge fields to sar_reports

Revision ID: 76bbe8f9ae12
Revises: 39bdd34b60db
Create Date: 2026-06-23 13:25:16.783597

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '76bbe8f9ae12'
down_revision: Union[str, Sequence[str], None] = '39bdd34b60db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sar_reports', sa.Column('judge_score', sa.Float(), nullable=True))
    op.add_column('sar_reports', sa.Column('judge_critique', sa.Text(), nullable=True))
    op.add_column('sar_reports', sa.Column('judge_passed', sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column('sar_reports', 'judge_passed')
    op.drop_column('sar_reports', 'judge_critique')
    op.drop_column('sar_reports', 'judge_score')
