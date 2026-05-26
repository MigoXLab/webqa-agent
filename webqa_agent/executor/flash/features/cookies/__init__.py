"""Cookie injection and multi-account switching for webqa-cc-mini.

Usage::

    ext = build_cookie_extensions(
        accounts=[
            AccountSpec(name='admin', cookies=admin_cookies, default=True,
                        role='Full administrator'),
            AccountSpec(name='viewer', cookies=viewer_cookies,
                        role='Read-only user'),
        ],
    )
    result = run_cc_mini(url, task, worker_id=0, **ext.as_kwargs())

Security notes:
  * Cookie values are plain dicts in memory — treat as live credentials,
    never commit cookie files to the repo.
  * CDP has NO authentication — keep ``--remote-debugging-address=127.0.0.1``.
  * ``AccountSpec.role`` and account names are sent to the LLM in the system
    prompt — avoid PII or confidential identifiers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from .account_pool import AccountPool, AccountSpec
from .cdp_client import CDPCookieClient, CDPCookieError
from .switch_account_tool import SwitchAccountTool

_log = logging.getLogger(__name__)


def _validate_cookie_shape(cookie: dict, *, context: str) -> list[str]:
    """Return error messages for a single cookie dict; empty = valid.

    Either ``domain`` or ``url`` must be present — without one CDP rejects
    with ``-32602`` and the test silently runs logged-out.
    """
    errors: list[str] = []
    if not isinstance(cookie, dict):
        return [f'{context}: expected dict, got {type(cookie).__name__}']
    if not cookie.get('name'):
        errors.append(f'{context}: missing or empty "name"')
    if 'value' not in cookie:
        errors.append(f'{context}: missing "value" key (empty string is OK)')
    has_domain = bool(cookie.get('domain'))
    has_url = isinstance(cookie.get('url'), str) and (
        cookie['url'].startswith('http://')
        or cookie['url'].startswith('https://')
    )
    if not has_domain and not has_url:
        errors.append(
            f'{context}: each cookie must have "domain" or "url" '
            '(CDP rejects unscoped cookies; the agent would silently run '
            'logged-out).'
        )
    return errors


def validate_cookie_list(cookies: list[dict], *, context: str) -> list[str]:
    errors: list[str] = []
    for i, c in enumerate(cookies):
        errors.extend(
            _validate_cookie_shape(c, context=f'{context}[{i}]'))
    return errors


@dataclass
class Extensions:
    """Bundle of run_cc_mini extension-point arguments.

    Merge multiple bundles with ``+`` before spreading into ``run_cc_mini``
    so independent features compose without overwriting each other.
    """

    pre_engine_hook: Callable[[Any, int], None] | None = None
    extra_tools: list = field(default_factory=list)
    extra_section: str | None = None

    def __add__(self, other: 'Extensions') -> 'Extensions':
        if not isinstance(other, Extensions):
            raise TypeError(
                f'cannot merge Extensions with {type(other).__name__}')
        if self.pre_engine_hook and other.pre_engine_hook:
            raise ValueError(
                'cannot merge Extensions with conflicting pre_engine_hook')
        sections = [s for s in (self.extra_section, other.extra_section) if s]
        return Extensions(
            pre_engine_hook=self.pre_engine_hook or other.pre_engine_hook,
            extra_tools=list(self.extra_tools) + list(other.extra_tools),
            extra_section='\n\n'.join(sections) if sections else None,
        )

    def as_kwargs(self) -> dict:
        """Keys match ``run_cc_mini`` parameter names — sync with runner.py on
        rename."""
        return {
            'pre_engine_hook': self.pre_engine_hook,
            'extra_tools': self.extra_tools or None,
            'extra_section': self.extra_section,
        }


def build_cookie_extensions(
    *,
    cookies: list[dict] | None = None,
    accounts: list[AccountSpec] | None = None,
) -> Extensions:
    """Assemble Extensions for cookie injection and multi-account switching.

    Raises ``ValueError`` when any cookie violates the CDP ``CookieParam``
    contract — failing fast is preferred to a silent logged-out run.
    """
    errors: list[str] = []
    if cookies:
        errors.extend(validate_cookie_list(cookies, context='cookies'))
    if accounts:
        for i, a in enumerate(accounts):
            errors.extend(validate_cookie_list(
                a.cookies, context=f'accounts[{a.name!r}].cookies'))
    if errors:
        joined = '\n  - '.join([''] + errors)
        raise ValueError(
            f'build_cookie_extensions: invalid cookie configuration:{joined}')

    pool = AccountPool(
        accounts=accounts or [], fallback_cookies=cookies or [])
    ext = Extensions()

    default_cookies = pool.resolve_cookies(None)
    if default_cookies:
        def hook(mcp: Any, cdp_port: int) -> None:
            client = CDPCookieClient(cdp_port)
            client.connect()
            try:
                client.set_cookies(default_cookies)
            finally:
                client.close()

        ext.pre_engine_hook = hook

    if pool.has_accounts:
        ext.extra_tools.append(SwitchAccountTool(pool))
        default_label = pool.default_name or '(the fallback identity)'
        ext.extra_section = (
            '## Available roles\n\n'
            f'You start this run logged in as **{default_label}**. '
            'Call `switch_account(account=..., navigate_url=...)` to change '
            'identity mid-run.\n\n'
            + pool.get_role_summary()
            + '\n\n'
            'Note: `switch_account` is a mutating action — follow '
            'Observe → switch_account(..., navigate_url=...) → Observe. '
            'Do NOT batch it with read-only tools.'
        )

    return ext


__all__ = [
    'AccountSpec',
    'AccountPool',
    'Extensions',
    'build_cookie_extensions',
    'validate_cookie_list',
    'SwitchAccountTool',
    # CDPCookieClient / CDPCookieError are low-level transport; not public API.
]
