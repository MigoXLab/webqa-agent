"""Case JSON synchronization utility for maintaining data consistency.

This module provides the CaseJsonSynchronizer class that ensures cases.json
(test plan) stays synchronized with recorded execution results (recorded_cases).

Architecture:
- Single Source of Truth: recorded_case data is authoritative for execution status
- Immutable History: Preserves original test plan structure in cases.json
- Sync on Completion: Updates cases.json after test execution completes

Key Features:
- Status synchronization (pending -> passed/failed/warning)
- Step summary extraction from recorded cases
- Execution metadata tracking (start_time, end_time, duration)
- Safe file I/O with error handling

Usage:
    synchronizer = CaseJsonSynchronizer(cases_json_path)
    synchronizer.sync_cases(test_cases, recorded_cases)

Best Practices (based on LangGraph persistence patterns):
- Use recorded_cases as Single Source of Truth
- Preserve cases.json as immutable test plan snapshot
- Sync final status only after execution completes
- Handle partial executions (not all cases executed)

Reference:
- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- Test reporting: https://www.browserstack.com/test-management/features/reports-analytics
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import yaml

logger = logging.getLogger(__name__)


class _IndentedYamlDumper(yaml.Dumper):
    """Custom YAML dumper that indents list items under their parent key.

    Produces readable output matching config_run.yaml style:
        cases:
          - name: Test_Login
            steps:
              - action: Click login button
              - verify: Check page title

    Instead of the default PyYAML style where list items are not indented.
    """

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        return super().increase_indent(flow, False)


class CaseJsonSynchronizer:
    """Synchronizes test case execution results back to cases.json.

    This ensures that cases.json reflects the actual execution status,
    while maintaining the original test plan structure.

    The synchronizer follows the Single Source of Truth pattern:
    recorded_case (from CaseRecorder) is the authoritative execution state,
    and cases.json is updated to match.

    Attributes:
        cases_json_path: Path to the cases.json file to synchronize
    """

    def __init__(self, cases_json_path: Path):
        """Initialize synchronizer with target cases.json path.

        Args:
            cases_json_path: Path to the cases.json file to sync

        Raises:
            ValueError: If path is None or empty
        """
        if not cases_json_path:
            raise ValueError('cases_json_path cannot be None or empty')

        self.cases_json_path = Path(cases_json_path)
        logger.debug(f'CaseJsonSynchronizer initialized for: {self.cases_json_path}')

    def sync_cases(
        self,
        test_cases: List[Dict[str, Any]],
        recorded_cases: List[Dict[str, Any]]
    ) -> None:
        """Sync execution results to cases.json.

        This method updates the cases.json file with execution results from
        recorded_cases. It preserves the original test plan structure while
        adding execution metadata.

        Args:
            test_cases: Original test case definitions (from planning)
            recorded_cases: Recorded execution results (from case_recorder)

        Updates cases.json with:
        - final status (passed/failed/warning)
        - execution_steps list
        - execution metadata (start_time, end_time, duration)

        Example:
            Original test_case:
            {
                "case_id": "case_1",
                "name": "Verify_Login",
                "status": "pending",
                "steps": [...]
            }

            After sync:
            {
                "case_id": "case_1",
                "name": "Verify_Login",
                "status": "passed",  # ✅ Updated
                "steps": [...],
                "execution_steps": [  # ✅ Added
                    {"description": "Click login", "status": "passed"}
                ],
                "start_time": "2026-01-29T17:28:17",  # ✅ Added
                "end_time": "2026-01-29T17:28:30",    # ✅ Added
                "duration": 13.2                       # ✅ Added
            }
        """
        if not recorded_cases:
            logger.warning('No recorded cases to sync')
            return

        # Build case_id -> recorded_case mapping
        recorded_map = self._build_recorded_map(recorded_cases)

        if not recorded_map:
            logger.warning('No valid recorded cases found (all missing case_id)')
            return

        # Update test cases with execution results
        updated_cases = []
        sync_count = 0

        for case in test_cases:
            case_id = case.get('case_id')
            if not case_id:
                logger.warning(f"Case missing case_id: {case.get('name')}")
                updated_cases.append(case)
                continue

            # Copy original case to avoid mutation
            updated_case = case.copy()

            # Merge execution results if available
            if case_id in recorded_map:
                recorded = recorded_map[case_id]
                self._merge_execution_results(updated_case, recorded)
                sync_count += 1

            updated_cases.append(updated_case)

        # Write back to cases.json
        self._write_cases_json(updated_cases)

        # Generate run-mode compatible YAML alongside cases.json
        self._write_cases_yaml(updated_cases)

        logger.info(
            f'Synchronized {sync_count}/{len(test_cases)} case results to {self.cases_json_path}'
        )

    def _build_recorded_map(
        self,
        recorded_cases: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Build case_id -> recorded_case mapping.

        Args:
            recorded_cases: List of recorded execution results

        Returns:
            Dictionary mapping case_id to recorded_case data

        Note:
            Handles both 'case_id' and 'name' fields for compatibility
        """
        recorded_map = {}

        for recorded in recorded_cases:
            # Try case_id first, fallback to name
            case_id = recorded.get('case_id') or recorded.get('name')

            if not case_id:
                logger.warning(
                    f'Recorded case missing both case_id and name, skipping: '
                    f"{recorded.get('description', 'unknown')}"
                )
                continue

            if case_id in recorded_map:
                logger.warning(
                    f'Duplicate case_id in recorded cases: {case_id}, '
                    f'using latest result'
                )

            recorded_map[case_id] = recorded

        return recorded_map

    def _merge_execution_results(
        self,
        updated_case: Dict[str, Any],
        recorded: Dict[str, Any]
    ) -> None:
        """Merge execution results into test case.

        Modifies updated_case in-place to add execution results.

        Args:
            updated_case: Test case dict to update (modified in-place)
            recorded: Recorded execution result to merge

        Updates:
            - status: Final execution status (passed/failed/warning)
            - execution_steps: List of executed step summaries
            - planned_steps: Original planned steps (from case_recorder, before adaptive recovery)
            - step_expansion_ratio: Ratio of execution to planned steps
            - start_time: Execution start timestamp
            - end_time: Execution end timestamp
            - duration: Execution duration in seconds
        """
        # Update status (most critical field)
        updated_case['status'] = recorded.get('status', 'pending')

        # Use original_planned_steps from case_recorder (captured before adaptive recovery)
        # Falls back to current steps if original not available (backward compatibility)
        original_planned = recorded.get('original_planned_steps')
        if original_planned is not None:
            updated_case['planned_steps'] = original_planned
        elif 'steps' in updated_case and 'planned_steps' not in updated_case:
            updated_case['planned_steps'] = updated_case['steps']

        # Extract step summaries from recorded execution data
        execution_steps = self._extract_step_summaries(recorded)
        updated_case['execution_steps'] = execution_steps

        # Calculate step expansion ratio (execution vs planned)
        # This helps identify cases where UI Agent generated many sub-steps
        planned_count = len(updated_case.get('planned_steps', []))
        execution_count = len(execution_steps)
        if planned_count > 0:
            updated_case['step_expansion_ratio'] = round(execution_count / planned_count, 2)
        else:
            updated_case['step_expansion_ratio'] = 1.0

        # Add execution metadata
        for field in ('start_time', 'end_time', 'duration'):
            if field in recorded:
                updated_case[field] = recorded[field]

        # Add error information for failed/warning cases
        if recorded.get('status') in ('failed', 'warning'):
            for field in ('error', 'failure_type'):
                if field in recorded:
                    updated_case[field] = recorded[field]

    def _extract_step_summaries(self, recorded_case: Dict) -> List[Dict]:
        """Extract step summaries from recorded case.

        Args:
            recorded_case: Recorded execution result

        Returns:
            List of step summary dicts with description, status, timestamp

        Example:
            Input: recorded_case['steps'] = [
                {
                    'description': 'Click login button',
                    'status': 'passed',
                    'timestamp': '2026-01-29T17:28:20',
                    'model_io_data': {...}  # Excluded
                }
            ]

            Output: [
                {
                    'description': 'Click login button',
                    'status': 'passed',
                    'timestamp': '2026-01-29T17:28:20'
                }
            ]
        """
        steps = recorded_case.get('steps', [])

        return [
            {
                'description': step.get('description'),
                'status': step.get('status'),
                'timestamp': step.get('timestamp')
            }
            for step in steps
            if step.get('description')  # Filter out steps without description
        ]

    def _generate_run_mode_steps(self, execution_steps: List[Dict]) -> List[Dict[str, str]]:
        """Generate run-mode compatible step list from execution steps.

        Parses step descriptions (prefixed with 'action:', 'verify:', 'ux_verify:')
        into structured dicts matching config_run.yaml format. Steps from custom tools
        (unknown prefixes or no prefix) are mapped to 'custom:' type.

        Args:
            execution_steps: List of execution step dicts with 'description' field

        Returns:
            List of single-key dicts like:
            [{"action": "Click button"}, {"verify": "Check result"}, {"custom": "..."}]

        Example:
            Input: [
                {"description": "action: Click login button", "status": "passed"},
                {"description": "verify: Dashboard is visible", "status": "passed"},
                {"description": "lighthouse: Run performance audit", "status": "passed"},
            ]
            Output: [
                {"action": "Click login button"},
                {"verify": "Dashboard is visible"},
                {"custom": "lighthouse: Run performance audit"},
            ]
        """
        run_steps: List[Dict[str, str]] = []
        known_prefixes = ('action', 'verify', 'ux_verify')

        for step in execution_steps:
            desc = step.get('description', '')
            if not desc:
                continue

            # Parse "prefix: content" format from recorder descriptions
            if ': ' in desc:
                prefix, content = desc.split(': ', 1)
                prefix_lower = prefix.strip().lower()
                if prefix_lower in known_prefixes:
                    run_steps.append({prefix_lower: content})
                    continue

            # All other steps (custom tools, no prefix) → custom type
            run_steps.append({'custom': desc})

        return run_steps

    def _write_cases_yaml(self, updated_cases: List[Dict]) -> None:
        """Generate run-mode compatible YAML file alongside cases.json.

        Converts execution results into config_run.yaml format that users
        can directly copy-paste for re-running test cases.

        Args:
            updated_cases: Synced test cases with execution_steps populated

        Output file: cases.yaml in the same directory as cases.json
        """
        yaml_path = self.cases_json_path.parent / 'cases.yaml'

        cases_yaml: List[Dict[str, Any]] = []
        for case in updated_cases:
            execution_steps = case.get('execution_steps', [])
            if not execution_steps:
                continue

            run_steps = self._generate_run_mode_steps(execution_steps)
            if not run_steps:
                continue

            cases_yaml.append({
                'name': case.get('name', case.get('case_id', 'unknown')),
                'steps': run_steps,
            })

        if not cases_yaml:
            logger.debug('No executed cases to write to cases.yaml')
            return

        try:
            # Ensure parent directory exists (defensive; _write_cases_json usually creates it first)
            yaml_path.parent.mkdir(parents=True, exist_ok=True)

            yaml_data: Dict[str, Any] = {'cases': cases_yaml}

            with open(yaml_path, 'w', encoding='utf-8') as f:
                yaml.dump(
                    yaml_data,
                    f,
                    Dumper=_IndentedYamlDumper,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,  # Preserve insertion order: name before steps
                )

            logger.info(f'Generated run-mode YAML: {yaml_path} ({len(cases_yaml)} cases)')

        except Exception as e:
            # YAML is a convenience feature for run-mode copy-paste; don't fail the sync
            logger.warning(
                f'Failed to write cases.yaml to {yaml_path}: {e}. '
                f'JSON sync completed successfully.'
            )

    def _write_cases_json(self, cases: List[Dict]) -> None:
        """Write updated cases to JSON file.

        Args:
            cases: Updated test cases list

        Raises:
            Exception: If file write fails (propagates for caller to handle)
        """
        try:
            # Ensure parent directory exists
            self.cases_json_path.parent.mkdir(parents=True, exist_ok=True)

            # Write with nice formatting
            with open(self.cases_json_path, 'w', encoding='utf-8') as f:
                json.dump(cases, f, ensure_ascii=False, indent=4)

            logger.debug(f'Successfully wrote {len(cases)} cases to {self.cases_json_path}')

        except Exception as e:
            logger.error(
                f'Failed to write cases.json to {self.cases_json_path}: {e}',
                exc_info=True
            )
            raise
