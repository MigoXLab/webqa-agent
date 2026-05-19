"""Tests for mcp_quick execution config building."""
from types import SimpleNamespace

import pytest
from app.services.mcp_execution_config import (build_mcp_quick_gen_config,
                                               sanitize_mcp_quick_gen_config)


def test_build_mcp_quick_uses_legacy_sso_environment():
    env = SimpleNamespace(
        auth_type='sso',
        accounts=None,
        sso_username='user@example.com',
        sso_password='secret',
        sso_env='prod',
        cookies=None,
    )

    config = build_mcp_quick_gen_config(
        {'url': 'https://example.com', 'task': '测试登录'},
        model='gpt-test',
        workers=1,
        environment=env,
    )

    assert config['runner_source'] == 'mini'
    assert config['auth_type'] == 'sso'
    assert config['accounts'] == [{
        'name': 'default',
        'role': '',
        'default': True,
        'is_default': True,
        'sso_username': 'user@example.com',
        'sso_password': 'secret',
        'sso_env': 'prod',
    }]


def test_build_mcp_quick_uses_legacy_cookie_environment():
    cookies = [{'name': 'token', 'value': 'abc', 'domain': '.example.com'}]
    env = SimpleNamespace(
        auth_type='cookies',
        accounts=None,
        sso_username=None,
        sso_password=None,
        sso_env='prod',
        cookies=cookies,
    )

    config = build_mcp_quick_gen_config(
        {'url': 'https://example.com', 'task': '测试登录'},
        model='gpt-test',
        workers=1,
        environment=env,
    )

    assert config['browser_config']['cookies'] == cookies
    assert config['accounts'][0]['cookies'] == cookies


def test_build_mcp_quick_fails_when_environment_auth_missing_credentials():
    env = SimpleNamespace(
        auth_type='sso',
        accounts=None,
        sso_username=None,
        sso_password=None,
        sso_env='prod',
        cookies=None,
    )

    with pytest.raises(ValueError, match='auth_type=sso'):
        build_mcp_quick_gen_config(
            {'url': 'https://example.com', 'task': '测试登录'},
            model='gpt-test',
            workers=1,
            environment=env,
        )


def test_build_mcp_quick_empty_task_yields_no_objectives():
    config = build_mcp_quick_gen_config(
        {'url': 'https://example.com', 'task': ''},
        model='gpt-test',
        workers=1,
    )

    assert config['business_objectives'] == []
    assert 'task' not in config


def test_sanitize_mcp_quick_gen_config_removes_sso_passwords():
    config = {
        'accounts': [
            {'name': 'default', 'sso_username': 'user', 'sso_password': 'secret'},
        ],
    }

    sanitized = sanitize_mcp_quick_gen_config(config)

    assert 'sso_password' not in sanitized['accounts'][0]
    assert config['accounts'][0]['sso_password'] == 'secret'
