"""add composite indexes for anomaly-detection query patterns

Revision ID: a1b2c3d4e5f6
Revises: 76bbe8f9ae12
Create Date: 2026-06-23 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '76bbe8f9ae12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_transactions_sender_tenant_created', 'transactions',
        ['sender_account', 'tenant_id', 'created_at'], unique=False, if_not_exists=True,
    )
    op.create_index(
        'ix_transactions_tenant_created', 'transactions',
        ['tenant_id', 'created_at'], unique=False, if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index('ix_transactions_tenant_created', table_name='transactions')
    op.drop_index('ix_transactions_sender_tenant_created', table_name='transactions')
