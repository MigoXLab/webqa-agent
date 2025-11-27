import json
from datetime import datetime


class CentralCaseRecorder:
    """Independent recorder to store all steps (action/verify/ux_verify) for a case.

    This avoids coupling to UITester's internal case store and works even when no UI actions occur.
    """

    def __init__(self) -> None:
        self.current_case_data: dict | None = None
        self.current_case_steps: list[dict] = []
        self.step_counter: int = 0

    def start_case(self, case_name: str, case_data: dict | None = None, planned_steps: list | None = None):
        """Start recording a new test case.

        Args:
            case_name: Name of the test case
            case_data: Optional case metadata
            planned_steps: Optional list of planned steps (from test case definition)
        """
        if self.current_case_data:
            # Auto-finish previous to avoid overlap
            self.finish_case(final_status="interrupted", final_summary="Interrupted by new case start")

        self.current_case_data = {
            "name": case_name,
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "case_info": case_data or {},
            "steps": [],
            "planned_steps": planned_steps or [],  # Store planned steps from test case
            "planned_total_steps": len(planned_steps) if planned_steps else 0,  # Total planned steps
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
            if isinstance(scr, dict) and "type" in scr and "data" in scr:
                normalized_screenshots.append(scr)
            elif hasattr(scr, 'type') and hasattr(scr, 'data'):
                # Duck typing for SubTestScreenshot-like objects
                normalized_screenshots.append({"type": scr.type, "data": scr.data})
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
