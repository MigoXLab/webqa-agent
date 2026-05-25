"""Shared helpers for building backend mcp_quick execution configs."""
from __future__ import annotations

import copy
from typing import Any, Optional


def _env_value(environment: Any, key: str, default: Any = None) -> Any:
    """Read an environment field from an ORM object or dict."""
    if environment is None:
        return default
    if isinstance(environment, dict):
        return environment.get(key, default)
    return getattr(environment, key, default)


def _account(name: str, **extra: Any) -> dict[str, Any]:
    return {'name': name, 'role': '', 'default': True, 'is_default': True, **extra}


def _legacy_sso_account(environment: Any) -> Optional[dict[str, Any]]:
    username = str(_env_value(environment, 'sso_username') or '').strip()
    password = str(_env_value(environment, 'sso_password') or '')
    if not username or not password:
        return None
    return _account(
        'default',
        sso_username=username,
        sso_password=password,
        sso_env=_env_value(environment, 'sso_env', 'prod') or 'prod',
    )


def _apply_environment_auth(gen_config: dict[str, Any], environment: Any) -> None:
    env_auth = _env_value(environment, 'auth_type', 'none') or 'none'
    env_accounts = _env_value(environment, 'accounts')
    env_cookies = _env_value(environment, 'cookies')

    if env_auth != 'none' and env_accounts:
        gen_config['auth_type'] = env_auth
        gen_config['accounts'] = env_accounts
        return

    if env_auth == 'sso':
        account = _legacy_sso_account(environment)
        if account is None:
            raise ValueError(
                'Environment auth_type=sso but no usable SSO account '
                'credentials are configured.'
            )
        gen_config['auth_type'] = 'sso'
        gen_config['accounts'] = [account]
        return

    if env_auth == 'cookies':
        if not isinstance(env_cookies, list) or not env_cookies:
            raise ValueError(
                'Environment auth_type=cookies but no cookies are configured.'
            )
        gen_config['browser_config'] = {'cookies': env_cookies}
        gen_config['accounts'] = [_account('default', cookies=env_cookies)]


def build_mcp_quick_gen_config(
    raw_config: dict[str, Any],
    *,
    model: str,
    workers: int,
    environment: Any = None,
) -> dict[str, Any]:
    """Convert MCP quick payload into Flash Gen config.

    Supports both the current multi-account environment shape and legacy
    environment-level SSO/cookies fields so MCP runs do not silently start
    logged out.
    """
    raw = dict(raw_config or {})
    report_lang = raw.pop('report_language', 'zh-CN')
    save_shots = raw.pop('save_screenshots', True)
    cookie_list = raw.pop('cookies', None)
    test_file_list = raw.pop('test_files', None)
    task = raw.pop('task', None)

    gen_config: dict[str, Any] = {
        'runner_source': 'mini',
        'target_url': raw.pop('url', ''),
        'business_objectives': [task] if task else [],
        'llm_config': {'model': model},
        'report_config': {
            'language': report_lang,
            'save_screenshots': save_shots,
        },
        'max_concurrent_tests': workers,
    }

    if cookie_list:
        gen_config['browser_config'] = {'cookies': cookie_list}
        gen_config['accounts'] = [_account('mcp', cookies=cookie_list)]
    elif environment is not None:
        _apply_environment_auth(gen_config, environment)

    if test_file_list:
        gen_config['test_files'] = test_file_list

    return gen_config


def sanitize_mcp_quick_gen_config(
    gen_config: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Return a copy safe to persist in Execution.config."""
    if gen_config is None:
        return None

    sanitized = copy.deepcopy(gen_config)
    accounts = sanitized.get('accounts')
    if isinstance(accounts, list):
        for account in accounts:
            if isinstance(account, dict):
                account.pop('sso_password', None)
    return sanitized
