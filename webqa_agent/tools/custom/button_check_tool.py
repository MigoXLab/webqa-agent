"""Page button traversal testing tool for WebQA Agent.

This tool performs comprehensive clickable element testing by:
- Extracting all clickable elements from the current page
- Clicking each element and capturing screenshots
- Validating click results and tracking failures
- Generating detailed test reports

Key Features:
- Reuses PageButtonTest for consistency with existing test infrastructure
- Tracks click history and validates business success
- Records screenshots for each click action
- Returns comprehensive test results with pass/fail statistics

Usage in test plans:
    LLM autonomously chooses when to invoke this tool based on:
    - Test objectives mentioning comprehensive UI testing
    - Need to verify all clickable elements work correctly
    - Regression testing scenarios

Example test step:
    {"action": "traverse_clickable_elements", "params": {}}
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Type

from pydantic import BaseModel, Field

from webqa_agent.data.gen_structures import TestStatus
from webqa_agent.tools.base import WebQABaseTool, WebQAToolMetadata
from webqa_agent.tools.core.web_checks import PageButtonTest
from webqa_agent.tools.registry import register_tool

logger = logging.getLogger(__name__)

# HTML tag name → human-readable label (zh-CN, en-US)
_TAG_LABELS: Dict[str, tuple] = {
    'a': ('链接', 'Link'),
    'button': ('按钮', 'Button'),
    'input': ('输入框', 'Input'),
    'textarea': ('文本输入框', 'Text Input'),
    'select': ('下拉选择', 'Dropdown'),
    'div': ('区块', 'Block'),
    'span': ('文本区域', 'Text Span'),
    'img': ('图片', 'Image'),
    'svg': ('图标', 'Icon'),
    'label': ('标签', 'Label'),
    'li': ('列表项', 'List Item'),
    'td': ('表格单元', 'Table Cell'),
    'tr': ('表格行', 'Table Row'),
    'th': ('表头', 'Table Header'),
    'form': ('表单', 'Form'),
    'nav': ('导航', 'Navigation'),
    'header': ('页头', 'Header'),
    'footer': ('页脚', 'Footer'),
}

# Common browser error codes → human-readable translations (zh-CN, en-US)
_ERROR_TRANSLATIONS: Dict[str, tuple] = {
    'net::err_failed': ('网络资源加载失败', 'Network resource loading failed'),
    'net::err_connection_refused': ('服务器拒绝连接', 'Server connection refused'),
    'net::err_name_not_resolved': ('域名解析失败', 'DNS resolution failed'),
    'net::err_connection_reset': ('连接被重置', 'Connection reset'),
    'net::err_timed_out': ('连接超时', 'Connection timed out'),
    'net::err_aborted': ('请求被中止', 'Request aborted'),
    'net::err_cert': ('证书错误', 'Certificate error'),
    'net::err_ssl': ('SSL 错误', 'SSL error'),
    '404': ('页面不存在(404)', 'Page not found (404)'),
    '500': ('服务器内部错误(500)', 'Internal server error (500)'),
    '502': ('网关错误(502)', 'Bad gateway (502)'),
    '503': ('服务不可用(503)', 'Service unavailable (503)'),
}


def _humanize_element(description: str, element_id: int, language: str = 'zh-CN') -> str:
    """Convert CSS selector description to a human-readable label.

    Args:
        description: Step description like "Click Element: textarea.ant-input.css-xxx"
        element_id: Numeric element ID
        language: 'zh-CN' or 'en-US'

    Returns:
        Human-readable string like "文本输入框(#18)" or "Text Input (#18)"
    """
    lang_idx = 0 if language == 'zh-CN' else 1

    # Extract the part after ':'  (e.g. "textarea.ant-input.css-xxx")
    raw = description
    if ':' in raw:
        raw = raw.split(':', 1)[-1].strip()

    # Get the tag name (first segment before '.' or '#' or '[')
    tag = raw
    for sep in ('.', '#', '[', ' '):
        tag = tag.split(sep)[0]
    tag = tag.strip().lower()

    label = _TAG_LABELS.get(tag, (tag, tag))[lang_idx] if tag else str(element_id)
    return f'{label}(#{element_id})'


def _humanize_error(error_text: str, language: str = 'zh-CN') -> str:
    """Translate low-level error messages to human-readable descriptions.

    Args:
        error_text: Raw error string (e.g. "browser_error: ... net::ERR_FAILED ...")
        language: 'zh-CN' or 'en-US'

    Returns:
        Human-readable error description
    """
    lang_idx = 0 if language == 'zh-CN' else 1
    text_lower = error_text.lower()

    # Try to match known error patterns
    for pattern, labels in _ERROR_TRANSLATIONS.items():
        if pattern in text_lower:
            return labels[lang_idx]

    # Fallback: simplify common prefixes
    if 'console error' in text_lower:
        return '控制台报错' if language == 'zh-CN' else 'Console error'
    if 'network failure' in text_lower or 'network error' in text_lower:
        return '网络请求失败' if language == 'zh-CN' else 'Network request failed'
    if 'element_not_found' in text_lower:
        return '元素未找到' if language == 'zh-CN' else 'Element not found'
    if 'element_not_clickable' in text_lower:
        return '元素无法点击' if language == 'zh-CN' else 'Element not clickable'
    if 'element_obscured' in text_lower:
        return '元素被遮挡' if language == 'zh-CN' else 'Element obscured'
    if 'scroll_timeout' in text_lower:
        return '滚动超时' if language == 'zh-CN' else 'Scroll timeout'
    if 'playwright_error' in text_lower:
        return '浏览器操作异常' if language == 'zh-CN' else 'Browser operation error'

    # Last resort: truncate raw text
    short = error_text[:80]
    if len(error_text) > 80:
        short += '...'
    return short


def _build_human_readable_summary(
    total_elements: int,
    passed_count: int,
    failed_count: int,
    failed_steps: List,
    language: str = 'zh-CN',
) -> str:
    """Build a structured, human-readable traversal test summary.

    Args:
        total_elements: Total clickable elements tested
        passed_count: Number of elements that passed
        failed_count: Number of elements that failed
        failed_steps: List of failed SubTestStep objects
        language: 'zh-CN' or 'en-US'

    Returns:
        Formatted summary string
    """
    if language == 'zh-CN':
        header = (
            f'遍历测试完成：共检测 {total_elements} 个交互元素，'
            f'{passed_count} 个正常，{failed_count} 个发现问题。'
        )
        if failed_count == 0:
            return header

        lines = [header, '发现的问题：']
        for i, step in enumerate(failed_steps[:10], 1):
            elem_label = _humanize_element(
                step.description or '', step.id, language
            )
            error_desc = _humanize_error(
                getattr(step, 'errors', '') or '', language
            )
            lines.append(f'{i}. {elem_label}：{error_desc}')
        if failed_count > 10:
            lines.append(f'...及其他 {failed_count - 10} 个问题')
        return '\n'.join(lines)
    else:
        header = (
            f'Traversal test completed: {total_elements} elements tested, '
            f'{passed_count} passed, {failed_count} issues found.'
        )
        if failed_count == 0:
            return header

        lines = [header, 'Issues:']
        for i, step in enumerate(failed_steps[:10], 1):
            elem_label = _humanize_element(
                step.description or '', step.id, language
            )
            error_desc = _humanize_error(
                getattr(step, 'errors', '') or '', language
            )
            lines.append(f'{i}. {elem_label}: {error_desc}')
        if failed_count > 10:
            lines.append(f'...and {failed_count - 10} more issues')
        return '\n'.join(lines)


class ButtonCheckToolSchema(BaseModel):
    """Schema for button check tool arguments.

    This tool takes no parameters. The LLM should call it with empty
    parameters.
    """

    pass  # No parameters needed - tests all clickable elements automatically


@register_tool  # Automatically registers to global registry on import
class ButtonCheckTool(WebQABaseTool):
    """Tool for comprehensive clickable element testing.

    This action-category tool traverses all clickable elements on a page,
    clicks each one, and validates the results. It provides comprehensive
    coverage for UI interaction testing.

    Architecture:
    - Category: 'custom' - Custom user-defined tool
    - Trigger: Explicit step_type for LLM planning prompt inclusion
    - Browser Access: Requires ui_tester_instance for page interaction
    - Test Implementation: Reuses PageButtonTest for consistency

    Performance:
    - Processes up to 50 clickable elements by default
    - Captures screenshots for each click
    - Brief pause between clicks for stability
    """

    name: str = 'traverse_clickable_elements'
    description: str = (
        'Performs comprehensive testing of all clickable elements on the page. '
        'Clicks each element, captures screenshots, and validates results. '
        'IMPORTANT: This tool takes NO parameters. Call it with empty arguments {}. '
        'NOTE: Console and network errors reported by this tool are EXPECTED discoveries '
        'and should NOT trigger a REPLAN. Simply document the findings and CONTINUE.'
    )
    args_schema: Type[BaseModel] = ButtonCheckToolSchema

    # Requires browser access via ui_tester_instance
    ui_tester_instance: Any = Field(
        ...,
        description='UITester instance for accessing browser page and context'
    )

    # Requires case_recorder for step recording
    case_recorder: Any | None = Field(
        default=None,
        description='Optional CentralCaseRecorder to record test steps'
    )

    # Optional llm_config for report configuration
    llm_config: Dict = Field(
        default_factory=dict,
        description='LLM configuration including report settings'
    )

    @classmethod
    def get_metadata(cls) -> WebQAToolMetadata:
        """Return tool metadata for registration and prompt generation."""
        return WebQAToolMetadata(
            name='traverse_clickable_elements',
            category='custom',  # Custom tool - marks as user-defined
            step_type='traverse_clickable_elements',  # Explicit step type for planning
            step_timeout=600.0,  # 10 min — clicks every element sequentially
            recovery_disabled=True,  # Batch tool: FAILURE = diagnostic finding, not a transient error
            description_short='Comprehensive testing of all clickable elements',
            description_long=(
                'Performs exhaustive testing of all clickable elements on the current page. '
                'This tool takes NO PARAMETERS. '
                'For each element:\n'
                '  - Clicks the element and waits for response\n'
                '  - Captures screenshots after click\n'
                '  - Validates business success (no errors, navigation successful)\n'
                '  - Returns to original page for next test\n\n'
                'Features:\n'
                '  - Automatic element extraction using DOM analysis\n'
                '  - Screenshot capture for visual validation\n'
                '  - Business logic success validation\n'
                '  - Detailed pass/fail statistics\n\n'
                'IMPORTANT NOTE FOR AGENT:\n'
                '  - Any console errors or network errors found by this tool are VALID BUGS on the page.\n'
                '  - They represent successfully discovered issues, NOT testing framework failures.\n'
                '  - When issues are found, the tool returns a [FAILURE] with a human-readable summary.\n'
                '  - DO NOT trigger a REPLAN for these failures — they are expected test findings.\n'
                '  - If the tool itself crashes (system error), it returns [WARNING] instead.\n\n'
                'Returns:\n'
                '  - Total elements tested\n'
                '  - Number of failures\n'
                '  - Human-readable error descriptions for failed elements'
            ),
            examples=[
                '{{"action": "traverse_clickable_elements", "params": {{}}}}',
            ],
            use_when=[
                # Comprehensive UI testing scenarios
                'Performing comprehensive UI regression testing',
                'Validating all interactive elements work correctly',
                'Testing navigation menu and dropdown functionality',
                'Verifying form submission buttons and links',
                'During smoke testing to catch broken UI interactions',

                # Specific testing needs
                'After major UI refactoring to ensure nothing broke',
                'Testing single-page applications (SPAs) with dynamic routing',
                'Validating e-commerce product pages with multiple CTAs',
                'Testing dashboard interfaces with many interactive widgets',
                'During accessibility audits to verify all clickable elements function',

                # Quality assurance workflows
                'As part of automated test suite for continuous integration',
                'Before major releases to catch last-minute UI issues',
                'When manual testing is too time-consuming due to many elements',
            ],
            dont_use_when=[
                # Performance and safety considerations
                'On pages with hundreds of clickable elements (use sampling instead)',
                'During performance testing (adds significant overhead)',
                'Too frequently (execution time: 10-30 seconds depending on element count)',
                'On every page navigation (use once per page for regression testing)',
                'On production environments without proper sandboxing',
                'When testing destructive actions (delete, payment submission)',

                # Inappropriate scenarios
                'After every single navigation (too frequent, use targeted testing)',
                'On pages with infinite scroll or dynamically loaded elements',
                'When only specific elements need testing (use targeted click instead)',
                'On login/authentication forms (may trigger rate limiting)',
            ],
            priority=35,  # Lower than link detection (45) but higher than experimental tools
            dependencies=[]  # No external dependencies, uses built-in modules
        )

    @classmethod
    def get_required_params(cls) -> Dict[str, str]:
        """Specify required initialization parameters.

        This tool requires:
        - ui_tester_instance: For browser access
        - case_recorder: For recording test steps to test report
        - llm_config: For report configuration
        """
        return {
            'ui_tester_instance': 'ui_tester_instance',
            'case_recorder': 'case_recorder',
            'llm_config': 'llm_config',
        }

    def _get_report_language(self) -> str:
        """Get the report language from llm_config."""
        report_config = self.llm_config.get('report_config', {})
        return report_config.get('language', 'en-US')

    async def _arun(self, **kwargs) -> str:
        """Execute comprehensive button testing.

        Workflow:
        1. Get current page and URL
        2. Extract all clickable elements
        3. Run PageButtonTest on extracted elements
        4. Analyze results and format response
        5. Update context with test results

        Returns:
            Formatted response with test results and statistics
        """
        # Log a warning if the LLM provided unexpected kwargs, but continue execution
        if kwargs:
            logger.warning(f'Button Test Tool: Ignoring unexpected parameters provided by LLM: {kwargs}')

        try:
            # Step 1: Get current page
            page = await self.ui_tester_instance.get_current_page()
            if not page:
                return self.format_critical_error(
                    'PAGE_CRASHED',
                    'Cannot get current page for button traversal testing'
                )

            url = page.url
            logger.info(f'Button Test Tool: Starting traversal test on {url}')

            # Step 2: Extract clickable elements using DeepCrawler
            from webqa_agent.crawler.deep_crawler import DeepCrawler

            # Use DeepCrawler to extract all interactive elements
            dp = DeepCrawler(page)
            crawl_result = await dp.crawl(highlight=False, viewport_only=False)

            # Get clickable elements as dictionary (format expected by PageButtonTest)
            clickable_elements = crawl_result.raw_dict()

            if not clickable_elements:
                # No clickable elements found - record as success (using safe_record_step helper)
                self.safe_record_step(
                    description='Traverse clickable elements (no elements found)',
                    model_io_data={'message': 'No clickable elements found on page'},
                    status='passed',
                )

                return self.format_success(
                    'No clickable elements found on page',
                    page_state=f'URL: {url}'
                )

            logger.info(f'Button Test Tool: Found {len(clickable_elements)} clickable elements')

            # Step 3: Run PageButtonTest
            report_config = self.llm_config.get('report_config', {'language': 'en-US'})
            button_test = PageButtonTest(report_config=report_config)

            result = await button_test.run(
                url=url,
                page=page,
                clickable_elements=clickable_elements
            )

            # Step 4: Analyze results
            total_elements = len(clickable_elements)
            failed_count = sum(
                1 for step in result.steps
                if step.status == TestStatus.FAILED
            )
            passed_count = total_elements - failed_count

            logger.info(
                f'Button Test Tool: Completed. '
                f'Total: {total_elements}, Passed: {passed_count}, Failed: {failed_count}'
            )

            # Step 5: Update context for downstream tools
            self.update_action_context(
                self.ui_tester_instance,
                {
                    'description': f'Traverse clickable elements (tested {total_elements})',
                    'action_type': 'ButtonTraversal',
                    'status': 'success' if result.status == TestStatus.PASSED else 'failed',
                    'result': {
                        'message': (
                            f'Tested {total_elements} clickable elements: '
                            f'{passed_count} passed, {failed_count} failed'
                        ),
                        'total_elements': total_elements,
                        'passed_count': passed_count,
                        'failed_count': failed_count,
                        'test_status': result.status.value,
                    },
                    'timestamp': datetime.now().isoformat(),
                }
            )

            # Step 6: Record to case_recorder (using safe_record_step helper)
            language = self._get_report_language()
            failed_steps = [
                step for step in result.steps
                if step.status == TestStatus.FAILED
            ]

            # Extract all screenshots from the test steps
            all_screenshots = []
            for step in result.steps:
                if hasattr(step, 'screenshots') and step.screenshots:
                    all_screenshots.extend(step.screenshots)

            # Build human-readable summary
            readable_summary = _build_human_readable_summary(
                total_elements, passed_count, failed_count,
                failed_steps, language
            )

            self.safe_record_step(
                description=f'Traverse clickable elements (tested {total_elements})',
                model_io_data={
                    'total_elements': total_elements,
                    'passed': passed_count,
                    'failed': failed_count,
                    'summary': readable_summary,
                },
                status='passed' if result.status == TestStatus.PASSED else 'failed',
                screenshots=all_screenshots,
            )

            # Step 7: Format response for LLM
            if result.status == TestStatus.PASSED:
                return self.format_success(
                    f'All {total_elements} clickable elements passed testing',
                    page_state=f'Tested buttons/links on {url}'
                )
            else:
                # Issues found (page bugs) — return as FAILURE
                # These are real bugs discovered by the test
                return self.format_failure(readable_summary)

        except Exception as e:
            # Record failed step (using safe_record_step helper)
            self.safe_record_step(
                description='Traverse clickable elements (failed)',
                model_io_data={
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                status='warning',
            )

            # Update context to indicate system error
            self.update_action_context(
                self.ui_tester_instance,
                {
                    'description': 'Traverse clickable elements (system error)',
                    'action_type': 'ButtonTraversal',
                    'status': 'warning',
                    'result': {
                        'message': f'Button traversal system error: {str(e)}',
                        'error_details': {
                            'error_type': type(e).__name__,
                        }
                    },
                    'timestamp': datetime.now().isoformat(),
                }
            )

            logger.error(f'Button Test Tool: Unexpected error: {e}', exc_info=True)
            return self.format_warning(
                f'Button traversal tool encountered a system error: {str(e)}'
            )
