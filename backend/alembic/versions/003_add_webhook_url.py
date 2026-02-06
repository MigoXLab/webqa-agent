"""Add webhook_url to scheduled_tasks table.

Revision ID: 003_add_webhook_url
Revises: 002_add_scheduled_tasks
Create Date: 2026-02-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '003_add_webhook_url'
down_revision: Union[str, None] = '002_add_scheduled_tasks'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('scheduled_tasks', sa.Column('webhook_url', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('scheduled_tasks', 'webhook_url')
