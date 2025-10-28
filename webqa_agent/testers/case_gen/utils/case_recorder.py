import json
from datetime import datetime
from typing import List, Dict, Any

from webqa_agent.data.test_structures import (
    SubTestResult,
    SubTestStep,
    SubTestScreenshot,
    SubTestReport,
    TestStatus,
)


class CentralCaseRecorder:
    """Independent recorder to store all steps (action/verify/ux_verify) for a case.

    This avoids coupling to UITester's internal case store and works even when no UI actions occur.
    """

    def __init__(self) -> None:
        self.current_case_data: dict | None = None
        self.current_case_steps: list[dict] = []
        self.step_counter: int = 0

    def start_case(self, case_name: str, case_data: dict | None = None):
        if self.current_case_data:
            # Auto-finish previous to avoid overlap
            self.finish_case(final_status="interrupted", final_summary="Interrupted by new case start")

        self.current_case_data = {
            "name": case_name,
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "case_info": case_data or {},
            "steps": [],
            "status": "running",
            "report": [],
        }
        self.current_case_steps = []
        self.step_counter = 0

    def add_step(self, *, description: str, screenshots: list | None = None, model_io: str | dict | None = None,
                 actions: list | None = None, status: str = "passed", step_type: str = "action",
                 end_time: str | None = None):
        """Add a step to the current case recording.
        
        Args:
            description: Step description
            screenshots: List of SubTestScreenshot objects or dicts with {"type": "base64", "data": "..."}
            model_io: Model input/output, can be string or dict (will be converted to JSON string)
            actions: List of actions
            status: Step status ("passed", "failed", "warning")
            step_type: Type of step ("action", "verify", "ux_verify")
            end_time: End time string, auto-generated if not provided
        """
        if not self.current_case_data:
            # Create a default unnamed case if none started
            self.start_case("Unnamed Case", case_data={})

        self.step_counter += 1

        screenshots = screenshots or []
        actions = actions or []
        end_time = end_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Normalize screenshots to dict format for storage
        normalized_screenshots = []
        for scr in screenshots:
            if isinstance(scr, SubTestScreenshot):
                normalized_screenshots.append({"type": scr.type, "data": scr.data})
            elif isinstance(scr, dict) and "type" in scr and "data" in scr:
                normalized_screenshots.append(scr)
            else:
                # Skip invalid screenshot formats
                continue

        # Ensure modelIO is a string (align with runner format)
        if isinstance(model_io, str):
            model_io_str = model_io
        else:
            try:
                model_io_str = json.dumps(model_io or "", ensure_ascii=False)
            except Exception:
                model_io_str = str(model_io)

        step_entry = {
            "id": self.step_counter,
            "number": self.step_counter,
            "type": step_type,
            "description": description or "",
            "screenshots": normalized_screenshots,
            "modelIO": model_io_str,
            "actions": actions,
            "status": status,
            "end_time": end_time,
        }

        self.current_case_steps.append(step_entry)
        self.current_case_data["steps"].append(step_entry)

    def finish_case(self, final_status: str = "completed", final_summary: str | None = None):
        if not self.current_case_data:
            return
        self.current_case_data.update(
            {
                "end_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": final_status,
                "final_summary": final_summary or "",
                "total_steps": len(self.current_case_steps),
            }
        )

    def get_case_data(self) -> dict | None:
        return self.current_case_data

    def reset(self):
        self.current_case_data = None
        self.current_case_steps = []
        self.step_counter = 0

    # --- Conversion helpers to project data structures ---
    def to_subtest_result(self, name: str, language: str = "zh-CN") -> SubTestResult:
        """Convert recorded case to SubTestResult for report compatibility."""
        steps_models: List[SubTestStep] = []
        for s in self.current_case_steps:
            # Convert screenshots
            screenshots_models: List[SubTestScreenshot] = []
            for scr in s.get("screenshots", []) or []:
                if isinstance(scr, dict) and scr.get("type") == "base64" and isinstance(scr.get("data"), str):
                    screenshots_models.append(SubTestScreenshot(type="base64", data=scr["data"]))

            # Map status
            status_str = (s.get("status") or "").lower()
            status_enum = TestStatus.PASSED
            if status_str in ["failed", "error", "failure"]:
                status_enum = TestStatus.FAILED
            elif status_str in ["warning", "warn"]:
                status_enum = TestStatus.WARNING

            steps_models.append(
                SubTestStep(
                    id=int(s.get("id", 0) or s.get("number", 0) or len(steps_models) + 1),
                    description=str(s.get("description", "")),
                    screenshots=screenshots_models,
                    modelIO=str(s.get("modelIO", "")),
                    actions=[],
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
        if self.current_case_data and self.current_case_data.get("final_summary"):
            reports.append(SubTestReport(title="Summary", issues=self.current_case_data.get("final_summary", "")))

        return SubTestResult(
            name=name,
            status=final_status,
            steps=steps_models,
            report=reports,
            final_summary=self.current_case_data.get("final_summary", "") if self.current_case_data else "",
        )


