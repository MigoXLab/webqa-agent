"""Unify accounts format: migrate legacy SSO/cookies to accounts array

Revision ID: 013_unify_accounts_format
Revises: 012_add_resolutions
Create Date: 2026-04-01 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '013_unify_accounts_format'
down_revision: Union[str, None] = '012_add_resolutions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Migrate legacy SSO single-account to accounts array
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
          AND (accounts IS NULL OR accounts = '[]'::jsonb)
    """)

    # 2. Migrate legacy cookies single-account to accounts array
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
          AND (accounts IS NULL OR accounts = '[]'::jsonb)
    """)

    # 3. Upgrade existing accounts: add role/is_default if missing
    #    Set first element as is_default=true if no default exists
    op.execute("""
        UPDATE environments
        SET accounts = (
            SELECT jsonb_agg(
                CASE
                    WHEN idx = 0 AND NOT EXISTS (
                        SELECT 1 FROM jsonb_array_elements(accounts) AS el
                        WHERE (el->>'is_default')::boolean = true
                    )
                    THEN elem || '{"is_default": true}'::jsonb
                    ELSE elem
                END
                || CASE WHEN elem->>'role' IS NULL THEN '{"role": null}'::jsonb ELSE '{}'::jsonb END
                || CASE WHEN elem->>'is_default' IS NULL THEN '{"is_default": false}'::jsonb ELSE '{}'::jsonb END
            )
            FROM jsonb_array_elements(accounts) WITH ORDINALITY AS arr(elem, idx)
            WHERE idx = idx  -- always true, keeps the row
        )
        WHERE accounts IS NOT NULL
          AND jsonb_array_length(accounts) > 0
          AND auth_type IN ('sso', 'cookies')
    """)


def downgrade() -> None:
    # Restore legacy SSO fields from accounts[0]
    op.execute("""
        UPDATE environments
        SET sso_username = accounts->0->>'sso_username',
            sso_password = accounts->0->>'sso_password',
            sso_env = COALESCE(accounts->0->>'sso_env', 'prod'),
            accounts = NULL
        WHERE auth_type = 'sso'
          AND accounts IS NOT NULL
          AND jsonb_array_length(accounts) > 0
    """)

    # Restore legacy cookies field from accounts[0]
    op.execute("""
        UPDATE environments
        SET cookies = (accounts->0->'cookies'),
            accounts = NULL
        WHERE auth_type = 'cookies'
          AND accounts IS NOT NULL
          AND jsonb_array_length(accounts) > 0
    """)
