"""Unify accounts format: migrate legacy SSO/cookies to accounts array

Revision ID: 013_unify_accounts_format
Revises: 012_add_resolutions
Create Date: 2026-04-03 10:00:00.000000

Handles all migration scenarios:
1. SSO with empty accounts → create from legacy sso_username/password
2. Cookies with empty accounts → create from legacy cookies field
3. SSO with existing accounts that MISS the legacy sso_username → prepend legacy account as default
4. Existing accounts missing role/is_default fields → backfill defaults
5. SSO accounts with stale cookies → clear cookies field
"""
from typing import Sequence, Union

from alembic import op

revision: str = '013_unify_accounts_format'
down_revision: Union[str, None] = '012_add_resolutions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Scenario 1: SSO + accounts empty → create from legacy fields ──
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

    # ── Scenario 2: Cookies + accounts empty → create from legacy cookies ──
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

    # ── Scenario 3: SSO + accounts non-empty + legacy sso_username missing from accounts ──
    # Prepend legacy account as default, clear is_default on existing accounts
    op.execute("""
        UPDATE environments
        SET accounts = (
            -- Build legacy account entry as first element
            jsonb_build_array(jsonb_build_object(
                'name', sso_username,
                'role', 'default',
                'is_default', true,
                'sso_username', sso_username,
                'sso_password', sso_password,
                'sso_env', COALESCE(sso_env, 'prod')
            ))
            -- Append existing accounts with is_default cleared
            || (
                SELECT COALESCE(jsonb_agg(
                    elem || '{"is_default": false}'::jsonb
                ), '[]'::jsonb)
                FROM jsonb_array_elements(accounts) AS elem
            )
        )
        WHERE auth_type = 'sso'
          AND sso_username IS NOT NULL
          AND accounts IS NOT NULL
          AND jsonb_array_length(accounts) > 0
          AND NOT EXISTS (
              SELECT 1
              FROM jsonb_array_elements(accounts) AS el
              WHERE el->>'sso_username' = environments.sso_username
          )
    """)

    # ── Scenario 4: Backfill missing role/is_default on all accounts ──
    # Ensure first account is default if no default exists
    op.execute("""
        UPDATE environments
        SET accounts = (
            SELECT jsonb_agg(
                CASE
                    WHEN idx = 1 AND NOT EXISTS (
                        SELECT 1 FROM jsonb_array_elements(accounts) AS chk
                        WHERE (chk->>'is_default')::boolean = true
                    )
                    THEN elem || '{"is_default": true}'::jsonb
                    ELSE elem
                END
                || CASE WHEN elem->>'role' IS NULL THEN '{"role": null}'::jsonb ELSE '{}'::jsonb END
                || CASE WHEN elem->>'is_default' IS NULL THEN '{"is_default": false}'::jsonb ELSE '{}'::jsonb END
            )
            FROM jsonb_array_elements(accounts) WITH ORDINALITY AS arr(elem, idx)
        )
        WHERE accounts IS NOT NULL
          AND jsonb_array_length(accounts) > 0
          AND auth_type IN ('sso', 'cookies')
    """)

    # ── Scenario 5: Clear stale cookies from SSO accounts ──
    # SSO accounts should not persist cookies; they are generated at runtime
    op.execute("""
        UPDATE environments
        SET accounts = (
            SELECT jsonb_agg(
                CASE
                    WHEN elem->'cookies' IS NOT NULL
                         AND jsonb_array_length(COALESCE(elem->'cookies', '[]'::jsonb)) > 0
                    THEN elem - 'cookies' || '{"cookies": []}'::jsonb
                    ELSE elem
                END
            )
            FROM jsonb_array_elements(accounts) AS elem
        )
        WHERE auth_type = 'sso'
          AND accounts IS NOT NULL
          AND jsonb_array_length(accounts) > 0
    """)


def downgrade() -> None:
    # Restore legacy SSO fields from default account in accounts array
    op.execute("""
        UPDATE environments
        SET sso_username = (
                SELECT el->>'sso_username'
                FROM jsonb_array_elements(accounts) AS el
                WHERE (el->>'is_default')::boolean = true
                LIMIT 1
            ),
            sso_password = (
                SELECT el->>'sso_password'
                FROM jsonb_array_elements(accounts) AS el
                WHERE (el->>'is_default')::boolean = true
                LIMIT 1
            ),
            sso_env = COALESCE(
                (SELECT el->>'sso_env'
                 FROM jsonb_array_elements(accounts) AS el
                 WHERE (el->>'is_default')::boolean = true
                 LIMIT 1),
                'prod'
            ),
            accounts = NULL
        WHERE auth_type = 'sso'
          AND accounts IS NOT NULL
          AND jsonb_array_length(accounts) > 0
    """)

    # Restore legacy cookies field from default account
    op.execute("""
        UPDATE environments
        SET cookies = (
                SELECT el->'cookies'
                FROM jsonb_array_elements(accounts) AS el
                WHERE (el->>'is_default')::boolean = true
                LIMIT 1
            ),
            accounts = NULL
        WHERE auth_type = 'cookies'
          AND accounts IS NOT NULL
          AND jsonb_array_length(accounts) > 0
    """)
