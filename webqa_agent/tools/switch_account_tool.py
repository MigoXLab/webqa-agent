"""Tool for switching browser identity during Gen mode execution."""

from typing import Any, Type

from pydantic import BaseModel, Field

from webqa_agent.tools.base import WebQABaseTool, WebQAToolMetadata
from webqa_agent.tools.registry import register_tool


class SwitchAccountSchema(BaseModel):
    """Arguments for switch_account tool."""

    account_name: str = Field(..., description='Target account name to switch to')


@register_tool
class SwitchAccountTool(WebQABaseTool):
    """Switch browser identity using a named account from the account pool."""

    name: str = 'switch_account'
    description: str = (
        'Switch browser identity to a different named test account before '
        'testing role-specific features or permission boundaries.'
    )
    args_schema: Type[BaseModel] = SwitchAccountSchema
    ui_tester_instance: Any = Field(...)
    account_pool: Any = Field(...)
    case_recorder: Any = Field(default=None)

    @classmethod
    def get_metadata(cls) -> WebQAToolMetadata:
        return WebQAToolMetadata(
            name='switch_account',
            category='action',
            description_short='Switch the active browser identity to another configured account.',
            description_long=(
                'Use this before visiting pages or flows that should be exercised '
                'under a different role, such as admin-only settings or read-only user journeys.'
            ),
            use_when=[
                'Testing permission boundaries',
                'Comparing role-specific UI or behavior',
                'Validating multi-role workflows in one case',
            ],
            dont_use_when=[
                'No accounts are configured',
                'The current test does not require a role change',
            ],
            priority=65,
        )

    @classmethod
    def get_required_params(cls) -> dict[str, str]:
        return {
            'ui_tester_instance': 'ui_tester_instance',
            'account_pool': 'account_pool',
        }

    async def _arun(self, account_name: str) -> str:
        account = self.account_pool.get(account_name)
        if not account:
            return self.format_failure(
                f"Account '{account_name}' not found. Available: {self.account_pool.account_names}",
                recovery_hints=['Check the configured account name spelling before retrying.'],
            )

        page = self.ui_tester_instance.browser_session.page
        current_url = getattr(self.ui_tester_instance, 'current_url', None)
        target_url = getattr(self.ui_tester_instance, 'target_url', None)
        navigate_url = current_url or target_url or (page.url if page else None)

        await self.ui_tester_instance.browser_session.switch_account(
            account.resolved_cookies,
            navigate_url=navigate_url,
        )
        await self.ui_tester_instance.refresh_session_bindings()
        self.ui_tester_instance.current_account_name = account.name
        self.ui_tester_instance.current_url = navigate_url

        self.safe_record_step(
            description=f"Switch to account '{account.name}'",
            model_io_data={
                'account': account.name,
                'role': account.role,
                'navigate_url': navigate_url,
            },
            status='passed',
            step_type='account_switch',
        )

        return self.format_success(
            f"Switched to account '{account.name}' (role: {account.role or 'N/A'}). "
            f"You are now operating as '{account.name}'."
        )
