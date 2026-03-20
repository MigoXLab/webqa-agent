from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

from webqa_agent.browser.config import DEFAULT_CONFIG

# Category titles moved to utils.i18n.get_category_title()
# Use: from webqa_agent.utils.i18n import get_category_title


class TestCategory(str, Enum):
    FUNCTION = 'function'
    UX = 'ux'
    SECURITY = 'security'
    PERFORMANCE = 'performance'


class TestStatus(str, Enum):
    """Test status enumeration."""

    PENDING = 'pending'
    RUNNING = 'running'
    PASSED = 'passed'
    WARNING = 'warning'
    INCOMPLETED = 'incompleted'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


class StepSeverity(str, Enum):
    """Step outcome severity classification for verdict engine.

    Used by _compute_verdict() to determine case-level status from individual
    step results. Ordered from most severe to least.
    """

    CRITICAL = 'critical'    # Unrecoverable: PAGE_CRASHED, PERMISSION_DENIED, unsupported page
    HARD_FAIL = 'hard_fail'  # Product defect: assertion failure, retry exhausted, step exception
    SOFT_FAIL = 'soft_fail'  # Infrastructure issue: recovery disabled, unknown strategy, LLM error
    SKIPPED = 'skipped'      # Intentional skip: recovery skip strategy, redundant step
    WARNING = 'warning'      # Non-blocking issue
    PASSED = 'passed'        # Success


@dataclass
class StepOutcome:
    """Structured result for a single step execution.

    Replaces the raw ``failed_steps.append(i+1)`` pattern with rich
    diagnostic data that the verdict engine can reason about.
    """

    step_index: int
    severity: StepSeverity
    description: str = ''
    recovery_strategy: Optional[str] = None
    recovery_reason: Optional[str] = None


# ==============================================================
# Test Config & Execution Context Structures
# ==============================================================


class TestConfiguration(BaseModel):
    """Test configuration for parallel execution."""

    test_id: Optional[str] = None
    test_name: Optional[str] = ''
    enabled: Optional[bool] = True
    browser_config: Optional[Dict[str, Any]] = DEFAULT_CONFIG
    report_config: Optional[Dict[str, Any]] = {'language': 'zh-CN'}
    test_specific_config: Optional[Dict[str, Any]] = {}


# ============================================================================
# Sub Test Structures
# ============================================================================

class SubTestScreenshot(BaseModel):
    type: str
    data: str  # base64 encoded image data or relative path
    label: Optional[str] = None


class SubTestAction(BaseModel):
    description: Optional[str]
    index: int
    success: bool


class SubTestStep(BaseModel):
    id: int
    screenshots: Optional[List[SubTestScreenshot]] = []
    modelIO: Optional[str] = ''
    actions: Optional[List[SubTestAction]] = []
    description: Optional[str] = ''
    status: Optional[TestStatus] = TestStatus.PASSED
    errors: Optional[str] = ''
    error_details: Optional[Dict[str, Any]] = None  # Detailed error context from ActionHandler


class SubTestReport(BaseModel):
    title: str
    issues: str


class SubTestResult(BaseModel):
    """Fine-grained result for a sub test / test case."""

    sub_test_id: Optional[str] = ''  # 对应 case 的 case_id
    name: str
    status: Optional[TestStatus] = TestStatus.PENDING
    metrics: Optional[Dict[str, Any]] = {}
    steps: Optional[List[SubTestStep]] = []  # Detailed execution steps
    messages: Optional[Dict[str, Any]] = {}  # Error messages and diagnostic data
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    final_summary: Optional[str] = ''
    user_summary: Optional[str] = ''  # User-facing concise summary in business language
    report: Optional[List[SubTestReport]] = []


# ==============================================================
# Test Result Structures
# ==============================================================

class TestResult(BaseModel):
    """Isolated test result data."""

    test_id: Optional[str] = ''
    test_name: Optional[str] = ''
    module_name: Optional[str] = ''
    status: Optional[TestStatus] = TestStatus.PENDING
    category: Optional[TestCategory] = TestCategory.FUNCTION
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration: Optional[float] = None

    # Structured list for sub-test results
    sub_tests: Optional[List[SubTestResult]] = []

    # Artifacts
    logs: Optional[List[str]] = []
    traces: Optional[List[str]] = []

    # Error information
    error_message: Optional[str] = ''
    error_details: Optional[Dict[str, Any]] = {}

    # Metrics
    metrics: Optional[Dict[str, Union[int, float, str]]] = {}

    def add_log(self, log_path: str):
        """Add log file to results."""
        self.logs.append(log_path)

    def add_metric(self, key: str, value: Union[int, float, str]):
        """Add metric to results."""
        self.metrics[key] = value

# ==============================================================
# Parallel Test Session Structures
# ==============================================================


class ParallelTestSession(BaseModel):
    """Session data for parallel test execution."""

    session_id: Optional[str] = None
    target_url: Optional[str] = ''
    llm_config: Optional[Dict[str, Any]] = {}

    # Test configurations
    test_configurations: Optional[List[TestConfiguration]] = []

    # Execution tracking
    test_results: Optional[Dict[str, TestResult]] = {}

    # Session metadata
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    # Aggregated results
    aggregated_results: Optional[Dict[str, Any]] = {}
    llm_summary: Optional[str] = ''
    report_path: Optional[str] = ''
    html_report_path: Optional[str] = ''

    def add_test_configuration(self, test_config: TestConfiguration):
        """Add test configuration to session."""
        self.test_configurations.append(test_config)

        # Initialize result with FUNCTION category (Run mode default)
        result = TestResult(
            test_id=test_config.test_id,
            test_name=test_config.test_name,
            status=TestStatus.PENDING,
            category=TestCategory.FUNCTION,
        )
        self.test_results[test_config.test_id] = result

    def start_session(self):
        """Start the test session."""
        self.start_time = datetime.now()

    def complete_session(self):
        """Complete the test session."""
        self.end_time = datetime.now()

    def update_test_result(self, test_id: str, result: TestResult):
        """Update test result."""
        self.test_results[test_id] = result

    def get_summary_stats(self) -> Dict[str, Any]:
        """Get session summary statistics."""
        return {
            'session_id': self.session_id,
            'target_url': self.target_url,
            'start_time': self.start_time.replace(microsecond=0).isoformat() if self.start_time else None,
            'end_time': self.end_time.replace(microsecond=0).isoformat() if self.end_time else None,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert session to dictionary with grouped test results."""
        from webqa_agent.utils.i18n import get_category_title

        grouped_results: Dict[str, Dict[str, Any]] = {}

        # Determine language from configurations or use default
        language = 'zh-CN'
        if self.test_configurations and len(self.test_configurations) > 0:
            language = self.test_configurations[0].report_config.get('language', 'zh-CN')

        # Initialize all categories with localized titles
        for cat in TestCategory:
            key = f'{cat.value}_test_results'
            grouped_results[key] = {
                'title': get_category_title(cat.value, language),
                'items': []
            }

        # Group results by category
        for result in self.test_results.values():
            key = f'{result.category.value}_test_results'
            if key not in grouped_results:
                grouped_results[key] = {
                    'title': get_category_title(result.category.value, language),
                    'items': [],
                }
            grouped_results[key]['items'].append(result.model_dump())

        return {
            'session_info': self.get_summary_stats(),
            'aggregated_results': self.aggregated_results,
            'test_results': grouped_results,
            'llm_summary': self.llm_summary,
        }
