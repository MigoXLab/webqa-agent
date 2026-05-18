"""Tests for MCP tool functions."""
import pytest

from webqa_agent.mcp_server.tools.testing import _parse_cookies


def test_parse_cookies_valid():
    raw = [{'name': 'tok', 'value': 'abc', 'domain': '.example.com'}]
    result = _parse_cookies(raw)
    assert len(result) == 1
    assert result[0]['name'] == 'tok'


def test_parse_cookies_none():
    assert _parse_cookies(None) is None
    assert _parse_cookies([]) is None


def test_parse_cookies_not_list():
    with pytest.raises(ValueError, match='must be an array'):
        _parse_cookies('not a list')
