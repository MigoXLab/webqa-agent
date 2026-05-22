"""Native Tool for mid-run cookie / identity swaps.

Swaps the cookie jar via CDP then navigates to a caller-supplied URL so
the DOM reflects the new session. ``navigate_url`` is required — cookies
alone do not reload the page, and omitting it causes a stale-DOM loop.

CDP errors are classified into three buckets so the LLM knows whether to
retry, abandon, or treat the failure as an infrastructure issue.
"""
from __future__ import annotations

import logging
from typing import Any

from ...core.tool import Tool, ToolResult
from .account_pool import AccountPool
from .cdp_client import CDPCookieClient, CDPCookieError

log = logging.getLogger(__name__)

_CONNECTION_ERROR_MARKERS = (
    'refused', 'closed', 'timed out', 'timeout', 'unreachable',
)
_PROTOCOL_ERROR_MARKERS = (
    'upgrade', 'accept', '/json/version', 'malformed', 'non-object',
    'unsupported ws url',
)


def _classify_cdp_error(exc: CDPCookieError) -> str:
    msg = str(exc).lower()
    if any(m in msg for m in _CONNECTION_ERROR_MARKERS):
        return 'connection'
    if any(m in msg for m in _PROTOCOL_ERROR_MARKERS):
        return 'protocol'
    return 'command'


class SwitchAccountTool(Tool):
    """Replace the browser's cookies with a named account's, then navigate.

    Call ``bind_mcp`` once the MCP server is up. Executing before ``bind_mcp``
    returns a clear infrastructure failure rather than silently no-oping.
    """

    def __init__(self, pool: AccountPool) -> None:
        self._pool = pool
        self._mcp_server: Any | None = None
        self._port: int | None = None

    def bind_mcp(self, mcp_server: Any, port: int) -> None:
        if self._mcp_server is not None:
            log.warning(
                'bind_mcp called twice on %s; ignoring second bind', self.name)
            return
        self._mcp_server = mcp_server
        self._port = port

    # --------------------------- Tool ABC --------------------------------

    @property
    def name(self) -> str:
        return 'switch_account'

    @property
    def description(self) -> str:
        return (
            'Switch the active browser identity by replacing cookies with a '
            "named account's, then navigating to `navigate_url` so the current "
            'page reflects the new session. Use for mid-run role changes. '
            'WARNING: cookies alone do NOT reload the DOM — `navigate_url` is '
            'required; pass the current page URL if you only want a reload.'
        )

    @property
    def input_schema(self) -> dict:
        return {
            'type': 'object',
            'properties': {
                'account': {
                    'type': 'string',
                    'description':
                        'Account name from the "Available roles" list.',
                },
                'navigate_url': {
                    'type': 'string',
                    'description':
                        'URL to land on after the swap. Required — cookies '
                        'alone do not reload the DOM; pass the current page '
                        'URL for an in-place reload.',
                },
            },
            'required': ['account', 'navigate_url'],
        }

    def is_read_only(self) -> bool:
        return False

    def get_activity_description(self, **kwargs) -> str | None:
        return f'Switching account to: {kwargs.get("account", "?")}'

    # --------------------------- execute --------------------------------

    def execute(self, **kwargs) -> ToolResult:
        account = (kwargs.get('account') or '').strip()
        navigate_url = (kwargs.get('navigate_url') or '').strip()
        if not account:
            return ToolResult(
                content='[FAILURE: missing account argument]', is_error=True)
        if not navigate_url:
            return ToolResult(
                content='[FAILURE: missing navigate_url argument]',
                is_error=True)

        cookies = self._pool.resolve_cookies(account)
        if cookies is None:
            avail = ', '.join(self._pool.account_names) or '(none)'
            return ToolResult(
                content=(
                    f'[FAILURE: unknown account {account!r}; '
                    f'available: {avail}]'),
                is_error=True)

        if self._mcp_server is None or self._port is None:
            return ToolResult(
                content=(
                    '[FAILURE: switch_account not bound to MCP server — '
                    'infrastructure error, do NOT retry; report test as blocked]'),
                is_error=True)

        try:
            client = CDPCookieClient(self._port)
            client.connect()
            try:
                client.clear_and_set(cookies)
            finally:
                client.close()
        except CDPCookieError as exc:
            kind = _classify_cdp_error(exc)
            if kind == 'connection':
                content = (
                    f'[FAILURE: CDP unreachable ({exc}) — browser may have '
                    f'crashed. Try navigate_page to a known URL first, then '
                    f'retry switch_account.]')
            elif kind == 'protocol':
                content = (
                    f'[FAILURE: CDP protocol error ({exc}) — infrastructure '
                    f'issue, do NOT retry this tool; report test as blocked.]')
            else:
                content = f'[FAILURE: CDP command rejected: {exc}]'
            return ToolResult(content=content, is_error=True)

        res = self._mcp_server.call_tool(
            'navigate_page', {'url': navigate_url})
        if getattr(res, 'is_error', False):
            return ToolResult(
                content=(
                    f"[FAILURE: cookies ARE now {account!r}'s but navigation "
                    f'to {navigate_url!r} failed: {res.content}. DO NOT call '
                    f'switch_account again — identity is already switched. '
                    f'Call navigate_page with a working URL instead.]'),
                is_error=True)

        return ToolResult(
            content=f'[SUCCESS] Switched to account {account!r}.',
            is_error=False)
