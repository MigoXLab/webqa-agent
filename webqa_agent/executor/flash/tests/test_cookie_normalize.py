"""Tests for cookie dict → CDP ``Network.CookieParam`` normalisation."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from webqa_agent.executor.flash.features.cookies.cdp_client import \
    _normalize_cookie as normalize_cookie


def test_basic_fields_preserved():
    c = {'name': 'a', 'value': 'b', 'domain': '.example.com',
         'path': '/x', 'secure': True, 'httpOnly': True}
    out = normalize_cookie(c)
    assert out == {
        'name': 'a', 'value': 'b', 'domain': '.example.com',
        'path': '/x', 'secure': True, 'httpOnly': True,
    }


def test_path_defaults_to_slash():
    out = normalize_cookie({'name': 'a', 'value': 'b'})
    assert out['path'] == '/'


def test_empty_domain_omitted():
    out = normalize_cookie({'name': 'a', 'value': 'b', 'domain': ''})
    assert 'domain' not in out


def test_leading_dot_in_domain_preserved():
    """CDP accepts both forms; the dot matters for subdomain scoping."""
    out = normalize_cookie(
        {'name': 'a', 'value': 'b', 'domain': '.example.com'})
    assert out['domain'] == '.example.com'


def test_secure_and_httponly_falsy_omitted():
    out = normalize_cookie(
        {'name': 'a', 'value': 'b', 'secure': False, 'httpOnly': False})
    assert 'secure' not in out
    assert 'httpOnly' not in out


def test_unknown_keys_dropped():
    out = normalize_cookie(
        {'name': 'a', 'value': 'b', 'thisIsNotCDP': 'x', 'size': 99})
    assert 'thisIsNotCDP' not in out
    assert 'size' not in out


# ------------------------------- sameSite ---------------------------------


@pytest.mark.parametrize('ss', ['Strict', 'Lax', 'None'])
def test_samesite_canonical_values_preserved(ss):
    out = normalize_cookie({'name': 'a', 'value': 'b', 'sameSite': ss})
    assert out['sameSite'] == ss


@pytest.mark.parametrize('ss', ['lax', 'strict', 'none', 'LAX', 'bogus'])
def test_samesite_lowercase_and_invalid_dropped(ss):
    out = normalize_cookie({'name': 'a', 'value': 'b', 'sameSite': ss})
    assert 'sameSite' not in out


# ------------------------------- expires ----------------------------------


def test_expires_positive_epoch_preserved():
    out = normalize_cookie(
        {'name': 'a', 'value': 'b', 'expires': 1700000000})
    assert out['expires'] == 1700000000.0
    assert isinstance(out['expires'], float)


def test_expires_zero_becomes_session_cookie():
    """Boundary: 0 is explicitly the year 1970; we treat it as session."""
    out = normalize_cookie(
        {'name': 'a', 'value': 'b', 'expires': 0})
    assert 'expires' not in out


def test_expires_negative_becomes_session_cookie():
    out = normalize_cookie(
        {'name': 'a', 'value': 'b', 'expires': -1})
    assert 'expires' not in out


def test_expires_iso_string_parsed():
    out = normalize_cookie(
        {'name': 'a', 'value': 'b', 'expires': '2024-12-31T23:59:59+00:00'})
    assert out['expires'] == datetime(
        2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp()


def test_expires_iso_with_z_suffix_parsed():
    out = normalize_cookie(
        {'name': 'a', 'value': 'b', 'expires': '2024-01-01T00:00:00Z'})
    assert out['expires'] == datetime(
        2024, 1, 1, tzinfo=timezone.utc).timestamp()


def test_expires_unparsable_string_dropped():
    out = normalize_cookie(
        {'name': 'a', 'value': 'b', 'expires': 'not-a-date'})
    assert 'expires' not in out


def test_expires_datetime_object_dropped():
    """Datetime is not int/float/str — CDP needs epoch float; caller must
    convert."""
    out = normalize_cookie(
        {'name': 'a', 'value': 'b', 'expires': datetime(2030, 1, 1)})
    assert 'expires' not in out


def test_expires_bool_rejected():
    """Bool is a subclass of int — True must not become epoch=1."""
    out = normalize_cookie(
        {'name': 'a', 'value': 'b', 'expires': True})
    assert 'expires' not in out


def test_missing_name_raises_keyerror():
    with pytest.raises(KeyError):
        normalize_cookie({'value': 'b'})


def test_missing_value_raises_keyerror():
    with pytest.raises(KeyError):
        normalize_cookie({'name': 'a'})


# --------------------------------- url -----------------------------------


def test_url_https_preserved():
    out = normalize_cookie(
        {'name': 'a', 'value': 'b', 'url': 'https://example.com/path'})
    assert out['url'] == 'https://example.com/path'


def test_url_http_preserved():
    out = normalize_cookie(
        {'name': 'a', 'value': 'b', 'url': 'http://example.com'})
    assert out['url'] == 'http://example.com'


def test_url_and_domain_both_preserved():
    """CDP accepts both — domain scopes, url anchors the set target."""
    out = normalize_cookie({
        'name': 'a', 'value': 'b',
        'domain': '.example.com',
        'url': 'https://app.example.com/',
    })
    assert out['domain'] == '.example.com'
    assert out['url'] == 'https://app.example.com/'


@pytest.mark.parametrize('bad', [
    'ftp://example.com', 'file:///etc/passwd',
    'javascript:alert(1)', 'ws://x', 'data:text/html,x',
])
def test_url_non_http_scheme_dropped(bad):
    out = normalize_cookie({'name': 'a', 'value': 'b', 'url': bad})
    assert 'url' not in out


@pytest.mark.parametrize('bad', ['', 42, ['https://x']])
def test_url_non_string_or_empty_dropped(bad):
    out = normalize_cookie({'name': 'a', 'value': 'b', 'url': bad})
    assert 'url' not in out


def test_url_none_dropped():
    out = normalize_cookie({'name': 'a', 'value': 'b', 'url': None})
    assert 'url' not in out
