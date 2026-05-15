"""Tests for MCP tool functions."""
import json

import pytest

from webqa_agent.mcp_server.tools.testing import _parse_cookies


def test_parse_cookies_valid():
    raw = json.dumps([{'name': 'tok', 'value': 'abc', 'domain': '.example.com'}])
    result = _parse_cookies(raw)
    assert len(result) == 1
    assert result[0]['name'] == 'tok'


def test_parse_cookies_none():
    assert _parse_cookies(None) is None
    assert _parse_cookies('') is None


def test_parse_cookies_invalid_json():
    with pytest.raises(ValueError, match='Invalid cookies JSON'):
        _parse_cookies('not json')


def test_parse_cookies_not_array():
    with pytest.raises(ValueError, match='must be a JSON array'):
        _parse_cookies('{"name":"tok"}')
