"""Tests for ``features.cookies.switch_account_tool``."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from webqa_agent.executor.flash.core.tool import ToolResult
from webqa_agent.executor.flash.features.cookies import \
    switch_account_tool as sat_module
from webqa_agent.executor.flash.features.cookies.account_pool import (
    AccountPool, AccountSpec)
from webqa_agent.executor.flash.features.cookies.cdp_client import \
    CDPCookieError
from webqa_agent.executor.flash.features.cookies.switch_account_tool import (
    SwitchAccountTool, _classify_cdp_error)

ADMIN = [{'name': 'session', 'value': 'admin-tok'}]
VIEWER = [{'name': 'session', 'value': 'viewer-tok'}]


def _make_tool() -> tuple[SwitchAccountTool, AccountPool]:
    pool = AccountPool(accounts=[
        AccountSpec(name='admin', cookies=ADMIN, default=True),
        AccountSpec(name='viewer', cookies=VIEWER),
    ])
    return SwitchAccountTool(pool), pool


# ---------------------------------------------------------------------------
# schema / metadata
# ---------------------------------------------------------------------------


def test_schema_requires_both_account_and_navigate_url():
    tool, _ = _make_tool()
    schema = tool.input_schema
    assert schema['required'] == ['account', 'navigate_url']
    assert 'account' in schema['properties']
    assert 'navigate_url' in schema['properties']


def test_is_not_read_only():
    tool, _ = _make_tool()
    assert tool.is_read_only() is False


def test_name_and_activity_description():
    tool, _ = _make_tool()
    assert tool.name == 'switch_account'
    assert 'admin' in tool.get_activity_description(account='admin')


def test_description_warns_about_navigate_url():
    tool, _ = _make_tool()
    desc = tool.description.lower()
    assert 'navigate_url' in desc
    assert 'required' in desc or 'not reload' in desc


# ---------------------------------------------------------------------------
# argument validation
# ---------------------------------------------------------------------------


def test_missing_account_returns_failure():
    tool, _ = _make_tool()
    tool.bind_mcp(MagicMock(), 9222)
    r = tool.execute(account='', navigate_url='https://x')
    assert r.is_error
    assert 'missing account' in r.content


def test_missing_navigate_url_returns_failure():
    tool, _ = _make_tool()
    tool.bind_mcp(MagicMock(), 9222)
    r = tool.execute(account='admin', navigate_url='')
    assert r.is_error
    assert 'missing navigate_url' in r.content


def test_unknown_account_lists_available():
    tool, _ = _make_tool()
    tool.bind_mcp(MagicMock(), 9222)
    r = tool.execute(account='superuser', navigate_url='https://x')
    assert r.is_error
    assert 'unknown account' in r.content
    assert 'admin' in r.content and 'viewer' in r.content


# ---------------------------------------------------------------------------
# bind_mcp
# ---------------------------------------------------------------------------


def test_execute_before_bind_returns_infrastructure_failure():
    tool, _ = _make_tool()
    r = tool.execute(account='admin', navigate_url='https://x')
    assert r.is_error
    assert 'not bound' in r.content
    assert 'do NOT retry' in r.content


def test_bind_mcp_idempotent_second_call_warns(caplog):
    tool, _ = _make_tool()
    s1 = MagicMock()
    s2 = MagicMock()
    tool.bind_mcp(s1, 9222)
    with caplog.at_level('WARNING'):
        tool.bind_mcp(s2, 9223)
    assert any('bind_mcp called twice' in r.message for r in caplog.records)
    # First binding preserved
    assert tool._mcp_server is s1
    assert tool._port == 9222


# ---------------------------------------------------------------------------
# success path
# ---------------------------------------------------------------------------


def test_happy_path_success(monkeypatch):
    tool, _ = _make_tool()
    mcp = MagicMock()
    mcp.call_tool.return_value = ToolResult(content='ok', is_error=False)
    tool.bind_mcp(mcp, 9222)

    fake_client = MagicMock()
    monkeypatch.setattr(sat_module, 'CDPCookieClient',
                        MagicMock(return_value=fake_client))

    r = tool.execute(account='admin', navigate_url='https://example.com/dash')
    assert not r.is_error
    assert "Switched to account 'admin'" in r.content

    # CDP sequence: clear_and_set with admin's cookies
    fake_client.connect.assert_called_once()
    fake_client.clear_and_set.assert_called_once_with(ADMIN)
    fake_client.close.assert_called_once()
    # MCP navigation after
    mcp.call_tool.assert_called_once_with(
        'navigate_page', {'url': 'https://example.com/dash'})


# ---------------------------------------------------------------------------
# CDP failure classification
# ---------------------------------------------------------------------------


def test_connection_error_hints_retry_after_navigate(monkeypatch):
    tool, _ = _make_tool()
    tool.bind_mcp(MagicMock(), 9222)

    def raise_connect():
        raise CDPCookieError('Connection refused on /json/version')

    fake_client = MagicMock()
    fake_client.connect.side_effect = raise_connect
    monkeypatch.setattr(sat_module, 'CDPCookieClient',
                        MagicMock(return_value=fake_client))

    r = tool.execute(account='admin', navigate_url='https://x')
    assert r.is_error
    assert 'CDP unreachable' in r.content
    assert 'retry switch_account' in r.content or 'navigate_page' in r.content


def test_protocol_error_says_do_not_retry(monkeypatch):
    tool, _ = _make_tool()
    tool.bind_mcp(MagicMock(), 9222)
    fake_client = MagicMock()
    fake_client.connect.side_effect = CDPCookieError(
        'Sec-WebSocket-Accept mismatch')
    monkeypatch.setattr(sat_module, 'CDPCookieClient',
                        MagicMock(return_value=fake_client))

    r = tool.execute(account='admin', navigate_url='https://x')
    assert r.is_error
    assert 'protocol error' in r.content
    assert 'do NOT retry' in r.content


def test_command_error_verbatim(monkeypatch):
    tool, _ = _make_tool()
    tool.bind_mcp(MagicMock(), 9222)
    fake_client = MagicMock()
    fake_client.clear_and_set.side_effect = CDPCookieError(
        'CDP command rejected (code=-32602)')
    monkeypatch.setattr(sat_module, 'CDPCookieClient',
                        MagicMock(return_value=fake_client))

    r = tool.execute(account='admin', navigate_url='https://x')
    assert r.is_error
    assert 'CDP command rejected' in r.content


# ---------------------------------------------------------------------------
# navigate failure → stranded-cookies recovery hint
# ---------------------------------------------------------------------------


def test_navigate_failure_instructs_recovery(monkeypatch):
    tool, _ = _make_tool()
    mcp = MagicMock()
    mcp.call_tool.return_value = ToolResult(
        content='404 not found', is_error=True)
    tool.bind_mcp(mcp, 9222)

    fake_client = MagicMock()
    monkeypatch.setattr(sat_module, 'CDPCookieClient',
                        MagicMock(return_value=fake_client))

    r = tool.execute(account='viewer', navigate_url='https://bad/path')
    assert r.is_error
    assert 'cookies ARE now' in r.content
    assert 'viewer' in r.content
    assert 'do NOT call switch_account again' in r.content.lower() \
        or 'DO NOT call switch_account again' in r.content


# ---------------------------------------------------------------------------
# _classify_cdp_error unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('msg,kind', [
    ('Connection refused', 'connection'),
    ('server closed connection mid-call', 'connection'),
    ('WS handshake timed out', 'connection'),
    ('WS upgrade failed: xxx', 'protocol'),
    ('Sec-WebSocket-Accept mismatch', 'protocol'),
    ('/json/version returned HTTP 500', 'protocol'),
    ('malformed JSON from CDP', 'protocol'),
    ('CDP command rejected (code=-32602)', 'command'),
])
def test_classify_cdp_error(msg, kind):
    assert _classify_cdp_error(CDPCookieError(msg)) == kind
