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
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Type

from pydantic import BaseModel, Field

from webqa_agent.data.gen_structures import TestStatus
from webqa_agent.tools.base import WebQABaseTool, WebQAToolMetadata
from webqa_agent.tools.core.web_checks import (TAG_LABELS, PageButtonTest,
                                               get_element_semantic_label)
from webqa_agent.tools.registry import register_tool

logger = logging.getLogger(__name__)


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


def _humanize_element(
    step,
    clickable_elements: dict | None = None,
    language: str = 'zh-CN',
    include_id: bool = True,
) -> str:
    """Convert a SubTestStep to a human-readable element label.

    Args:
        step: SubTestStep with .id (numeric element ID) and .description.
        clickable_elements: Optional dict for semantic label lookup.
        language: 'zh-CN' or 'en-US'
        include_id: When ``False`` and a semantic label exists, the internal
            element ID is omitted for cleaner user-facing output.
            When no semantic label is available, the ID is always shown
            as it is the only distinguishing identifier.

    Returns:
        ``Link[文心](#9)`` (include_id=True) or ``Link[文心]`` (False).
    """
    lang_idx = 0 if language == 'zh-CN' else 1
    element_id: int = step.id
    description: str = step.description or ''

    raw = description
    if ':' in raw:
        raw = raw.split(':', 1)[-1].strip()

    tag = raw
    for sep in ('.', '#', '[', ' '):
        tag = tag.split(sep)[0]
    tag = tag.strip().lower()

    tag_label = TAG_LABELS.get(tag, (tag, tag))[lang_idx] if tag else str(element_id)

    semantic_label = ''
    if clickable_elements is not None:
        elem = clickable_elements.get(str(element_id))
        if elem:
            semantic_label = get_element_semantic_label(elem)

    if semantic_label:
        if include_id:
            return f'{tag_label}[{semantic_label}](#{element_id})'
        return f'{tag_label}[{semantic_label}]'
    return f'{tag_label}(#{element_id})'


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

    return error_text


# ---------------------------------------------------------------------------
# Element priority filter
# ---------------------------------------------------------------------------

# Tier 1 – native interactive HTML elements; always tested.
_TIER1_TAGS: frozenset[str] = frozenset({'button', 'a', 'input', 'select', 'textarea'})

# Tier 2 – structural/container tags tested at lower priority.
# Those with an interactive aria role take precedence over those without.
_TIER2_TAGS: frozenset[str] = frozenset({'div', 'span', 'form', 'li', 'td'})

# ARIA roles that indicate interactive behaviour regardless of tag name.
# Sourced from WCAG 4.1.2 and WAI-ARIA Practices.
_INTERACTIVE_ROLES: frozenset[str] = frozenset({
    'button', 'link', 'menuitem', 'menuitemcheckbox', 'menuitemradio',
    'tab', 'option', 'checkbox', 'radio', 'switch',
    'treeitem', 'combobox', 'textbox', 'searchbox',
    'slider', 'spinbutton',
})

# Default element cap – matches the class-level docstring guarantee.
_DEFAULT_MAX_ELEMENTS: int = 50


