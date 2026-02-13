"""Add version column to test_cases for user-defined case versioning.

Revision ID: 007_add_version_to_test_cases
Revises: 006_add_sort_order_to_test_cases
Create Date: 2026-02-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '007_add_version_to_test_cases'
down_revision: Union[str, Sequence[str], None] = '006_add_sort_order_to_test_cases'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'test_cases',
        sa.Column('version', sa.String(50), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('test_cases', 'version')
