"""Widen feishu_notify_user_id column to support multiple open_ids.

Revision ID: 005_widen_feishu_notify_user_id
Revises: 004_add_feishu_notify_user_id
Create Date: 2026-02-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '005_widen_feishu_notify_user_id'
down_revision: Union[str, Sequence[str], None] = '004_add_feishu_notify_user_id'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'scheduled_tasks',
        'feishu_notify_user_id',
        type_=sa.String(500),
        existing_type=sa.String(100),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        'scheduled_tasks',
        'feishu_notify_user_id',
        type_=sa.String(100),
        existing_type=sa.String(500),
        existing_nullable=True,
    )
