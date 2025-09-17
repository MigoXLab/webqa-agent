import logging
import uuid
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Coroutine

from webqa_agent.browser.config import DEFAULT_CONFIG
from webqa_agent.data import ParallelTestSession, TestConfiguration, TestType, get_default_test_name
from webqa_agent.executor import ParallelTestExecutor
from webqa_agent.utils import Display
from webqa_agent.utils.get_log import GetLog
from webqa_agent.utils.log_icon import icon

class ParallelMode:
    """Parallel test mode - runs tests concurrently with data isolation"""

    def __init__(self, tests: List, max_concurrent_tests: int = 4):
        self.max_concurrent_tests = max_concurrent_tests
        self.executor = ParallelTestExecutor(max_concurrent_tests)

    async def run(
        self,
        url: str,
        llm_config: Dict[str, Any],
        browser_config: Optional[Dict[str, Any]] = None,
        test_configurations: Optional[List[Dict[str, Any]]] = None,
        log_cfg: Optional[Dict[str, Any]] = None,
        report_cfg: Optional[Dict[str, Any]] = None
    ) -> Tuple[Dict[str, Any], str]:
        """Run tests in parallel mode with configurable test types.

        Args:
            url: Target URL to test
            llm_config: Configuration for language models
            browser_config: Default browser configuration
            test_configurations: Custom test configurations for parallel execution
            log_cfg: Configuration for logger
            report_cfg: Configuration for report

        Returns:
            Tuple of (aggregated_results, report_path)
        """
        try:

            GetLog.get_log(log_level=log_cfg["level"])
            Display.init(language=report_cfg["language"])
            Display.display.start()

            logging.info(f"{icon['rocket']} Starting tests for URL: {url}, parallel mode {self.max_concurrent_tests}")

            # Use default config if none provided
            if not browser_config:
                browser_config = DEFAULT_CONFIG.copy()

            # Create test session
            test_session = ParallelTestSession(session_id=str(uuid.uuid4()), target_url=url, llm_config=llm_config)

            # Use a fresh per-task timestamp for reports and keep logs separate
            report_ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
            os.environ["WEBQA_REPORT_TIMESTAMP"] = report_ts

            # Configure tests based on input or legacy test objects
            if test_configurations:
                self._configure_tests_from_config(test_session, test_configurations, browser_config, report_cfg)

            # Execute tests in parallel
            completed_session = await self.executor.execute_parallel_tests(test_session)

            result = completed_session.aggregated_results.get("count", {})
            

            await Display.display.stop()
            Display.display.render_summary()
            # Return results in format compatible with existing code
            return (
                completed_session.aggregated_results,
                completed_session.report_path,
                completed_session.html_report_path,
                result,
            )

        except Exception as e:
            logging.error(f"Error in parallel mode: {e}")
            raise

    def _configure_tests_from_config(
        self,
        test_session: ParallelTestSession,
        test_configurations: List[Dict[str, Any]],
        default_browser_config: Dict[str, Any],
        report_cfg: Dict[str, Any]
    ):
        """Configure tests from provided configuration."""
        for config in test_configurations:
            test_type_str = config.get("test_type", "basic_test")

            # Map string to TestType enum
            test_type = self._map_test_type(test_type_str)

            # Merge browser config
            browser_config = {**default_browser_config, **config.get("browser_config", {})}

            test_config = TestConfiguration(
                test_id=str(uuid.uuid4()),
                test_type=test_type,
                test_name=get_default_test_name(test_type, report_cfg["language"]),
                enabled=config.get("enabled", True),
                browser_config=browser_config,
                report_config=report_cfg,
                test_specific_config=config.get("test_specific_config", {}),
                timeout=config.get("timeout", 300),
                retry_count=config.get("retry_count", 0),
                dependencies=config.get("dependencies", []),
            )

            test_session.add_test_configuration(test_config)

    def _map_test_type(self, test_type_str: str) -> TestType:
        """Map string to TestType enum."""
        mapping = {
            "ui_agent_langgraph": TestType.UI_AGENT_LANGGRAPH,
            "ux_test": TestType.UX_TEST,
            "performance": TestType.PERFORMANCE,
            "basic_test": TestType.BASIC_TEST,
            # "web_basic_check": TestType.WEB_BASIC_CHECK,
            # "button_test": TestType.BUTTON_TEST,
            "security": TestType.SECURITY_TEST,
            "security_test": TestType.SECURITY_TEST,
        }

        return mapping.get(test_type_str, TestType.BASIC_TEST)
