import asyncio
import logging
import re
import socket
import ssl
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests
from playwright.async_api import Page

from webqa_agent.data.gen_structures import (SubTestReport, SubTestResult,
                                             SubTestScreenshot, SubTestStep,
                                             TestStatus)
from webqa_agent.utils import Display, i18n
from webqa_agent.utils.log_icon import icon


class _LocalizedTestBase:
    """Base class providing i18n support for web test classes."""

    def __init__(self, report_config: dict = None):
        self.language = report_config.get('language', 'zh-CN') if report_config else 'zh-CN'
        self.localized_strings = {
            'zh-CN': i18n.get_lang_data('zh-CN').get('tools', {}).get('basic', {}),
            'en-US': i18n.get_lang_data('en-US').get('tools', {}).get('basic', {}),
        }

    def _get_text(self, key: str) -> str:
        """Get localized text for the given key."""
        return self.localized_strings.get(self.language, {}).get(key, key)


class WebAccessibilityTest(_LocalizedTestBase):

    async def run(self, url: str, sub_links: list) -> SubTestResult:
        logging.debug(f'Starting combined HTTPS and status check for {url}')
        result = SubTestResult(name=self._get_text('accessibility_check'), sub_test_id='basic_1')

        with Display.display(self._get_text('basic_test_display') + result.name):  # pylint: disable=not-callable
            try:
                # check the main link
                main_valid, main_reason, main_expiry_date = await self.check_https_expiry(url)
                main_status = await self.check_page_status(url)
                main_url_result = {
                    'url': url,
                    'status': main_status,
                    'https_valid': main_valid,
                    'https_reason': main_reason,
                    'https_expiry_date': main_expiry_date,
                }

                # check sub links
                sub_link_results = []
                failed_links = 0
                total_links = 1  # include main link

                if sub_links:
                    total_links += len(sub_links)
                    for link in sub_links:
                        sub_result = {
                            'url': link,
                            'status': None,
                            'https_valid': None,
                            'https_reason': None,
                            'https_expiry_date': None,
                        }
                        try:
                            sub_result['https_valid'], sub_result['https_reason'], sub_result['https_expiry_date'] = (
                                await self.check_https_expiry(link)
                            )
                        except Exception as e:
                            logging.error(f'Failed to check HTTPS for {link}: {str(e)}')
                            sub_result['https_valid'] = False
                            sub_result['https_reason'] = str(e)
                        try:
                            sub_result['status'] = await self.check_page_status(link)
                        except Exception as e:
                            logging.error(f'Failed to check status for {link}: {str(e)}')
                            sub_result['status'] = {'error': str(e)}
                        sub_link_results.append(sub_result)

                # check if all passed
                def is_passed(item):
                    https_valid = item['https_valid']
                    status_code = item['status']
                    # ensure status_code is an integer
                    if isinstance(status_code, dict):
                        return False  # if status_code is a dict (contains error info), then test failed
                    return https_valid and (status_code is not None and status_code < 400)

                all_passed = is_passed(main_url_result)
                if not all_passed:
                    failed_links += 1

                if sub_links:
                    for link in sub_link_results:
                        if not is_passed(link):
                            failed_links += 1
                    all_passed = all_passed and all(is_passed(link) for link in sub_link_results)

                result.status = TestStatus.PASSED if all_passed else TestStatus.FAILED

                # add main link check steps
                result.report.append(SubTestReport(
                    title=self._get_text('main_link_check'),
                    issues=f"{self._get_text('test_results')}: {main_url_result}"))

                # add sub link check steps
                if sub_links:
                    for i, sub_link_result in enumerate(sub_link_results):
                        result.report.append(
                            SubTestReport(
                                title=f"{self._get_text('sub_link_check')} {i + 1}",
                                issues=f"{self._get_text('test_results')}: {sub_link_result}")
                        )
                logging.info(f"{icon['check']} Sub Test Completed: {result.name}")

            except Exception as e:
                error_message = f'An error occurred in WebAccessibilityTest: {str(e)}'
                logging.error(error_message)
                result.status = TestStatus.FAILED
                result.messages = {'error': error_message}

            return result

    @staticmethod
    async def check_https_expiry(url: str, timeout: float = 10.0) -> tuple[bool, str, str]:
        """Check HTTPS certificate expiry in a thread to avoid blocking the
        event loop."""
        loop = asyncio.get_running_loop()

        def _sync_check():
            parsed_url = urlparse(url)
            hostname = parsed_url.hostname
            port = 443
            result_valid = None
            result_reason = None
            result_expiry_date = None
            try:
                context = ssl.create_default_context()
                with socket.create_connection((hostname, port), timeout=timeout) as sock:
                    with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                        cert = ssock.getpeercert()

                expiry_date = datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
                formatted_expiry_date = expiry_date.strftime('%Y-%m-%d %H:%M:%S')
                result_valid = datetime.now() < expiry_date
                result_expiry_date = formatted_expiry_date
                logging.debug(f"HTTPS certificate is {'valid' if result_valid else 'expired'} for {url}")
            except ssl.SSLCertVerificationError as ssl_error:
                result_valid = False
                result_reason = str(ssl_error)
                logging.error(f'SSL verification error: {ssl_error}')
            except Exception as e:
                result_valid = False
                result_reason = str(e)
                logging.error(f'Error checking certificate: {str(e)}')
            return result_valid, result_reason, result_expiry_date

        return await loop.run_in_executor(None, _sync_check)

    @staticmethod
    async def check_page_status(url: str, timeout: float = 10.0) -> int:
        """Get page status code using requests in a thread pool to avoid
        blocking."""
        loop = asyncio.get_running_loop()

        def _sync_get():
            return requests.get(url, timeout=timeout)

        try:
            response = await loop.run_in_executor(None, _sync_get)
            status_code = response.status_code
            logging.debug(f'Page {url} returned status {status_code}')
            return status_code
        except requests.RequestException as e:
            error_message = f'Failed to load page {url}: {str(e)}'
            logging.error(error_message)
            raise Exception(error_message)


