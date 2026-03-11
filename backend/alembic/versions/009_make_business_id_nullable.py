"""Make business_id nullable in executions table.

Revision ID: 009_make_business_id_nullable
Revises: 008_add_config_to_executions
Create Date: 2026-03-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = '009_make_business_id_nullable'
down_revision: Union[str, Sequence[str], None] = '008_add_config_to_executions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'executions',
        'business_id',
        existing_type=UUID(as_uuid=True),
        nullable=True
    )


def downgrade() -> None:
    op.alter_column(
        'executions',
        'business_id',
        existing_type=UUID(as_uuid=True),
        nullable=False
    )
