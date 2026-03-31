"""Add accounts JSONB column to environments table.

Revision ID: 010_add_accounts_to_environments
Revises: 009_make_business_id_nullable
Create Date: 2026-03-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = '010_add_accounts_to_environments'
down_revision: Union[str, Sequence[str], None] = '009_make_business_id_nullable'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('environments', sa.Column('accounts', JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column('environments', 'accounts')