"""Tests for multi-account configuration and switching support."""

import json

from webqa_agent.browser.account_pool import AccountPool
from webqa_agent.config_models.base_config import AccountConfig
from webqa_agent.data.run_structures import Case, CaseStep


class TestAccountConfig:
    """Account config resolution and fallback behavior."""

    def test_account_config_loads_cookies_file_relative_to_config(self, tmp_path):
        config_dir = tmp_path / 'config'
        cookies_dir = config_dir / 'cookies'
        cookies_dir.mkdir(parents=True)

        cookies_path = cookies_dir / 'admin.json'
        cookies = [{'name': 'session', 'value': 'abc', 'domain': 'example.com', 'path': '/'}]
        cookies_path.write_text(json.dumps(cookies), encoding='utf-8')

        account = AccountConfig.from_raw(
            {
                'name': 'admin',
                'role': 'Administrator',
                'cookies_file': './cookies/admin.json',
                'default': True,
            },
            config_dir=str(config_dir),
        )

        assert account.resolved_cookies == cookies

    def test_account_pool_resolves_explicit_default_and_fallback(self):
        admin = AccountConfig.from_raw(
            {
                'name': 'admin',
                'role': 'Administrator',
                'cookies': [{'name': 'admin', 'value': '1', 'domain': 'example.com', 'path': '/'}],
                'default': True,
            }
        )
        viewer = AccountConfig.from_raw(
            {
                'name': 'viewer',
                'role': 'Viewer',
                'cookies': [{'name': 'viewer', 'value': '1', 'domain': 'example.com', 'path': '/'}],
            }
        )
        pool = AccountPool(
            accounts=[admin, viewer],
            fallback_cookies=[{'name': 'legacy', 'value': '1', 'domain': 'example.com', 'path': '/'}],
        )

        assert pool.resolve_cookies('viewer') == viewer.resolved_cookies
        assert pool.resolve_cookies(None) == admin.resolved_cookies
        assert pool.resolve_account_name(None) == 'admin'

        fallback_only = AccountPool(accounts=[], fallback_cookies=[{'name': 'legacy', 'value': '1'}])
        assert fallback_only.resolve_cookies(None) == [{'name': 'legacy', 'value': '1'}]


class TestRunStructures:
    """Run-mode schema compatibility for account-aware steps."""

    def test_case_step_parses_switch_account(self):
        step = CaseStep.model_validate({'switch_account': 'viewer'})

        assert step.step_type == 'switch_account'
        assert step.switch_account is not None
        assert step.switch_account.target == 'viewer'

    def test_case_accepts_optional_account_field(self):
        case = Case.model_validate(
            {
                'name': 'Permission comparison',
                'account': 'admin',
                'steps': [
                    {'action': 'Open settings'},
                    {'switch_account': 'viewer'},
                    {'verify': 'No permission prompt is shown'},
                ],
            }
        )

        assert case.account == 'admin'
        assert case.steps[1].step_type == 'switch_account'
