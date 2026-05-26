"""Tests for ``features.cookies.account_pool``."""
from __future__ import annotations

import pytest

from webqa_agent.executor.flash.features.cookies.account_pool import (
    AccountPool, AccountSpec)

COOK_A = [{'name': 'a', 'value': '1'}]
COOK_B = [{'name': 'b', 'value': '2'}]
COOK_C = [{'name': 'c', 'value': '3'}]


def test_empty_pool_empty_fallback_resolves_none():
    pool = AccountPool()
    assert pool.resolve_cookies(None) is None
    assert pool.resolve_cookies('anything') is None


def test_fallback_returned_when_no_accounts():
    pool = AccountPool(fallback_cookies=COOK_A)
    assert pool.resolve_cookies(None) == COOK_A


def test_default_account_wins_over_fallback():
    pool = AccountPool(
        accounts=[AccountSpec(name='admin', cookies=COOK_A, default=True)],
        fallback_cookies=COOK_B,
    )
    assert pool.resolve_cookies(None) == COOK_A


def test_explicit_name_wins_over_default():
    pool = AccountPool(
        accounts=[
            AccountSpec(name='admin', cookies=COOK_A, default=True),
            AccountSpec(name='viewer', cookies=COOK_B),
        ],
        fallback_cookies=COOK_C,
    )
    assert pool.resolve_cookies('viewer') == COOK_B


def test_unknown_name_returns_none_not_fallback():
    pool = AccountPool(
        accounts=[AccountSpec(name='admin', cookies=COOK_A)],
        fallback_cookies=COOK_B,
    )
    assert pool.resolve_cookies('nobody') is None


def test_no_default_no_fallback_resolve_none():
    pool = AccountPool(
        accounts=[AccountSpec(name='admin', cookies=COOK_A)])
    assert pool.resolve_cookies(None) is None


def test_duplicate_names_raise():
    with pytest.raises(ValueError, match='duplicate'):
        AccountPool(accounts=[
            AccountSpec(name='a', cookies=COOK_A),
            AccountSpec(name='a', cookies=COOK_B),
        ])


def test_multiple_defaults_raise():
    with pytest.raises(ValueError, match='multiple defaults'):
        AccountPool(accounts=[
            AccountSpec(name='a', cookies=COOK_A, default=True),
            AccountSpec(name='b', cookies=COOK_B, default=True),
        ])


@pytest.mark.parametrize('bad', ['', '   ', '\t\n'])
def test_whitespace_name_rejected(bad):
    with pytest.raises(ValueError, match='non-empty'):
        AccountPool(accounts=[AccountSpec(name=bad, cookies=COOK_A)])


def test_default_name_property_when_set():
    pool = AccountPool(accounts=[
        AccountSpec(name='admin', cookies=COOK_A, default=True)])
    assert pool.default_name == 'admin'


def test_default_name_property_when_unset():
    pool = AccountPool(accounts=[
        AccountSpec(name='admin', cookies=COOK_A)])
    assert pool.default_name is None


def test_account_names_listing():
    pool = AccountPool(accounts=[
        AccountSpec(name='admin', cookies=COOK_A),
        AccountSpec(name='viewer', cookies=COOK_B),
    ])
    assert pool.account_names == ['admin', 'viewer']


def test_has_accounts():
    assert not AccountPool().has_accounts
    assert not AccountPool(fallback_cookies=COOK_A).has_accounts
    assert AccountPool(accounts=[
        AccountSpec(name='a', cookies=COOK_A)]).has_accounts


def test_role_summary_format():
    pool = AccountPool(accounts=[
        AccountSpec(name='admin', cookies=COOK_A, default=True,
                    role='Full admin'),
        AccountSpec(name='viewer', cookies=COOK_B, role=''),
    ])
    summary = pool.get_role_summary()
    assert '- admin [default]: Full admin' in summary
    assert '- viewer: (no role)' in summary


# ------------------- security-relevant AccountSpec.__repr__ ----------------


def test_account_spec_repr_redacts_cookies():
    """JWT leakage prevention: repr must not include cookie values."""
    spec = AccountSpec(
        name='admin',
        cookies=[{'name': 'auth',
                  'value': 'eyJhbGciOiJIUzI1NiJ9.super-secret-jwt'}],
        role='Full admin',
        default=True,
    )
    r = repr(spec)
    assert 'eyJhbGciOiJIUzI1NiJ9' not in r
    assert 'super-secret-jwt' not in r
    assert '1 cookie' in r  # count preserved for diagnostics
    assert 'admin' in r     # name still visible
