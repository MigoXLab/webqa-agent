"""Add account column to test_cases table.

Revision ID: 011_add_account_to_test_cases
Revises: 010_add_accounts_to_environments
Create Date: 2026-03-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '011_add_account_to_test_cases'
down_revision: Union[str, Sequence[str], None] = '010_add_accounts_to_environments'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('test_cases', sa.Column('account', sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column('test_cases', 'account')
