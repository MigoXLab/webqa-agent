"""Add feishu_notify_user_id to scheduled_tasks.

Revision ID: 004_add_feishu_notify_user_id
Revises: 003_add_webhook_url
Create Date: 2026-02-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '004_add_feishu_notify_user_id'
down_revision: Union[str, Sequence[str], None] = '003_add_webhook_url'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('scheduled_tasks', sa.Column('feishu_notify_user_id', sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column('scheduled_tasks', 'feishu_notify_user_id')
