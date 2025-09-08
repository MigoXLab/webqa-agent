from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

from webqa_agent.browser.config import DEFAULT_CONFIG

# 侧边栏标题（默认）
CATEGORY_TITLES: Dict[str, Dict[str, str]] = {
    "zh-CN": {
        "function": "功能测试",
        "ux": "UX测试",
        "performance": "性能测试",
        "security": "安全测试",
    },
    "en-US": {
        "function": "Function Test",
        "ux": "UX Test",
        "performance": "Performance Test",
        "security": "Security Test",
    }
}


class TestCategory(str, Enum):
    FUNCTION = "function"
    UX = "ux"
    SECURITY = "security"
    PERFORMANCE = "performance"

# 测试类型
class TestType(str, Enum):
    """Test type enumeration."""

    UNKNOWN = "unknown"
    BASIC_TEST = "basic_test"
    # BUTTON_TEST = "button_test"
    UI_AGENT_LANGGRAPH = "ui_agent_langgraph"
    UX_TEST = "ux_test"
    PERFORMANCE = "performance_test"
    # WEB_BASIC_CHECK = "web_basic_check"
    SECURITY_TEST = "security_test"
    SEO_TEST = "seo_test"

def get_category_for_test_type(test_type: TestType) -> TestCategory:
    """Map TestType to TestCategory."""
    mapping = {
        TestType.UI_AGENT_LANGGRAPH: TestCategory.FUNCTION,
        TestType.BASIC_TEST: TestCategory.FUNCTION,
        # TestType.BUTTON_TEST: TestCategory.FUNCTION,
        # TestType.WEB_BASIC_CHECK: TestCategory.FUNCTION,
        TestType.UX_TEST: TestCategory.UX,
        TestType.PERFORMANCE: TestCategory.PERFORMANCE,
        TestType.SECURITY_TEST: TestCategory.SECURITY,
        TestType.UNKNOWN: TestCategory.FUNCTION,  # Default to function for unknown types
    }
    return mapping.get(test_type, TestCategory.FUNCTION)


# 报告子标题栏
TEST_TYPE_DEFAULT_NAMES: Dict[str, Dict[TestType, str]] = {
    "zh-CN": {
        TestType.UI_AGENT_LANGGRAPH: "智能功能测试",
        TestType.BASIC_TEST: "遍历测试",
        # TestType.BUTTON_TEST: "功能测试",
        # TestType.WEB_BASIC_CHECK: "技术健康度检查",
        TestType.UX_TEST: "用户体验测试",
        TestType.PERFORMANCE: "性能测试",
        TestType.SECURITY_TEST: "安全测试",
    },
    "en-US": {
        TestType.UI_AGENT_LANGGRAPH: "AI Function Test",
        TestType.BASIC_TEST: "Basic Function Test",
        # TestType.BUTTON_TEST: "Traversal Test",
        # TestType.WEB_BASIC_CHECK: "Technical Health Check",
        TestType.UX_TEST: "UX Test",
        TestType.PERFORMANCE: "Performance Test",
        TestType.SECURITY_TEST: "Security Test",
    }
}


def get_default_test_name(test_type: TestType, language: str = "zh-CN") -> str:
    """Return the internal default test name for a given TestType.

    Names are hardcoded and not user-configurable.
    """
    return TEST_TYPE_DEFAULT_NAMES.get(language, {}).get(test_type, test_type.value)


class TestStatus(str, Enum):
    """Test status enumeration."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    WARNING = "warning"
    INCOMPLETED = "incompleted"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TestConfiguration(BaseModel):
    """Test configuration for parallel execution."""

    test_id: Optional[str] = None
    test_type: Optional[TestType] = TestType.BASIC_TEST
    test_name: Optional[str] = ""
    enabled: Optional[bool] = True
    browser_config: Optional[Dict[str, Any]] = DEFAULT_CONFIG
    report_config: Optional[Dict[str, Any]] = {"language": "zh-CN"}
    test_specific_config: Optional[Dict[str, Any]] = {}
    timeout: Optional[int] = 300  # seconds
    retry_count: Optional[int] = 0
    dependencies: Optional[List[str]] = []  # test_ids that must complete first


class TestExecutionContext(BaseModel):
    """Execution context for a single test."""

    test_config: TestConfiguration
    session_id: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: Optional[TestStatus] = TestStatus.PENDING
    error_message: Optional[str] = ""
    retry_attempts: Optional[int] = 0

    def start_execution(self):
        """Mark test as started."""
        self.start_time = datetime.now().replace(microsecond=0)
        self.status = TestStatus.RUNNING

    def complete_execution(self, success: bool = True, error_message: str = ""):
        """Mark test as completed."""
        self.end_time = datetime.now().replace(microsecond=0)
        self.status = TestStatus.PASSED if success else TestStatus.FAILED
        self.error_message = error_message

    @property
    def duration(self) -> Optional[float]:
        """Get execution duration in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


class SubTestScreenshot(BaseModel):
    type: str
    data: str  # base64 encoded image data


class SubTestAction(BaseModel):
    description: Optional[str]
    index: int
    success: bool


