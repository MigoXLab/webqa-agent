"""Add config column to executions for dynamic configuration.

Revision ID: 008_add_config_to_executions
Revises: 007_add_version_to_test_cases
Create Date: 2026-03-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = '008_add_config_to_executions'
down_revision: Union[str, Sequence[str], None] = '007_add_version_to_test_cases'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'executions',
        sa.Column('config', JSONB, nullable=True)
    )


def downgrade() -> None:
    op.drop_column('executions', 'config')
