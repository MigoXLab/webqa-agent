"""add resolutions to execution and scheduled_task

Revision ID: 012_add_resolutions
Revises: 011_add_account_to_test_cases
Create Date: 2026-04-01 11:25:45.179527

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '012_add_resolutions'
down_revision: Union[str, None] = '011_add_account_to_test_cases'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('executions', sa.Column('resolutions', sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('scheduled_tasks', sa.Column('resolutions', sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('scheduled_tasks', 'resolutions')
    op.drop_column('executions', 'resolutions')
