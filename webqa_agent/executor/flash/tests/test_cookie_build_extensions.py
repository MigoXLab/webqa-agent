"""Tests for ``features.cookies.build_cookie_extensions`` + ``Extensions``."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from webqa_agent.executor.flash.features.cookies import (
    AccountSpec, Extensions, SwitchAccountTool, build_cookie_extensions,
    validate_cookie_list)

# ---------------------------------------------------------------------------
# validate_cookie_list
# ---------------------------------------------------------------------------


def test_validate_empty_list_ok():
    assert validate_cookie_list([], context='x') == []


def test_validate_valid_cookie_ok():
    assert validate_cookie_list(
        [{'name': 'a', 'value': 'b', 'domain': '.x'}], context='x') == []


def test_validate_url_alone_ok():
    """Url alone is acceptable per CDP CookieParam."""
    assert validate_cookie_list(
        [{'name': 'a', 'value': 'b', 'url': 'https://x.com/'}],
        context='x') == []


def test_validate_missing_name():
    errors = validate_cookie_list(
        [{'value': 'b', 'domain': '.x'}], context='c')
    assert any('missing or empty "name"' in e for e in errors)


def test_validate_empty_name():
    errors = validate_cookie_list(
        [{'name': '', 'value': 'b', 'domain': '.x'}], context='c')
    assert any('missing or empty "name"' in e for e in errors)


def test_validate_missing_value_key():
    """Missing 'value' key is an error (empty string value is OK)."""
    errors = validate_cookie_list(
        [{'name': 'a', 'domain': '.x'}], context='c')
    assert any('missing "value"' in e for e in errors)


def test_validate_empty_value_ok():
    """Empty string value is accepted — some servers use it as a deletion
    sentinel."""
    assert validate_cookie_list(
        [{'name': 'a', 'value': '', 'domain': '.x'}], context='x') == []


def test_validate_missing_domain_and_url():
    errors = validate_cookie_list(
        [{'name': 'a', 'value': 'b'}], context='c')
    assert any('domain' in e and 'url' in e for e in errors)


def test_validate_non_http_url_not_accepted():
    """A non-http(s) url does not satisfy the url-or-domain requirement."""
    errors = validate_cookie_list(
        [{'name': 'a', 'value': 'b', 'url': 'ftp://x'}], context='c')
    assert any('domain' in e and 'url' in e for e in errors)


def test_validate_non_dict_entry():
    errors = validate_cookie_list(
        ['not-a-dict'], context='c')  # type: ignore[list-item]
    assert any('expected dict' in e for e in errors)


def test_validate_context_is_indexed():
    errors = validate_cookie_list(
        [{'name': 'ok', 'value': 'v', 'domain': '.x'},
         {'name': 'bad'}],   # missing value + domain
        context='accounts[admin].cookies')
    # The bad index should appear in the message
    assert any('accounts[admin].cookies[1]' in e for e in errors)
    assert not any('accounts[admin].cookies[0]' in e for e in errors)


# ---------------------------------------------------------------------------
# build_cookie_extensions validation
# ---------------------------------------------------------------------------


def test_build_rejects_cookie_without_domain_or_url():
    with pytest.raises(ValueError, match='invalid cookie configuration'):
        build_cookie_extensions(
            cookies=[{'name': 'a', 'value': 'b'}])


def test_build_rejects_account_cookie_without_domain_or_url():
    with pytest.raises(ValueError) as exc_info:
        build_cookie_extensions(accounts=[
            AccountSpec(name='admin',
                        cookies=[{'name': 'a', 'value': 'b'}]),
        ])
    # Error message identifies which account and which cookie index
    msg = str(exc_info.value)
    assert "accounts['admin'].cookies[0]" in msg


def test_build_accepts_url_only_cookie():
    ext = build_cookie_extensions(cookies=[
        {'name': 'a', 'value': 'b', 'url': 'https://x.com/'},
    ])
    assert ext.pre_engine_hook is not None


# ---------------------------------------------------------------------------
# build_cookie_extensions
# ---------------------------------------------------------------------------


def test_empty_config_yields_empty_extensions():
    ext = build_cookie_extensions()
    assert ext.pre_engine_hook is None
    assert ext.extra_tools == []
    assert ext.extra_section is None


def test_cookies_only_yields_hook_only():
    ext = build_cookie_extensions(cookies=[
        {'name': 'session', 'value': 'x', 'domain': '.x'},
    ])
    assert ext.pre_engine_hook is not None
    assert ext.extra_tools == []
    assert ext.extra_section is None


def test_accounts_yield_hook_tool_section():
    ext = build_cookie_extensions(accounts=[
        AccountSpec(name='admin', cookies=[{'name': 'a', 'value': 'b', 'domain': '.x'}],
                    default=True, role='Full admin'),
    ])
    assert ext.pre_engine_hook is not None
    assert len(ext.extra_tools) == 1
    assert isinstance(ext.extra_tools[0], SwitchAccountTool)
    assert ext.extra_section is not None


def test_section_names_current_logged_in_identity():
    ext = build_cookie_extensions(accounts=[
        AccountSpec(name='alice_admin',
                    cookies=[{'name': 'a', 'value': 'b', 'domain': '.x'}],
                    default=True, role='Alice the admin'),
        AccountSpec(name='viewer',
                    cookies=[{'name': 'a', 'value': 'c', 'domain': '.x'}],
                    role='Read-only'),
    ])
    section = ext.extra_section
    assert 'alice_admin' in section
    assert 'logged in as **alice_admin**' in section
    # Role summary included.
    assert 'Alice the admin' in section
    assert 'Read-only' in section


def test_section_mentions_mutating_action_rule():
    ext = build_cookie_extensions(accounts=[
        AccountSpec(name='admin', cookies=[{'name': 'a', 'value': 'b', 'domain': '.x'}]),
    ])
    assert 'mutating action' in ext.extra_section
    assert 'Do NOT batch' in ext.extra_section


def test_no_default_and_no_fallback_no_hook():
    ext = build_cookie_extensions(accounts=[
        AccountSpec(name='admin', cookies=[{'name': 'a', 'value': 'b', 'domain': '.x'}]),
    ])
    # With accounts but no default, hook is None (nothing to inject at startup).
    assert ext.pre_engine_hook is None
    assert ext.extra_tools
    assert ext.extra_section is not None
    assert '(the fallback identity)' in ext.extra_section


def test_accounts_plus_fallback_cookies():
    """When accounts have no default but fallback is set, fallback fires."""
    ext = build_cookie_extensions(
        accounts=[AccountSpec(
            name='admin', cookies=[{'name': 'a', 'value': 'b', 'domain': '.x'}])],
        cookies=[{'name': 'fb', 'value': 'fb-val', 'domain': '.x'}],
    )
    assert ext.pre_engine_hook is not None


# ---------------------------------------------------------------------------
# Extensions + Extensions
# ---------------------------------------------------------------------------


def test_as_kwargs_has_correct_keys():
    ext = build_cookie_extensions(accounts=[AccountSpec(
        name='admin', cookies=[{'name': 'a', 'value': 'b', 'domain': '.x'}], default=True)])
    kwargs = ext.as_kwargs()
    assert set(kwargs.keys()) == {
        'pre_engine_hook', 'extra_tools', 'extra_section'}
    assert kwargs['extra_tools'][0].name == 'switch_account'


def test_as_kwargs_empty_tools_to_none():
    """Empty tool list is normalized to None for caller convenience."""
    ext = Extensions()
    kwargs = ext.as_kwargs()
    assert kwargs['extra_tools'] is None


def test_merge_empty_and_something():
    empty = Extensions()
    something = build_cookie_extensions(accounts=[
        AccountSpec(name='a',
                    cookies=[{'name': 'x', 'value': 'y', 'domain': '.x'}])])
    merged_left = empty + something
    merged_right = something + empty
    assert merged_left.extra_section == something.extra_section
    assert len(merged_left.extra_tools) == len(something.extra_tools)
    assert merged_right.extra_section == something.extra_section


def test_merge_extra_tools_concatenated():
    ext_a = Extensions(extra_tools=['tool_a'])
    ext_b = Extensions(extra_tools=['tool_b', 'tool_c'])
    merged = ext_a + ext_b
    assert merged.extra_tools == ['tool_a', 'tool_b', 'tool_c']


def test_merge_sections_joined_with_double_newline():
    ext_a = Extensions(extra_section='A section')
    ext_b = Extensions(extra_section='B section')
    merged = ext_a + ext_b
    assert merged.extra_section == 'A section\n\nB section'


def test_merge_conflicting_hooks_raises():
    def h1(mcp, port):
        pass

    def h2(mcp, port):
        pass

    ext_a = Extensions(pre_engine_hook=h1)
    ext_b = Extensions(pre_engine_hook=h2)
    with pytest.raises(ValueError, match='conflicting pre_engine_hook'):
        _ = ext_a + ext_b


def test_merge_one_hook_preserved():
    def h(mcp, port):
        pass

    ext_a = Extensions(pre_engine_hook=h)
    ext_b = Extensions()
    merged = ext_a + ext_b
    assert merged.pre_engine_hook is h


def test_merge_with_non_extensions_raises_type_error():
    with pytest.raises(TypeError, match='merge'):
        _ = Extensions() + {'pre_engine_hook': None}  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Hook actually wires through to CDPCookieClient with right cookies
# ---------------------------------------------------------------------------


def test_hook_invokes_cdp_client_with_default_cookies(monkeypatch):
    from webqa_agent.executor.flash.features import cookies as cookies_init

    captured_calls: list[tuple[str, tuple, dict]] = []

    class FakeClient:
        def __init__(self, port):
            self.port = port
            captured_calls.append(('init', (port,), {}))

        def connect(self):
            captured_calls.append(('connect', (), {}))

        def set_cookies(self, cookies):
            captured_calls.append(('set_cookies', (cookies,), {}))

        def close(self):
            captured_calls.append(('close', (), {}))

    monkeypatch.setattr(cookies_init, 'CDPCookieClient', FakeClient)

    ext = build_cookie_extensions(accounts=[
        AccountSpec(name='admin',
                    cookies=[{'name': 'a', 'value': 'b', 'domain': '.x'}], default=True),
    ])
    hook = ext.pre_engine_hook
    assert hook is not None

    mcp = MagicMock()
    hook(mcp, 9222)

    names = [c[0] for c in captured_calls]
    assert names == ['init', 'connect', 'set_cookies', 'close']
    # Inspect set_cookies args
    set_call = [c for c in captured_calls if c[0] == 'set_cookies'][0]
    assert set_call[1][0] == [{'name': 'a', 'value': 'b', 'domain': '.x'}]
    # Port threaded through
    init_call = [c for c in captured_calls if c[0] == 'init'][0]
    assert init_call[1][0] == 9222
