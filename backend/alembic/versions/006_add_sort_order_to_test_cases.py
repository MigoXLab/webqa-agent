"""Add sort_order column to test_cases for explicit ordering.

Revision ID: 006_add_sort_order_to_test_cases
Revises: 005_widen_feishu_notify_user_id
Create Date: 2026-02-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '006_add_sort_order_to_test_cases'
down_revision: Union[str, Sequence[str], None] = '005_widen_feishu_notify_user_id'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add sort_order column with default 0
    op.add_column(
        'test_cases',
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0')
    )

    # Backfill: set sort_order based on created_at order within each business
    # This ensures existing data gets correct ordering
    op.execute("""
        UPDATE test_cases
        SET sort_order = sub.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY business_id ORDER BY created_at ASC
            ) AS rn
            FROM test_cases
        ) AS sub
        WHERE test_cases.id = sub.id
    """)


def downgrade() -> None:
    op.drop_column('test_cases', 'sort_order')
