"""State restoration for replanned test cases.

This module provides the StateRestorer class that ensures replanned test cases
start from the correct execution state instead of the default homepage.

Problem Context:
When a test case triggers reflection and generates replanned cases, these new
cases are created based on the current page state (e.g., login page). However,
without state restoration, they start from the homepage, causing initial steps
to fail because the expected page elements are not present.

Solution:
StateRestorer extracts the last URL from the source case's execution history
and navigates to that URL before executing the replanned case.

Architecture:
- Integrates with agent_worker_node in execute_agent.py
- Uses completed_cases to build state map (case_name -> last_url)
- Restores state only for cases marked with _is_replanned: true

Usage:
    restorer = StateRestorer(completed_cases, ui_tester)
    restored_url = await restorer.restore_state_if_needed(case)

Best Practices:
- Always check _is_replanned flag before restoration
- Log restoration actions for debugging
- Fall back to default URL if restoration fails
- Record restoration as a step in case_recorder

Reference:
- Analysis doc: /home/tutu/.claude/plans/peppy-percolating-turing_test_failures.md
- Section: P2 - Replanned用例状态恢复缺失
"""

import logging
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from webqa_agent.tools.core.ui_driver import UITester

logger = logging.getLogger(__name__)


class StateRestorer:
    """Restores execution state for replanned test cases.

    When a test case is replanned from another case's execution context,
    this utility ensures the starting state matches what the LLM expected
    when generating the replanned case.

    Key Features:
    - Extracts last URL from source case execution history
    - Navigates to restored URL before executing replanned case
    - Handles missing source cases gracefully
    - Logs all restoration actions

    Attributes:
        completed_cases: List of completed case results with recorded_case data
        ui_tester: UITester instance for performing navigation
        state_map: Dictionary mapping case_name to last_known_url
    """

    def __init__(self, completed_cases: List[Dict], ui_tester: Optional['UITester']):
        """Initialize StateRestorer with completed cases and UI tester.

        Args:
            completed_cases: List of completed case results from worker pool
                Each dict should have:
                - 'case_name': Name of the test case
                - 'recorded_case': Dict with execution history including 'steps'
            ui_tester: UITester instance for performing state restorations.
                Can be None during initialization; set per-worker before use.

        Example:
            completed_cases = [
                {
                    'case_name': 'Verify_Header_Try_Now_Button',
                    'recorded_case': {
                        'steps': [
                            {'description': '...', 'current_url': 'https://...'},
                            {'description': '...', 'current_url': 'https://.../login'}
                        ]
                    }
                }
            ]
            restorer = StateRestorer(completed_cases, ui_tester)
        """
        self.completed_cases = completed_cases
        self.ui_tester = ui_tester

        # Build map: case_name -> last_known_url
        self.state_map = self._build_state_map()

        logger.debug(
            f'StateRestorer initialized with {len(self.state_map)} '
            f'restorable states: {list(self.state_map.keys())}'
        )

    def _build_state_map(self) -> Dict[str, str]:
        """Build mapping from case name to last known URL.

        Returns:
            Dictionary mapping case_name to last_known_url

        Note:
            Only includes cases where last URL could be extracted
        """
        state_map = {}

        for case in self.completed_cases:
            case_name = case.get('case_name')
            if not case_name:
                continue

            # Try to get recorded_case from both possible locations
            recorded_case = case.get('recorded_case')
            if not recorded_case and isinstance(case, dict):
                # Fallback: sometimes recorded_case is at top level
                recorded_case = case

            last_url = self._extract_last_url(recorded_case)

            if last_url:
                state_map[case_name] = last_url
                logger.debug(f"Mapped '{case_name}' -> {last_url}")

        return state_map

    def _extract_last_url(self, recorded_case: Optional[Dict]) -> Optional[str]:
        """Extract the last URL from recorded case steps.

        Args:
            recorded_case: Recorded execution result with 'steps' list

        Returns:
            Last URL if found, None otherwise

        Extraction Strategy:
        1. Check last step's 'current_url' field
        2. Fallback to 'url' field
        3. Iterate backwards to find first step with URL
        4. Return None if no URL found
        """
        if not recorded_case:
            return None

        steps = recorded_case.get('steps', [])
        if not steps:
            return None

        # Iterate backwards to find first step with URL
        for step in reversed(steps):
            # Try both 'current_url' and 'url' fields
            url = step.get('current_url') or step.get('url')
            if url:
                return url

        return None

    async def restore_state_if_needed(self, case: Dict) -> Optional[str]:
        """Restore state for a replanned case if needed.

        Args:
            case: Test case dict with potential _is_replanned field

        Returns:
            Restored URL if restoration was performed, None otherwise

        Logic:
        1. Check if case is marked as replanned
        2. Get source case name from _replan_source
        3. Look up last URL from state_map
        4. Navigate to that URL using ui_tester
        5. Return restored URL or None

        Example:
            case = {
                'name': 'Verify_Login_Language_Switcher',
                '_is_replanned': True,
                '_replan_source': 'Verify_Header_Try_Now_Button'
            }
            restored_url = await restorer.restore_state_if_needed(case)
            # Returns: 'https://discovery.intern-ai.org.cn/login'
        """
        # Check 1: Is this a replanned case?
        if not case.get('_is_replanned'):
            logger.debug(f"Case '{case.get('name')}' is not replanned, skipping restoration")
            return None

        # Check 2: Get source case name
        replan_source = case.get('_replan_source')
        if not replan_source:
            logger.warning(
                f"Case '{case.get('name')}' is replanned but missing _replan_source field"
            )
            return None

        # Check 3: Look up last URL from source case
        if replan_source not in self.state_map:
            logger.warning(
                f"Cannot restore state for '{case.get('name')}': "
                f"source case '{replan_source}' not found in state map. "
                f'Available cases: {list(self.state_map.keys())}'
            )
            return None

        target_url = self.state_map[replan_source]

        logger.info(
            f"Restoring state for replanned case '{case.get('name')}' "
            f"from source '{replan_source}' to URL: {target_url}"
        )

        # Check 4: Perform restoration
        try:
            # Navigate to restored URL
            page = await self.ui_tester.get_current_page()
            if not page:
                logger.error('Cannot restore state: no current page available')
                return None

            current_url = page.url

            # Skip navigation if already at target URL
            if current_url == target_url:
                logger.info(f'Already at target URL {target_url}, skipping navigation')
                return target_url

            # Perform navigation
            await page.goto(target_url, wait_until='networkidle', timeout=30000)
            logger.info(f'Successfully restored state to: {target_url}')

            return target_url

        except Exception as e:
            logger.error(
                f"State restoration failed for '{case.get('name')}': {e}",
                exc_info=True,
            )
            return None

    def get_restorable_cases(self) -> List[str]:
        """Get list of case names that can be used as restoration sources.

        Returns:
            List of case names with known URLs

        Useful for debugging and validation.
        """
        return list(self.state_map.keys())

    def has_restoration_for(self, replan_source: str) -> bool:
        """Check if restoration is available for a source case.

        Args:
            replan_source: Name of the source case

        Returns:
            True if restoration URL is available, False otherwise

        Example:
            if restorer.has_restoration_for('Verify_Header_Try_Now_Button'):
                print('Restoration available')
        """
        return replan_source in self.state_map

    def update_state_map(self, completed_cases: List[Dict]) -> None:
        """Update state map with new completed cases.

        This method allows reusing the same StateRestorer instance across
        multiple test case executions, avoiding repeated reconstruction.

        Args:
            completed_cases: Updated list of completed case results

        Performance Note:
            Call this method when new cases have completed to update the
            restorable state map without recreating the StateRestorer instance.

        Example:
            # Created once in run_test_cases
            restorer = StateRestorer([], ui_tester)

            # Updated in worker before each restoration
            restorer.update_state_map(completed_cases)
            restored_url = await restorer.restore_state_if_needed(case)
        """
        self.completed_cases = completed_cases
        self.state_map = self._build_state_map()
        logger.debug(
            f'State map updated: {len(self.state_map)} restorable states available'
        )