# ---------------------------------------------------------------------------
# Element label and highlight helpers for screenshot annotation
# ---------------------------------------------------------------------------

# HTML tag name → human-readable label (zh-CN, en-US).
# Single source of truth — also imported by button_check_tool.
TAG_LABELS: Dict[str, tuple] = {
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

# Auto-generated CSS class prefixes to skip in fallback labelling.
# Covers CSS Modules (css-), styled-components (sc-/styled-), Svelte, JS hooks.
_AUTO_CLASS_PREFIX = re.compile(r'^(css-|sc-|svelte-|styled-|js-|_)')


def get_element_semantic_label(elem: dict) -> str:
    """Extract a human-readable semantic label from an element dict.

    Priority chain (first non-empty value wins):
        aria-label → innerText[:30] → placeholder → title → alt → name
        → role → first meaningful CSS class → ''

    This is a shared utility used by both web_checks and button_check_tool to
    ensure consistent semantic labelling of elements across all tools.

    Args:
        elem: Element dict from DeepCrawler with keys like 'attributes',
            'innerText', 'className', 'selector'.

    Returns:
        Human-readable label string, or '' if none found.
    """
    attrs_raw = elem.get('attributes')
    if isinstance(attrs_raw, list):
        # JS serialises attributes as [{name: ..., value: ...}]; normalise to dict
        attrs: dict = {
            a['name']: a.get('value', '')
            for a in attrs_raw
            if isinstance(a, dict) and 'name' in a
        }
    elif isinstance(attrs_raw, dict):
        attrs = attrs_raw
    else:
        attrs = {}

    # Fallback 8: first meaningful CSS class from className or selector
    _class_fallback: str | None = None
    # className is the raw class attribute: "chat-voice-input other-class"
    _class_name = (elem.get('className') or '').strip()
    if _class_name:
        for _cls in _class_name.split():
            if len(_cls) > 2 and not _AUTO_CLASS_PREFIX.match(_cls):
                _class_fallback = _cls
                break
    # selector is CSS notation: "div.chat-voice-input" — extract .xxx parts only
    if not _class_fallback:
        _selector = elem.get('selector') or ''
        for _cls in re.findall(r'\.([a-zA-Z][\w-]*)', _selector):
            if len(_cls) > 2 and not _AUTO_CLASS_PREFIX.match(_cls):
                _class_fallback = _cls
                break

    candidates = [
        (attrs.get('aria-label') or '').strip() or None,
        (elem.get('innerText') or '')[:30].strip() or None,
        (attrs.get('placeholder') or '').strip() or None,
        (attrs.get('title') or '').strip() or None,
        (attrs.get('alt') or '').strip() or None,
        (attrs.get('name') or '').strip() or None,
        (attrs.get('role') or '').strip() or None,
        _class_fallback,
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    return ''


def _humanize_element_label(
    tag: str, elem_id: int, language: str = 'en-US', elem: dict | None = None,
) -> str:
    """Human-readable element label for screenshot annotations.

    When *elem* is provided, a semantic name is extracted via
    :func:`get_element_semantic_label` (priority: aria-label → innerText →
    placeholder → title → alt → name → role → CSS class).

    Format with a name  : Link[文心一言](#9)
    Format without a name: Link(#9)
    """
    human_name = get_element_semantic_label(elem) if elem is not None else ''

    lang_idx = 0 if language == 'zh-CN' else 1
    if tag:
        base_label = TAG_LABELS.get(tag, (tag, tag.title()))[lang_idx]
    else:
        base_label = str(elem_id) if language == 'zh-CN' else 'Element'

    if human_name:
        return f'{base_label}[{human_name}](#{elem_id})'
    return f'{base_label}(#{elem_id})'


async def _highlight_element_for_screenshot(
    page: Any, tag: str, text: str, selector: str, xpath: str = '',
) -> bool:
    """Add red outline to element via JS. Returns True if element was found.

    Lookup chain:
      ① CSS selector (skipped if bare tag name) → ② XPath → ③ tag + text match → ④ return false
    Bare-tag selectors (e.g. ``'a'``, ``'div'``) are skipped because
    ``querySelector`` returns the first element of that type, not the target.
    """
    try:
        return await page.evaluate("""({tag, text, selector, xpath}) => {
            let el = null;
            // Only use CSS selector if it's specific (contains class, ID, or
            // attribute qualifiers).  Bare tag names like 'a' or 'div' match
            // the *first* element of that type — almost always wrong.
            const isBareTag = selector && /^[a-z][a-z0-9]*$/i.test(selector.trim());
            if (selector && !isBareTag) {
                try { el = document.querySelector(selector); } catch(e) {}
            }
            if (!el && xpath) {
                try {
                    const xpathResult = document.evaluate(
                        xpath, document, null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE, null
                    );
                    el = xpathResult.singleNodeValue;
                } catch(e) {}
            }
            if (!el && text && tag) {
                for (const c of document.querySelectorAll(tag)) {
                    if (c.textContent && c.textContent.trim().startsWith(text.trim())) {
                        el = c; break;
                    }
                }
            }
            if (el) {
                el.dataset.webqaHighlight = 'true';
                el.style.outline = '3px solid red';
                el.style.outlineOffset = '2px';
                el.style.boxShadow = '0 0 8px rgba(255,0,0,0.6)';
                el.scrollIntoView({behavior:'instant', block:'center'});
                return true;
            }
            return false;
        }""", {'tag': tag, 'text': text, 'selector': selector, 'xpath': xpath})
    except Exception:
        return False


async def _remove_element_highlight(page: Any) -> None:
    """Remove all webqa highlight markers from the page."""
    try:
        await page.evaluate("""() => {
            for (const el of document.querySelectorAll('[data-webqa-highlight]')) {
                el.style.outline = '';
                el.style.outlineOffset = '';
                el.style.boxShadow = '';
                delete el.dataset.webqaHighlight;
            }
        }""")
    except Exception:
        pass


class PageButtonTest(_LocalizedTestBase):

    async def run(self, url: str, page: Page, clickable_elements: dict, **kwargs) -> SubTestResult:
        """Run page button test using ActionHandler for enhanced error
        handling.

        Args:
            url: target url
            page: playwright page
            clickable_elements: dict of clickable elements (id -> element_info)

        Returns:
            SubTestResult containing test results, click screenshots, and detailed error context
        """

        result = SubTestResult(name=self._get_text('clickable_element_check'), sub_test_id='basic_2')
        logging.info(f"{icon['running']} Running Sub Test: {result.name}")
        sub_test_results = []
        # with Display.display(self._get_text('basic_test_display') + result.name):  # pylint: disable=not-callable
        if True:
            try:
                status = TestStatus.PASSED
                from webqa_agent.actions.action_handler import (
                    ActionHandler, action_context_var)
                from webqa_agent.browser.event_collector import \
                    BrowserEventCollector

                # Initialize ActionHandler with element buffer
                action_handler = ActionHandler()
                action_handler.page = page
                # Convert clickable_elements to ActionHandler buffer format
                action_handler.page_element_buffer = {
                    str(k): v for k, v in clickable_elements.items()
                }

                # Per-element event collector for browser error detection.
                # Wrapped in try/finally so detach() is always called — even
                # when clickable_elements is empty or CancelledError propagates.
                collector = BrowserEventCollector()
                collector.attach(page)

                # count total passed / failed
                total, total_failed = 0, 0

                try:
                    if clickable_elements:
                        for highlight_id, element in clickable_elements.items():
                            element_text = element.get('selector', 'Unknown')
                            logging.info(f'Testing clickable element {highlight_id}...')

                            step = SubTestStep(
                                id=int(highlight_id),
                                description=f"{self._get_text('click_element')}: {element_text}",
                                screenshots=[],
                                actions=[]
                            )

                            step_recorded = False
                            try:
                                current_url = page.url
                                if current_url != url:
                                    await page.goto(url)
                                    await asyncio.sleep(0.5)

                                # Clear per-action buffers before the click
                                await collector.clear()

                                click_success = await action_handler.click(str(highlight_id))
                                ctx = action_context_var.get()

                                await asyncio.sleep(1)

                                events = await collector.collect(timeout=2.0)

                                # Check for new browser errors from this click
                                new_console_errors = events.get('console_errors', [])
                                new_request_failures = events.get('request_failures', [])
                                has_browser_errors = bool(new_console_errors) or bool(new_request_failures)

                                browser_errors_summary: List[str] = []
                                if has_browser_errors:
                                    for err in new_console_errors:
                                        browser_errors_summary.append(f"Console Error: {err.get('text')}")
                                    for err in new_request_failures:
                                        browser_errors_summary.append(f"Network Failure: {err.get('url')} - {err.get('failure')}")

                                if click_success and not has_browser_errors:
                                    step.status = TestStatus.PASSED
                                    total += 1

                                else:
                                    # Click failed or browser errors occurred
                                    # Take and append the 'after' screenshot (error scene)
                                    after_b64, after_path = await action_handler.b64_page_screenshot(
                                        file_name=f'element_{highlight_id}_error_scene',
                                        context='test'
                                    )
                                    if after_path:
                                        step.screenshots.append(SubTestScreenshot(
                                            type='path',
                                            data=after_path,
                                            label='Error Scene'
                                        ))
                                    elif after_b64:
                                        step.screenshots.append(SubTestScreenshot(
                                            type='base64',
                                            data=after_b64,
                                            label='Error Scene'
                                        ))

                                    error_type = 'unknown'
                                    error_reason = 'Click failed or errors occurred'

                                    if not click_success and ctx:
                                        error_type = ctx.error_type
                                        error_reason = ctx.error_reason
                                    elif has_browser_errors:
                                        error_type = 'browser_error'
                                        error_reason = 'Console or Network errors occurred after click'

                                    error_msg_parts = [f'{error_type}: {error_reason}']

                                    if not click_success and ctx and ctx.playwright_error:
                                        error_msg_parts.append(f'Details: {ctx.playwright_error}')

                                    if has_browser_errors and browser_errors_summary:
                                        error_msg_parts.append('Browser Errors: ' + '; '.join(browser_errors_summary))

                                    step.errors = ' | '.join(error_msg_parts)
                                    step.status = TestStatus.FAILED
                                    total += 1
                                    total_failed += 1
                                    status = TestStatus.FAILED

                                    logging.warning(
                                        f'Click failed/errored for element {highlight_id}: '
                                        f'type={error_type}, '
                                        f'reason={error_reason}'
                                    )

                                    # Capture highlighted screenshot for failed element
                                    try:
                                        if page.url != url:
                                            await page.goto(url)
                                            await asyncio.sleep(0.3)

                                        _elem_data = element
                                        _tag_name = (_elem_data.get('tagName') or '').lower()
                                        _inner_text = (_elem_data.get('innerText') or '')[:40]
                                        _elem_selector = _elem_data.get('selector', '')

                                        _found = await _highlight_element_for_screenshot(
                                            page, _tag_name, _inner_text, _elem_selector,
                                            xpath=_elem_data.get('xpath', ''),
                                        )
                                        if _found:
                                            await asyncio.sleep(0.2)
                                            _hl_b64, _hl_path = await action_handler.b64_page_screenshot(
                                                file_name=f'element_{highlight_id}_highlighted',
                                                context='test',
                                            )
                                            _elem_label = _humanize_element_label(
                                                _tag_name, int(highlight_id), self.language,
                                                elem=_elem_data,
                                            )
                                            if _hl_path:
                                                step.screenshots.insert(0, SubTestScreenshot(
                                                    type='path', data=_hl_path,
                                                    label=f'Failed: {_elem_label}',
                                                ))
                                            elif _hl_b64:
                                                step.screenshots.insert(0, SubTestScreenshot(
                                                    type='base64', data=_hl_b64,
                                                    label=f'Failed: {_elem_label}',
                                                ))
                                            await _remove_element_highlight(page)

                                    except Exception as _hl_err:
                                        logging.debug(
                                            f'Failed to capture highlighted screenshot for element '
                                            f'{highlight_id}: {_hl_err}'
                                        )

                                # Brief pause between clicks
                                await asyncio.sleep(0.5)

                            except asyncio.CancelledError:
                                # Timeout mid-element: discard this incomplete step so
                                # the outer CancelledError handler only counts elements
                                # that finished with an explicit PASSED/FAILED status.
                                step_recorded = True  # prevent finally from appending
                                raise

                            except Exception as e:
                                error_message = f'PageButtonTest error: {str(e)}'
                                logging.error(error_message)
                                step.status = TestStatus.FAILED
                                step.errors = str(e)
                                total += 1
                                total_failed += 1
                                status = TestStatus.FAILED
                            finally:
                                if not step_recorded:
                                    sub_test_results.append(step)

                finally:
                    # Clean up listeners on every exit path (including timeout/cancel).
                    collector.detach(page)

                logging.info(f"{icon['check']} Sub Test Completed: {result.name}")
                result.report.append(
                    SubTestReport(
                        title=self._get_text('traversal_test_results'),
                        issues=f"{self._get_text('clickable_elements_count')}{total}{self._get_text('click_failed_count')}{total_failed}",
                    )
                )

            except asyncio.CancelledError:
                # Step-level timeout: save whatever progress was accumulated so
                # ButtonCheckTool._arun() can record a meaningful partial result.
                completed_steps = [
                    s for s in sub_test_results
                    if s.status in (TestStatus.PASSED, TestStatus.FAILED)
                ]
                self._partial_result = {
                    'tested': len(completed_steps),
                    'total': len(clickable_elements),
                    'failed': sum(1 for s in completed_steps if s.status == TestStatus.FAILED),
                    'failed_steps': [s for s in completed_steps if s.status == TestStatus.FAILED],
                    'steps': completed_steps,
                }
                logging.info(
                    f'PageButtonTest: CancelledError after '
                    f'{self._partial_result["tested"]}/{self._partial_result["total"]} elements'
                )
                raise  # Must propagate so asyncio.timeout() converts to TimeoutError

            except Exception as e:
                error_message = f'PageButtonTest error: {str(e)}'
                logging.error(error_message)
                status = TestStatus.FAILED
                result.messages = {'error': error_message}

            result.status = status
            result.steps = sub_test_results
            return result
