"""Tests for account bootstrap cookie resolution."""
from typing import Any, Dict, List

from webqa_agent.browser.account_pool import AccountPool
from webqa_agent.config_models.base_config import AccountConfig
from webqa_agent.utils.config import load_accounts


def _cookie(name: str, value: str) -> Dict[str, Any]:
    return {
        'name': name,
        'value': value,
        'domain': '.example.com',
        'path': '/',
    }


def _account(name: str, cookie_value: str, default: bool = False) -> AccountConfig:
    return AccountConfig(
        name=name,
        role=name,
        cookies=[_cookie('session', cookie_value)],
        default=default,
    )


def test_resolve_cookies_prefers_fallback_for_implicit_startup() -> None:
    """Implicit startup should keep legacy cookie behavior when available."""
    fallback_cookies: List[Dict[str, Any]] = [_cookie('session', 'legacy-cookie')]
    pool = AccountPool(
        accounts=[_account('admin', 'admin-cookie', default=True)],
        fallback_cookies=fallback_cookies,
    )

    assert pool.resolve_cookies(None) == fallback_cookies
    assert pool.resolve_account_name(None) is None


def test_resolve_cookies_uses_explicit_account_over_fallback() -> None:
    """Explicit case.account should still use the named account."""
    fallback_cookies: List[Dict[str, Any]] = [_cookie('session', 'legacy-cookie')]
    pool = AccountPool(
        accounts=[
            _account('admin', 'admin-cookie', default=True),
            _account('user', 'user-cookie'),
        ],
        fallback_cookies=fallback_cookies,
    )

    assert pool.resolve_cookies('user') == [_cookie('session', 'user-cookie')]
    assert pool.resolve_account_name('user') == 'user'


def test_resolve_cookies_uses_default_account_when_no_fallback() -> None:
    """Default account should bootstrap only when legacy cookies are absent."""
    pool = AccountPool(accounts=[_account('admin', 'admin-cookie', default=True)])

    assert pool.resolve_cookies(None) == [_cookie('session', 'admin-cookie')]
    assert pool.resolve_account_name(None) == 'admin'


def test_load_accounts_accepts_legacy_is_default_and_none_role() -> None:
    """Legacy backend account payloads should remain compatible with run config loading."""
    accounts = load_accounts([{
        'name': 'admin',
        'role': None,
        'is_default': True,
        'cookies': [_cookie('session', 'legacy-cookie')],
    }])

    assert accounts is not None
    assert len(accounts) == 1
    assert accounts[0].role == ''
    assert accounts[0].default is True
