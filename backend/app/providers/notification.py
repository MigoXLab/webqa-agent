"""Notification provider interface and default implementation.

Provider implementations must expose:
- name: str - provider identifier
- send(**kwargs) -> bool - send notification
"""
import logging
from typing import Any, Dict, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class Notifier(Protocol):
    """Protocol for execution result notification providers."""

    name: str

    async def send(
        self,
        *,
        execution_id: str,
        business_name: str,
        result_count: Optional[Dict[str, Any]] = None,
        report_url: Optional[str] = None,
        webhook_url: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        """Send an execution result notification.

        Args:
            execution_id: Execution UUID string
            business_name: Business name
            result_count: Test result counts {"total": N, "passed": N, "failed": N, "warning": N}
            report_url: URL to the test report (if available)
            webhook_url: Target webhook URL (provider-specific)
            **kwargs: Additional provider-specific parameters

        Returns:
            True if notification was sent successfully
        """
        ...


class NoopNotifier:
    """Default provider: no notifications are sent.

    This is the default for open-source deployments. Install a notification
    extension (e.g. Slack webhook, email) to enable notifications.
    """

    name = 'noop'

    async def send(self, **kwargs: Any) -> bool:
        logger.debug('[Notification:noop] Notification skipped (no provider configured)')
        return True