def _filter_clickable_elements(
    raw_elements: Dict[str, Any],
    max_elements: int = _DEFAULT_MAX_ELEMENTS,
) -> Dict[str, Any]:
    """Filter crawl elements by priority and cap at *max_elements*.

    Priority order:
      Tier 1 – native interactive tags (button, a, input, select, textarea)
      Tier 2a – any tag with an interactive aria role
      Tier 2b – structural tags (div/span/form/li/td) without an explicit role

    Excluded unconditionally:
      - ``aria-hidden="true"``   (decorative, invisible to assistive tech)
      - ``input[type=hidden]``   (never user-facing)
      - Tags outside Tier 1 / Tier 2 with no interactive role
        (img, svg, nav, header, footer, …)

    Args:
        raw_elements: Raw dict from ``DeepCrawler.crawl().raw_dict()``.
        max_elements: Hard cap on the number of elements returned.

    Returns:
        Filtered, priority-ordered dict with at most *max_elements* entries.
    """
    tier1: Dict[str, Any] = {}
    tier2_role: Dict[str, Any] = {}
    tier2_tag: Dict[str, Any] = {}

    for elem_id, elem in raw_elements.items():
        tag = (elem.get('tagName') or '').lower()
        raw_attrs = elem.get('attributes') or {}
        # JS returns attributes as a list of {name, value} objects; normalise
        # to a plain dict so all downstream .get() calls work uniformly.
        attrs: Dict[str, Any]
        if isinstance(raw_attrs, list):
            # HTML boolean attributes (e.g. disabled, readonly) may lack a
            # 'value' key in the serialised form; default to empty string.
            attrs = {
                a['name']: a.get('value', '')
                for a in raw_attrs
                if isinstance(a, dict) and 'name' in a
            }
        else:
            attrs = raw_attrs

        # Unconditional exclusions
        if attrs.get('aria-hidden') == 'true':
            continue
        if tag == 'input' and (attrs.get('type') or '').lower() == 'hidden':
            continue

        role = (attrs.get('role') or '').lower()

        if tag in _TIER1_TAGS:
            tier1[elem_id] = elem
        elif role in _INTERACTIVE_ROLES:
            tier2_role[elem_id] = elem
        elif tag in _TIER2_TAGS:
            tier2_tag[elem_id] = elem
        # All other tags (img, svg, nav, header, footer, …) → ignored

    # Merge in priority order and apply cap
    combined: Dict[str, Any] = {}
    for source in (tier1, tier2_role, tier2_tag):
        for k, v in source.items():
            if len(combined) >= max_elements:
                return combined
            combined[k] = v
    return combined


