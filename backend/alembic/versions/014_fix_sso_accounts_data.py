"""Fix SSO/cookies accounts data: idempotent backfill for records missed by 013

Revision ID: 014_fix_sso_accounts_data
Revises: 013_unify_accounts_format
Create Date: 2026-04-02 12:00:00.000000

Migration 013 ran the same SQL but only affected data present at that time.
Any rows that existed before the multi-account feature but were not captured
by 013 (e.g. data created on a different DB, or restored from backup) are
backfilled here with the same idempotent WHERE condition.
"""
from typing import Sequence, Union

from alembic import op

revision: str = '014_fix_sso_accounts_data'
down_revision: Union[str, None] = '013_unify_accounts_format'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfill SSO: legacy sso_username/password → accounts[0] as default
    op.execute("""
        UPDATE environments
        SET accounts = jsonb_build_array(jsonb_build_object(
            'name', sso_username,
            'role', 'default',
            'is_default', true,
            'sso_username', sso_username,
            'sso_password', sso_password,
            'sso_env', COALESCE(sso_env, 'prod')
        ))
        WHERE auth_type = 'sso'
          AND sso_username IS NOT NULL
          AND (accounts IS NULL OR jsonb_array_length(accounts) = 0)
    """)

    # Backfill cookies: legacy cookies field → accounts[0] as default
    op.execute("""
        UPDATE environments
        SET accounts = jsonb_build_array(jsonb_build_object(
            'name', 'default',
            'role', 'default',
            'is_default', true,
            'cookies', cookies
        ))
        WHERE auth_type = 'cookies'
          AND cookies IS NOT NULL
          AND (accounts IS NULL OR jsonb_array_length(accounts) = 0)
    """)


def downgrade() -> None:
    # Intentionally a no-op: passwords are stored in accounts and cannot be
    # safely restored to the legacy sso_password column after this migration.
    pass