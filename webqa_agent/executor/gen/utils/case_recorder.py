import json
from datetime import datetime
from typing import Dict, List

from webqa_agent.data.gen_structures import (SubTestReport, SubTestResult,
                                             SubTestScreenshot, SubTestStep,
                                             TestStatus)


def get_report_summary(case_data: dict) -> str:
    """Return the preferred user-facing summary from a recorded case dict.

    Prefers ``user_summary`` (concise, business-language) over
    ``final_summary`` (technical/agent-facing).  Returns empty string when
    neither field is populated.
    """
    return case_data.get('user_summary') or case_data.get('final_summary', '')


class CentralCaseRecorder:
    """Independent recorder to store all steps (action/verify/ux_verify) for a
    case.

    This avoids coupling to UITester's internal case store and works even when
    no UI actions occur.
    """

    def __init__(self) -> None:
        self.current_case_data: dict | None = None
        self.current_case_steps: list[dict] = []
        self.step_counter: int = 0

    def start_case(self, case_name: str, case_data: dict | None = None) -> None:
        if self.current_case_data:
            # Auto-finish previous to avoid overlap
            self.finish_case(final_status='interrupted', final_summary='Interrupted by new case start')

        # Extract case_id from case_data if available for top-level access
        case_info = case_data or {}
        case_id = case_info.get('case_id', '')

        self.current_case_data = {
            'name': case_name,
            'case_id': case_id,  # Top-level for CaseJsonSynchronizer lookup
            'start_time': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),  # ISO 8601 format
            'case_info': case_info,
            'steps': [],
            'status': 'running',
            'report': [],
        }
        self.current_case_steps = []
        self.step_counter = 0

    def add_step(self, *, description: str, screenshots: list | None = None, screenshots_paths: list | None = None, model_io: str | dict | None = None,
                 actions: list | None = None, status: str = 'passed', step_type: str = 'action',
                 timestamp: str | None = None) -> None:
        """Add a step to the current case recording.

        Args:
            description: Step description
            screenshots: List of SubTestScreenshot objects or dicts with {"type": "base64", "data": "..."}
            screenshots_paths: List of dicts with {"type": "path", "data": "..."}
            model_io: Model input/output, can be string or dict (will be converted to JSON string)
            actions: List of actions
            status: Step status ("passed", "failed", "warning")
            step_type: Type of step ("action", "verify", "ux_verify")
            timestamp: Timestamp string (ISO 8601), auto-generated if not provided
        """
        if not self.current_case_data:
            # Create a default unnamed case if none started
            self.start_case('Unnamed Case', case_data={})

        self.step_counter += 1

        screenshots = screenshots or []
        actions = actions or []
        timestamp = timestamp or datetime.now().strftime('%Y-%m-%dT%H:%M:%S')  # ISO 8601 format

        # Normalize screenshots to dict format for storage
        normalized_screenshots = []
        normalized_screenshots_paths = []

        # Process paths if provided
        if screenshots_paths:
            for scr in screenshots_paths:
                if isinstance(scr, dict) and 'type' in scr and isinstance(scr.get('data'), str):
                    normalized_screenshots_paths.append(scr)
                else:
                    # Skip invalid screenshot formats
                    continue

        # Process base64 screenshots if provided
        # If paths are provided, we use them as the primary screenshots record to save space
        if normalized_screenshots_paths:
            normalized_screenshots = normalized_screenshots_paths
        elif screenshots:
            for scr in screenshots:
                if isinstance(scr, SubTestScreenshot):
                    normalized_screenshots.append({'type': scr.type, 'data': scr.data, 'label': scr.label})
                elif isinstance(scr, dict) and 'type' in scr and 'data' in scr:
                    normalized_screenshots.append(scr)
                else:
                    # Skip invalid screenshot formats
                    continue

        # Ensure modelIO is a string (align with runner format)
        if isinstance(model_io, str):
            model_io_str = model_io
        else:
            try:
                model_io_str = json.dumps(model_io or '', ensure_ascii=False)
            except Exception:
                model_io_str = str(model_io)

        step_entry = {
            'id': self.step_counter,
            'number': self.step_counter,
            'type': step_type,
            'description': description or '',
            'screenshots': normalized_screenshots,
            'modelIO': model_io_str,
            'actions': actions,
            'status': status,
            'timestamp': timestamp,  # ISO 8601 format for CaseJsonSynchronizer
        }

        self.current_case_steps.append(step_entry)
        self.current_case_data['steps'].append(step_entry)

    def _build_metrics(self) -> Dict[str, int]:
        """Build metrics from recorded steps to keep JSON and aggregation
        aligned."""
        total_steps = len(self.current_case_steps)
        passed = failed = warning = skipped = 0
        total_actions = 0
        for s in self.current_case_steps:
            status = (s.get('status') or '').lower()
            if status in ['failed', 'error', 'failure']:
                failed += 1
            elif status in ['warning', 'warn']:
                warning += 1
            elif status == 'skipped':
                skipped += 1
            else:
                passed += 1
            actions = s.get('actions', [])
            if isinstance(actions, list):
                total_actions += len(actions)
        return {
            'total_steps': total_steps,
            'passed_steps': passed,
            'failed_steps': failed,
            'warning_steps': warning,
            'skipped_steps': skipped,
            'total_actions': total_actions,
        }

    def finish_case(self, final_status: str = 'completed', final_summary: str | None = None, user_summary: str | None = None) -> None:
        if not self.current_case_data:
            return

        # Append summary to report list — prefer user_summary (user-facing)
        # over final_summary (technical/agent-facing)
        report_summary = user_summary or final_summary
        if report_summary:
            self.current_case_data['report'].append({
                'title': 'Summary',
                'issues': report_summary
            })

        end_time = datetime.now()
        end_time_str = end_time.strftime('%Y-%m-%dT%H:%M:%S')  # ISO 8601 format

        # Calculate duration from start_time to end_time
        duration_seconds = 0.0
        start_time_str = self.current_case_data.get('start_time')
        if start_time_str:
            try:
                start_time = datetime.strptime(start_time_str, '%Y-%m-%dT%H:%M:%S')  # ISO 8601 format
                duration_seconds = round((end_time - start_time).total_seconds(), 2)
            except ValueError:
                # If parsing fails, duration remains 0
                pass

        self.current_case_data.update(
            {
                'end_time': end_time_str,
                'duration': duration_seconds,
                'status': final_status,
                'final_summary': final_summary or '',
                'user_summary': user_summary or '',
                'metrics': self._build_metrics()
            }
        )

    def get_case_data(self) -> dict | None:
        return self.current_case_data

    def reset(self) -> None:
        self.current_case_data = None
        self.current_case_steps = []
        self.step_counter = 0

    # --- Conversion helpers to project data structures ---
    def to_subtest_result(self, name: str, language: str = 'zh-CN') -> SubTestResult:
        """Convert recorded case to SubTestResult for report compatibility."""
        steps_models: List[SubTestStep] = []
        metrics = self._build_metrics()
        for s in self.current_case_steps:
            # Convert screenshots
            screenshots_models: List[SubTestScreenshot] = []

            # Get combined screenshots (could be paths or base64)
            all_screenshots = s.get('screenshots', []) or []
            # Also check screenshots_paths for backward compatibility with older recorded files
            legacy_paths = s.get('screenshots_paths', []) or []

            # Combine them for processing, prioritizing screenshots field
            scrs_to_process = all_screenshots if all_screenshots else legacy_paths

            for scr in scrs_to_process:
                if isinstance(scr, dict) and isinstance(scr.get('data'), str) and scr.get('data'):
                    screenshots_models.append(SubTestScreenshot(
                        type=scr.get('type', 'base64'),
                        data=scr['data'],
                        label=scr.get('label')
                    ))

            # Map status
            status_str = (s.get('status') or '').lower()
            status_enum = TestStatus.PASSED
            if status_str in ['failed', 'error', 'failure']:
                status_enum = TestStatus.FAILED
            elif status_str in ['warning', 'warn']:
                status_enum = TestStatus.WARNING

            steps_models.append(
                SubTestStep(
                    id=int(s.get('id', 0) or s.get('number', 0) or len(steps_models) + 1),
                    description=str(s.get('description', '')),
                    screenshots=screenshots_models,
                    modelIO=str(s.get('modelIO', '')),
                    actions=s.get('actions', []),  # Preserve original actions data
                    status=status_enum,
                )
            )

        # Aggregate status
        final_status = TestStatus.PASSED
        for sm in steps_models:
            if sm.status == TestStatus.FAILED:
                final_status = TestStatus.FAILED
                break
            if sm.status == TestStatus.WARNING and final_status != TestStatus.FAILED:
                final_status = TestStatus.WARNING

        reports: List[SubTestReport] = []
        if self.current_case_data:
            report_summary = get_report_summary(self.current_case_data)
            if report_summary:
                reports.append(SubTestReport(title='Summary', issues=report_summary))

        # Extract case_id from case_info if available
        case_info = self.current_case_data.get('case_info', {}) if self.current_case_data else {}
        case_id = case_info.get('case_id', '') if isinstance(case_info, dict) else ''

        return SubTestResult(
            sub_test_id=case_id,
            name=name,
            status=final_status,
            metrics=metrics,
            steps=steps_models,
            report=reports,
            final_summary=self.current_case_data.get('final_summary', '') if self.current_case_data else '',
            user_summary=self.current_case_data.get('user_summary', '') if self.current_case_data else '',
        )