class SubTestStep(BaseModel):
    id: int
    screenshots: Optional[List[SubTestScreenshot]] = []
    modelIO: Optional[str] = ""
    actions: Optional[List[SubTestAction]] = []
    description: Optional[str] = ""
    status: Optional[TestStatus] = TestStatus.PASSED
    errors: Optional[str] = ""


class SubTestReport(BaseModel):
    title: str
    issues: str


class SubTestResult(BaseModel):
    """Fine-grained result for a sub test / test case.

    TODO: Update type of `messages`
    """

    name: str
    status: Optional[TestStatus] = TestStatus.PENDING
    metrics: Optional[Dict[str, Any]] = {}
    steps: Optional[List[SubTestStep]] = []  # Detailed execution steps
    messages: Optional[Dict[str, Any]] = {}  # Browser monitoring data
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    final_summary: Optional[str] = ""
    report: Optional[List[SubTestReport]] = []


class TestResult(BaseModel):
    """Isolated test result data."""

    test_id: Optional[str] = ""
    test_type: Optional[TestType] = TestType.UNKNOWN
    test_name: Optional[str] = ""
    module_name: Optional[str] = ""
    status: Optional[TestStatus] = TestStatus.PENDING
    # New field to indicate test category (function/ui/performance)

    category: Optional[TestCategory] = TestCategory.FUNCTION
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration: Optional[float] = None

    # Deprecated free-form dict; keep until callers migrated
    results: Optional[Dict[str, Any]] = {}

    # Structured list replacing the old 'results' field
    sub_tests: Optional[List[SubTestResult]] = []

    # Artifacts
    logs: Optional[List[str]] = []
    traces: Optional[List[str]] = []

    # Error information
    error_message: Optional[str] = ""
    error_details: Optional[Dict[str, Any]] = {}

    # Metrics
    metrics: Optional[Dict[str, Union[int, float, str]]] = {}

    def add_log(self, log_path: str):
        """Add log file to results."""
        self.logs.append(log_path)

    def add_metric(self, key: str, value: Union[int, float, str]):
        """Add metric to results."""
        self.metrics[key] = value

    def add_data(self, key: str, value: Any):
        """Add data to results."""
        self.results[key] = value


class ParallelTestSession(BaseModel):
    """Session data for parallel test execution."""

    session_id: Optional[str] = None
    target_url: Optional[str] = ""
    llm_config: Optional[Dict[str, Any]] = {}

    # Test configurations
    test_configurations: Optional[List[TestConfiguration]] = []

    # Execution tracking
    test_contexts: Optional[Dict[str, TestExecutionContext]] = {}
    test_results: Optional[Dict[str, TestResult]] = {}

    # Session metadata
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    # Aggregated results
    aggregated_results: Optional[Dict[str, Any]] = {}
    llm_summary: Optional[str] = ""
    report_path: Optional[str] = ""
    html_report_path: Optional[str] = ""

    def add_test_configuration(self, test_config: TestConfiguration):
        """Add test configuration to session."""
        self.test_configurations.append(test_config)

        # Create execution context
        context = TestExecutionContext(test_config=test_config, session_id=self.session_id)
        self.test_contexts[test_config.test_id] = context

        # Initialize result
        result = TestResult(
            test_id=test_config.test_id,
            test_type=test_config.test_type,
            test_name=test_config.test_name,
            status=TestStatus.PENDING,
            category=get_category_for_test_type(test_config.test_type),
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

    def get_test_by_type(self, test_type: TestType) -> List[TestConfiguration]:
        """Get all tests of specific type."""
        return [config for config in self.test_configurations if config.test_type == test_type]

    def get_enabled_tests(self) -> List[TestConfiguration]:
        """Get all enabled test configurations."""
        return [config for config in self.test_configurations if config.enabled]

    def get_summary_stats(self) -> Dict[str, Any]:
        """Get session summary statistics"""
        return {
            "session_id": self.session_id,
            "target_url": self.target_url,
            "start_time": self.start_time.replace(microsecond=0).isoformat() if self.start_time else None,
            "end_time": self.end_time.replace(microsecond=0).isoformat() if self.end_time else None,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert session to dictionary with grouped test results."""
        grouped_results: Dict[str, Dict[str, Any]] = {}

        if self.test_configurations and len(self.test_configurations) > 0:
            language = self.test_configurations[0].report_config.get("language", "zh-CN")

        for cat in TestCategory:
            key = f"{cat.value}_test_results"
            grouped_results[key] = {"title": CATEGORY_TITLES[language].get(cat.value, cat.name), "items": []}

        for result in self.test_results.values():
            key = f"{result.category.value}_test_results"
            if key not in grouped_results:
                grouped_results[key] = {
                    "title": CATEGORY_TITLES[language].get(result.category.value, result.category.name.title()),
                    "items": [],
                }
            grouped_results[key]["items"].append(result.dict())

        return {
            "session_info": self.get_summary_stats(),
            "aggregated_results": self.aggregated_results,
            "test_results": grouped_results,
            "llm_summary": self.llm_summary,
        }