def _build_human_readable_summary(
    total_elements: int,
    passed_count: int,
    failed_count: int,
    failed_steps: List,
    language: str = 'zh-CN',
    clickable_elements: dict | None = None,
) -> str:
    """Build a structured, human-readable traversal test summary.

    Args:
        total_elements: Total clickable elements tested
        passed_count: Number of elements that passed
        failed_count: Number of elements that failed
        failed_steps: List of failed SubTestStep objects
        language: 'zh-CN' or 'en-US'
        clickable_elements: Optional element dict from DeepCrawler, used to
            enrich element labels with semantic text (aria-label, innerText, …).

    Returns:
        Formatted summary string
    """
    # Build header
    if language == 'zh-CN':
        header = (
            f'遍历测试完成：共检测 {total_elements} 个交互元素，'
            f'{passed_count} 个正常，{failed_count} 个发现问题。'
        )
    else:
        header = (
            f'Traversal test completed: {total_elements} elements tested, '
            f'{passed_count} passed, {failed_count} issues found.'
        )

    if failed_count == 0:
        return header

    # Group failures by error type for readability
    error_groups: Dict[str, List[str]] = {}
    for step in failed_steps:
        error_desc = _humanize_error(
            getattr(step, 'errors', '') or '', language,
        )
        elem_label = _humanize_element(
            step, clickable_elements, language, include_id=False,
        )
        error_groups.setdefault(error_desc, []).append(elem_label)

    # Per-group element cap: show all ≤ 10, truncate above
    _MAX_PER_GROUP = 10

    lines = [header]
    lines.append('发现的问题：' if language == 'zh-CN' else 'Issues:')
    for error_desc, elements in error_groups.items():
        count = len(elements)
        if language == 'zh-CN':
            lines.append(f'● {error_desc} ({count}个):')
        else:
            lines.append(f'● {error_desc} ({count}):')
        shown = elements[:_MAX_PER_GROUP]
        for elem_label in shown:
            lines.append(f'  - {elem_label}')
        overflow = count - _MAX_PER_GROUP
        if overflow > 0:
            if language == 'zh-CN':
                lines.append(f'  ...及其他 {overflow} 个元素')
            else:
                lines.append(f'  ...and {overflow} more')
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
            step_timeout=1200.0,  # 20 min — clicks every element sequentially
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

            # Get raw clickable elements from DeepCrawler
            raw_elements = crawl_result.raw_dict()

            if not raw_elements:
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

            # Step 2.5: Apply priority filter (Tier1 native tags → interactive role → Tier2 tag)
            # and cap at _DEFAULT_MAX_ELEMENTS.  Decorative / structural elements are excluded.
            clickable_elements = _filter_clickable_elements(raw_elements)
            logger.info(
                f'Button Test Tool: Found {len(raw_elements)} raw elements → '
                f'{len(clickable_elements)} after priority filter (cap={_DEFAULT_MAX_ELEMENTS})'
            )

            if not clickable_elements:
                self.safe_record_step(
                    description='Traverse clickable elements (all filtered out)',
                    model_io_data={
                        'raw_elements_count': len(raw_elements),
                        'message': 'All elements were decorative/structural; no interactive elements to test',
                    },
                    status='passed',
                )
                return self.format_success(
                    f'No testable interactive elements found after priority filter '
                    f'({len(raw_elements)} raw elements were decorative/structural)',
                    page_state=f'URL: {url}'
                )

            # Step 3: Run PageButtonTest
            report_config = self.llm_config.get('report_config', {'language': 'en-US'})
            button_test = PageButtonTest(report_config=report_config)
            language = self._get_report_language()

            try:
                result = await button_test.run(
                    url=url,
                    page=page,
                    clickable_elements=clickable_elements
                )
            except asyncio.CancelledError:
                # Timeout fired while PageButtonTest was running.  The inner loop
                # saved whatever progress it completed to button_test._partial_result
                # before re-raising.  Record that partial data to the test report so
                # the user sees "tested N/M elements" instead of a blank timeout entry.
                partial = getattr(button_test, '_partial_result', None)
                if partial and partial.get('tested', 0) > 0:
                    tested = partial['tested']
                    total_elements = partial['total']
                    partial_failed = partial['failed']
                    partial_passed = tested - partial_failed
                    readable_partial = _build_human_readable_summary(
                        tested, partial_passed, partial_failed,
                        partial['failed_steps'], language,
                        clickable_elements=clickable_elements,
                    )
                    skipped = total_elements - tested
                    skipped_note = (
                        f'（因超时中断，另有 {skipped} 个元素未测试）'
                        if language == 'zh-CN' else
                        f'({skipped} element(s) not tested due to timeout)'
                    )
                    self.safe_record_step(
                        description=(
                            f'Traverse clickable elements '
                            f'(partial: {tested}/{total_elements} tested, timed out)'
                        ),
                        model_io_data={
                            'total_elements': total_elements,
                            'raw_elements_count': len(raw_elements),
                            'tested': tested,
                            'passed': partial_passed,
                            'failed': partial_failed,
                            'partial': True,
                            'summary': f'{readable_partial}\n{skipped_note}'.split('\n'),
                        },
                        status='warning',
                        screenshots=[
                            s
                            for step in partial['steps']
                            for s in (getattr(step, 'screenshots', None) or [])
                        ],
                    )
                    logger.info(
                        f'Button Test Tool: Partial results saved '
                        f'({tested}/{total_elements} elements, {partial_failed} failed) '
                        f'before timeout'
                    )
                raise  # Re-raise so asyncio.timeout() converts it to TimeoutError

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

            # Build data needed for Step 5 and Step 6
            failed_steps = []
            all_screenshots = []
            for step in result.steps:
                if step.status == TestStatus.FAILED:
                    failed_steps.append(step)
                if hasattr(step, 'screenshots') and step.screenshots:
                    all_screenshots.extend(step.screenshots)

            readable_summary = _build_human_readable_summary(
                total_elements, passed_count, failed_count,
                failed_steps, language,
                clickable_elements=clickable_elements,
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
                        'raw_elements_count': len(raw_elements),
                        'passed_count': passed_count,
                        'failed_count': failed_count,
                        'test_status': result.status.value,
                    },
                    'diagnostic_summary': readable_summary,
                    'timestamp': datetime.now().isoformat(),
                }
            )

            # Step 6: Record to case_recorder (using safe_record_step helper)

            self.safe_record_step(
                description=f'Traverse clickable elements (tested {total_elements})',
                model_io_data={
                    'total_elements': total_elements,
                    'raw_elements_count': len(raw_elements),
                    'passed': passed_count,
                    'failed': failed_count,
                    'summary': readable_summary.split('\n'),
                },
                status='passed' if result.status == TestStatus.PASSED else 'warning',
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
