import ast
import asyncio
import base64
import json
import logging
import uuid
from io import BytesIO
from typing import List, Dict, Any, Optional

from html2text import html2text
from playwright.async_api import Page

from webqa_agent.actions.action_handler import ActionHandler
from webqa_agent.actions.scroll_handler import ScrollHandler
from webqa_agent.crawler.deep_crawler import DeepCrawler
from webqa_agent.data.test_structures import (SubTestReport, SubTestResult,
                                              SubTestScreenshot, SubTestStep,
                                              TestStatus)
from webqa_agent.llm.llm_api import LLMAPI
from webqa_agent.llm.prompt import LLMPrompt
from webqa_agent.utils import Display
from webqa_agent.utils.log_icon import icon
from webqa_agent.utils import i18n

try:
    from PIL import Image, ImageDraw
    _PIL_AVAILABLE = True
except Exception:
    _PIL_AVAILABLE = False


class PageTextTest:

    def __init__(self, llm_config: dict, user_cases: List[str] = None, report_config: dict = None):
        self.llm_config = llm_config
        self.user_cases = user_cases or LLMPrompt.TEXT_USER_CASES
        self.llm = LLMAPI(self.llm_config)
        self.language = report_config["language"] if report_config else "zh-CN"
        self.localized_strings = {
            'zh-CN': i18n.get_lang_data('zh-CN').get('testers', {}).get('ux', {}),
            'en-US': i18n.get_lang_data('en-US').get('testers', {}).get('ux', {}),
        }
    
    def _get_text(self, key: str) -> str:
        """Get localized text for the given key."""
        return self.localized_strings.get(self.language, {}).get(key, key)

    async def get_iframe_content(self, frame):
        # get iframe content
        html_content = await frame.content()
        page_text = html2text(html_content)
        for child_frame in frame.child_frames:
            page_text += await self.get_iframe_content(child_frame)
        return page_text

    async def run(self, page: Page) -> SubTestResult:
        """Runs a test to check the text content of a web page and identifies
        any issues based on predefined user cases."""
        result = SubTestResult(name=self._get_text('text_check_name'))
        logging.info(f"{icon['running']} Running Sub Test: {result.name}")

        with Display.display(self._get_text('ux_test_display') + result.name):
            try:
                # 创建ActionHandler用于截图
                action_handler = ActionHandler()
                action_handler.page = page
                await asyncio.sleep(2)

                # 检查页面是否空白
                is_blank = await page.evaluate("document.body.innerText.trim() === ''")
                if is_blank:
                    logging.error('page is blank, no visible content')
                    result.status = TestStatus.FAILED
                    result.messages = {'page': self._get_text('page_blank_error')}
                    return result

                logging.debug('page is not blank, start crawling page content')

                # 获取页面文本内容
                page_text = html2text(await page.content())
                for frame in page.frames:
                    if frame != page.main_frame:
                        page_text += await self.get_iframe_content(frame)

                # 运行每个用例
                for user_case in self.user_cases:
                    logging.debug(f'page_text: {page_text}')
                    prompt = self._build_prompt(page_text, user_case)

                    # 确保LLM已初始化
                    if not hasattr(self.llm, '_client') or self.llm._client is None:
                        await self.llm.initialize()

                    test_page_content = await self.llm.get_llm_response(LLMPrompt.page_default_prompt, prompt)

                    has_issues = test_page_content and 'None' not in str(test_page_content)
                    if has_issues:
                        result.status = TestStatus.FAILED
                        issues = self.format_issues_to_markdown(test_page_content)
                    else:
                        result.status = TestStatus.PASSED
                        issues = self._get_text('no_issues_found')
                    result.report.append(
                        SubTestReport(
                            title=self._get_text('report_title'),
                            issues=issues,
                        )
                    )
                logging.info(f"{icon['check']} Sub Test Completed: {result.name}")

            except Exception as e:
                error_message = f'PageTextTest error: {str(e)}'
                logging.error(error_message)
                result.status = TestStatus.FAILED
                result.messages = {'page': str(e)}
                raise

            return result

    def _build_prompt(self, page_text: str, user_case: str) -> str:
        """Builds the LLM prompt in English."""
        return f"""Task description: Based on the provided web page content and user cases, check for any typos or English grammar errors. If errors are found, output the results in the specified JSON format.
                Input information:
                - Web content: ${page_text}
                - User case: ${user_case}
                Output requirements:
                - If no errors are found, output only None, do not include any explanations.
                - If errors are found, please output in the following JSON format:
                {{
                    "error": [
                        {{
                            "location": "Description of error location",
                            "current": "Current erroneous content",
                            "suggested": "Suggested modification",
                            "type": "Error type"
                        }}
                    ],
                    "reason": "Overall problem description"
                }}
                """
    
    def format_issues_to_markdown(self, issues_content: str) -> str:
        # Format issues to markdown
        if not issues_content or issues_content == self._get_text('no_issues_found'):
            return issues_content
        
        try:
            if isinstance(issues_content, str):
                if issues_content.strip().startswith('{'):
                    data = json.loads(issues_content)
                else:
                    return issues_content
            else:
                data = issues_content
                
            if 'error' in data and 'reason' in data:
                errors = data['error']
                reason_summary = data['reason']
                
                if not errors:
                    return self._get_text('no_issues_found')
                
                markdown_content = ''
                if reason_summary:
                    markdown_content += f"{self._get_text('overall_problem')}{reason_summary}\n\n"
                
                if isinstance(errors, list):
                    for i, error_item in enumerate(errors, 1):
                        if isinstance(error_item, dict):
                            location = error_item.get('location', self._get_text('unknown_location'))
                            current = error_item.get('current', '')
                            suggested = error_item.get('suggested', '')
                            error_type = error_item.get('type', self._get_text('unknown_type'))
                            
                            markdown_content += f"{self._get_text('issue_details')}".format(i)
                            markdown_content += f"{self._get_text('location')}{location}\n\n"
                            markdown_content += f"{self._get_text('error_content')}`{current}`\n\n"
                            markdown_content += f"{self._get_text('suggested_fix')}`{suggested}`\n\n"
                            markdown_content += f"{self._get_text('error_type')}{error_type}\n\n"
                        else:
                            markdown_content += f"{self._get_text('issue_details')}".format(i)
                            markdown_content += f"{self._get_text('error_content')}{error_item}\n\n"
                else:
                    markdown_content += f"{self._get_text('error_content')}{errors}\n\n"
                
                return markdown_content
            else:
                return issues_content
                
        except (json.JSONDecodeError, KeyError, TypeError):
            return issues_content


class PageContentTest:

    def __init__(self, llm_config: dict, user_cases: List[str] = None, report_config: dict = None):
        self.llm_config = llm_config
        self.user_cases = user_cases or LLMPrompt.CONTENT_USER_CASES
        self.llm = LLMAPI(self.llm_config)
        self.language = report_config["language"] if report_config else "zh-CN"
        self.localized_strings = {
            'zh-CN': i18n.get_lang_data('zh-CN').get('testers', {}).get('ux', {}),
            'en-US': i18n.get_lang_data('en-US').get('testers', {}).get('ux', {}),
        }
    
    def _get_text(self, key: str) -> str:
        """Get localized text for the given key."""
        return self.localized_strings.get(self.language, {}).get(key, key)

    async def run(self, page: Page, **kwargs) -> List[SubTestResult]:
        """run page content tests and return two separate SubTestResults
        Args:
            page: playwright page
            **kwargs: additional arguments

        Returns:
            List of SubTestResult containing layout test and image test results
        """
        # 创建两个独立的测试结果
        layout_result = SubTestResult(name=self._get_text('layout_check_name'))
        # image_result = SubTestResult(name=_['element_check_name'])

        logging.info(f"{icon['running']} Running Sub Tests: {layout_result.name}")

        dp = DeepCrawler(page)
        crawl_result = await dp.crawl(highlight=True, filter_text=False, viewport_only=False, include_styles=True)

        # Check for unsupported page types (PDF, plugins, etc.)
        if hasattr(crawl_result, 'page_status') and crawl_result.page_status == "UNSUPPORTED_PAGE":
            page_type = getattr(crawl_result, 'page_type', 'unknown')
            logging.warning(f"Cannot execute UX test on {page_type} page, skipping")
            layout_result.status = TestStatus.FAILED
            layout_result.messages = {'page': f"Page type '{page_type}' is unsupported, cannot execute UX test"}
            return [layout_result]

        id_map = crawl_result.raw_dict()
        logging.debug(f'id_map: {id_map}')
        await dp.remove_marker()

        # LAYOUT
        layout_case = self.user_cases[0]

        try:
            if not hasattr(self.llm, '_client') or self.llm._client is None:
                await self.llm.initialize()

            page_identifier = str(int(uuid.uuid4().int) % 10000)
            _scroll = ScrollHandler(page)
            logging.info('Scrolling the page...')
            browser_screenshot = await _scroll.scroll_and_crawl(
                scroll=True, max_scrolls=10, page_identifier=page_identifier
            )

            page_img = True

            with Display.display(self._get_text('ux_test_display') + self._get_text('layout_case')):
                # 执行布局检查
                await self._run_single_test(layout_result, layout_case, id_map, browser_screenshot, page_img)
                logging.info(f"{icon['check']} Sub Tests Completed: {layout_result.name}")

            # with Display.display(_['ux_test_display'] + _['element_check_name']):
            #     try:
            #         await self._run_single_test(image_result, image_case, id_map, browser_screenshot, page_img)
            #         logging.info(f"{icon['check']} Sub Tests Completed: {image_result.name}")
            #     except Exception as e:
            #         error_message = f'Image test error: {str(e)}'
            #         logging.error(error_message)
            #         image_result.status = TestStatus.FAILED
            #         image_result.messages = {'page': str(e)}

        except Exception as e:
            error_message = f'PageContentTest general error: {str(e)}'
            logging.error(error_message)
            raise

        return [layout_result]

    async def _run_single_test(self, result: SubTestResult, user_case: str, id_map: dict, browser_screenshot: List, page_img: bool):
        """执行单个测试."""
        id_counter = 0
        overall_status = TestStatus.PASSED

        prompt = self._build_prompt(user_case, id_map, len(browser_screenshot))
        logging.debug(f'{result.name} test, prompt: {prompt}')
        logging.info(f"Vision model: evaluating use case '{result.name}'...")
        test_page_content = await self._get_llm_response(prompt, page_img, browser_screenshot)

        # parse LLM response
        summary_text = None
        issues_list = []
        issues_text = self._get_text('no_issues_found')  # initialize with default value
        case_status = TestStatus.PASSED

        logging.debug(f"LLM response for user case '{result.name}...': {test_page_content}")

        if test_page_content and str(test_page_content).strip():
            try:
                parsed = json.loads(test_page_content)
                logging.debug(f'Parsed LLM output: {parsed}')
            except Exception:
                logging.warning('Unable to parse LLM output as JSON')
                parsed = None

            if parsed:
                # Check if it's the "no issues" format
                if isinstance(parsed, dict) and parsed.get('status') == 'no_issues':
                    # No issues found - this is the expected case
                    case_status = TestStatus.PASSED
                    issues_text = self._get_text('no_issues_found')
                    logging.debug(f"LLM confirmed no issues found: {parsed.get('message', 'No issues detected')}")

                # Check if it's the "issues found" format (array)
                elif isinstance(parsed, list) and len(parsed) > 0:
                    # Issues found - process the array
                    case_status = TestStatus.WARNING

                    for item in parsed:
                        if isinstance(item, dict):
                            if 'summary' in item:
                                summary_text = item.get('summary')
                                logging.debug(f'Found summary: {summary_text}')
                            elif any(key in item for key in ['issue', 'screenshotid', 'coordinates']):
                                # This is an issue object
                                issues_list.append(item)
                                logging.debug(f"Added issue to list: {item.get('issue', 'No issue description')}")
                            else:
                                logging.debug(f'Skipping item without issue fields: {item}')

                # Fallback for other dict formats
                elif isinstance(parsed, dict):
                    summary_text = parsed.get('summary')
                    issues_candidate = {k: v for k, v in parsed.items() if k != 'summary'}
                    if issues_candidate:
                        issues_list.append(issues_candidate)
                        case_status = TestStatus.WARNING

                # If we have issues, set status to warning
                if issues_list:
                    case_status = TestStatus.WARNING

            logging.debug(f'Processing {len(issues_list)} issues')
            for idx, issue in enumerate(issues_list):
                # collect issue info for report
                issue_desc = issue.get('issue') or issue.get('description') or str(issue)
                suggestion = issue.get('suggestion')
                coords = None
                if isinstance(issue, dict) and 'coordinates' in issue:
                    c = issue.get('coordinates')
                    if isinstance(c, (list, tuple)) and len(c) == 4:
                        try:
                            x1, y1, x2, y2 = [int(float(v)) for v in c]
                            # ensure ordering and non-negative
                            x1, x2 = sorted([max(0, x1), max(0, x2)])
                            y1, y2 = sorted([max(0, y1), max(0, y2)])
                            if y1 == y2:
                                y2 = y1 + 5
                            coords = [x1, y1, x2, y2]
                            issue['coordinates'] = coords
                            logging.debug(f'Issue {idx + 1} - Processed coordinates: {coords}')
                        except Exception as e:
                            logging.warning(f'Issue {idx + 1} - Failed to process coordinates {c}: {e}')
                            coords = None

                # if screenshot index (0-based), append corresponding screenshot and create step
                screenshot_idx = issue.get('screenshotid')
                if isinstance(screenshot_idx, int) and 0 <= screenshot_idx < len(browser_screenshot):
                    screenshot_data = browser_screenshot[screenshot_idx]

                    def _annotate_b64_image(image_b64: str, rect: List[int]) -> str:
                        if not (_PIL_AVAILABLE and isinstance(image_b64, str) and image_b64.startswith('data:image')):
                            return image_b64
                        try:
                            header, b64 = image_b64.split(',', 1)
                            img_bytes = base64.b64decode(b64)
                            with Image.open(BytesIO(img_bytes)) as im:
                                # Ensure RGB to draw colored lines
                                if im.mode not in ('RGB', 'RGBA'):
                                    im = im.convert('RGB')
                                draw = ImageDraw.Draw(im)
                                x1, y1, x2, y2 = rect
                                # draw rectangle with width 3 in red
                                for w in range(2):
                                    draw.rectangle([x1 - w, y1 - w, x2 + w, y2 + w], outline=(255, 0, 0))
                                out = BytesIO()
                                im.save(out, format='PNG')
                                new_b64 = base64.b64encode(out.getvalue()).decode('utf-8')
                                return f'data:image/png;base64,{new_b64}'
                        except Exception:
                            return image_b64

                    annotated_b64 = None
                    screenshots = []
                    if isinstance(screenshot_data, str):
                        # Always include annotated (if possible) and original in order
                        if coords is not None:
                            annotated_b64 = _annotate_b64_image(screenshot_data, coords)
                            screenshots.append(SubTestScreenshot(type='base64', data=annotated_b64))
                            screenshots.append(SubTestScreenshot(type='base64', data=screenshot_data))
                        else:
                            # No coordinates -> include original only
                            screenshots.append(SubTestScreenshot(type='base64', data=screenshot_data))
                    elif isinstance(screenshot_data, dict):
                        data_str = screenshot_data.get('data')
                        if isinstance(data_str, str):
                            if coords is not None:
                                annotated_b64 = _annotate_b64_image(data_str, coords)
                                screenshots.append(SubTestScreenshot(type='base64', data=annotated_b64))
                                screenshots.append(SubTestScreenshot(type='base64', data=data_str))
                            else:
                                screenshots.append(SubTestScreenshot(type='base64', data=data_str))
                        else:
                            # Unable to annotate; include original dict
                            screenshots.append(SubTestScreenshot(**screenshot_data))

                    # step status: all discovered issues are warnings
                    step_status = TestStatus.WARNING
                    result.steps.append(SubTestStep(
                        id=int(id_counter + 1),
                        description=user_case[:4] + ': ' + issue_desc,
                        modelIO=suggestion,
                        screenshots=screenshots,
                        status=step_status,
                    ))
                    id_counter += 1

            # compute issues_text per requirement and collect overall summary
            if summary_text and str(summary_text).strip():
                issues_text = str(summary_text).strip()
            elif issues_list:
                try:
                    issues_text = json.dumps(issues_list, ensure_ascii=False)
                except Exception:
                    issues_text = str(issues_list)
        else:
            # no valid content from LLM, treat as no issues found
            case_status = TestStatus.PASSED
            issues_text = self._get_text('no_issues_found')
            logging.debug(f'LLM returned no content, treating as PASSED')

        result.report.append(SubTestReport(title=self._get_text('report_title'), issues=issues_text))
        # aggregate overall status: any WARNING -> WARNING; else PASSED
        if case_status == TestStatus.WARNING and overall_status != TestStatus.WARNING:
            overall_status = TestStatus.WARNING

        result.status = overall_status

    def _build_prompt(self, user_case: str, id_map: dict, screenshot_count: int = 0) -> str:
        # 构建结构化的DOM/CSS信息摘要
        structured_info = ''

        if id_map:
            key_elements = []

            for element_id, info in id_map.items():
                if not isinstance(info, dict):
                    continue

                tag = info.get('tagName', '')
                text = (info.get('innerText', '') or '').strip()[:50]
                styles = info.get('styles', {}) or {}
                viewport = info.get('viewport', {})

                # 提取关键布局属性
                key_styles = {}
                layout_signals = {}

                if styles:
                    layout_props = [
                        'position', 'zIndex', 'overflow', 'overflowX', 'overflowY',
                        'textOverflow', 'whiteSpace', 'margin', 'padding',
                        'width', 'height', 'maxWidth', 'maxHeight', 'minWidth', 'minHeight',
                        'display', 'textAlign', 'verticalAlign', 'lineHeight'
                    ]

                    for prop in layout_props:
                        if prop in styles and styles[prop] and styles[prop] not in ['auto', 'none', '']:
                            key_styles[prop] = styles[prop]

                    # 布局信号
                    if (styles.get('overflow') == 'hidden' or styles.get('overflowX') == 'hidden' or
                        styles.get('overflowY') == 'hidden' or styles.get('textOverflow') == 'ellipsis'):
                        layout_signals['potential_overflow'] = True

                    if 'absolute' in styles.get('position', '') or 'fixed' in styles.get('position', ''):
                        layout_signals['positioned'] = True

                    if styles.get('whiteSpace') == 'nowrap':
                        layout_signals['no_wrap'] = True

                    border_value = styles.get('border', '')
                    if (border_value and border_value != '0px solid rgb(255, 255, 255)' and
                        'solid' in border_value and not border_value.startswith('0px')):
                        layout_signals['has_border'] = True
                        if tag in ['input', 'button', 'textarea']:
                            layout_signals['container_risk'] = True

                # 坐标信息
                coords = {
                    'x': viewport.get('x', 0),
                    'y': viewport.get('y', 0),
                    'width': viewport.get('width', 0),
                    'height': viewport.get('height', 0),
                    'x2': viewport.get('x', 0) + viewport.get('width', 0),
                    'y2': viewport.get('y', 0) + viewport.get('height', 0),

                }

                element_info = {
                    'id': element_id,
                    'tag': tag,
                    'text': text,
                    'position': f"({coords['x']:.0f}, {coords['y']:.0f})",
                    'size': f"{coords['width']:.0f}×{coords['height']:.0f}",
                    'coords': coords,
                    'styles': key_styles,
                    'signals': layout_signals
                }

                if tag == 'img':
                    element_info['src'] = info.get('src')
                    element_info['alt'] = info.get('alt')

                if text or key_styles or tag in ['img', 'svg', 'button', 'input', 'select']:
                    key_elements.append(element_info)

            total_elements = len(key_elements)
            logging.debug(f'UX test page total interactive elements: {total_elements}')
            interactive_count = len([e for e in key_elements if e['tag'] in ['button', 'input', 'select', 'a']])
            image_count = len([e for e in key_elements if e['tag'] in ['img', 'svg']])

            structured_info = f'DOM Summary: {total_elements} elements ({interactive_count} interactive, {image_count} images)'

            if key_elements:
                # Handle elements with layout properties
                elements_with_signals = [e for e in key_elements if e.get('signals')]
                # Handle regular elements without layout signals
                regular_elements = [e for e in key_elements if not e.get('signals')]

                # relevant_elements = (elements_with_signals[:15] + regular_elements[:5])[:20]
                relevant_elements = elements_with_signals + regular_elements

                structured_info += '\nKey Elements:'
                for elem in relevant_elements:
                    coords = elem['coords']
                    element_desc = (
                        f"\n- {elem['tag']}[{elem['size']}] "
                        f"(coords: {coords['x']:.0f},{coords['y']:.0f} → {coords['x2']:.0f},{coords['y2']:.0f})"
                    )

                    if elem['text']:
                        element_desc += f" text: \"{elem['text'][:30]}{'...' if len(elem['text']) > 30 else ''}\""

                    critical_styles = {}
                    for prop in ['overflow', 'textOverflow', 'whiteSpace', 'position', 'border']:
                        if prop in elem['styles']:
                            critical_styles[prop] = elem['styles'][prop]
                    if critical_styles:
                        style_str = '; '.join([f'{k}:{v}' for k, v in critical_styles.items()])
                        element_desc += f' {{{style_str}}}'

                    if elem.get('signals'):
                        signals = []
                        if elem['signals'].get('potential_overflow'):
                            signals.append('MAY_OVERFLOW')
                        if elem['signals'].get('positioned'):
                            signals.append('POSITIONED')
                        if elem['signals'].get('no_wrap'):
                            signals.append('NO_WRAP')
                        if elem['signals'].get('has_border'):
                            signals.append('BORDERED')
                        if elem['signals'].get('container_risk'):
                            signals.append('CONTAINER_RISK')
                        if signals:
                            element_desc += f" [⚠️ {','.join(signals)}]"

                    structured_info += element_desc

            logging.debug(f'structured_info (layout check): {structured_info}')


            return f"""## Layout Analysis Task
    **Input**: {screenshot_count} screenshots (index 0-{screenshot_count-1}) + DOM context with layout signals

    **DOM Reference**: {structured_info}

    **Objective**: {user_case}

     ### Analysis Strategy
    **Primary Method**: Visual analysis of screenshots to identify layout issues
    **Supporting Context**: Use DOM information and layout signals as hints for potential problem areas

    **Layout Signal Meanings**:
    - **MAY_OVERFLOW**: Element has overflow:hidden or text-overflow:ellipsis → check for content clipping
    - **POSITIONED**: Element uses absolute/fixed positioning → check for overlaps or misalignment
    - **NO_WRAP**: Element has white-space:nowrap → check for text extending beyond containers
    - **BORDERED**: Element has visible border → check if content extends outside border boundaries
    - **CONTAINER_RISK**: Bordered input/button element → high risk of text/icon overflow issues

    **Focus Areas**:
    1. **Occlusion**: Elements overlapping, text/buttons hidden behind other elements
    2. **Crowding**: Elements too close together, insufficient spacing
    3. **Text Truncation**: Content cut off, ellipsis (...), text overflow beyond container boundaries
    4. **Alignment**: Misaligned elements, inconsistent positioning
    5. **Container Overflow**: Text or icons extending outside their intended boundaries
    6. **Images**: Broken images, placeholders, loading failures, distorted aspect ratios

    ### Output Requirements
    {LLMPrompt.OUTPUT_FORMAT}

    **Rules**:
    - Use **visual evidence** as primary source, DOM signals as supporting hints
    - For BORDERED and CONTAINER_RISK elements, Use **visual evidence** to carefully examine if text/icons extend beyond the visible border boundaries
    - For any element marked with MAY_OVERFLOW or NO_WRAP in DOM signals, compare the full DOM text content with the visible text in screenshot; if mismatch or truncation occurs (e.g., missing letters, words cut off), mark as overflow.
    - Look for content that appears to "break out" or "overflow" from boxes, buttons, input fields
    - Check if text is cut off at container edges or if icons appear partially outside their containers
    - Output one JSON object per distinct issue
    - If multiple issues exist in the same screenshot, create separate objects for each
    - If no issues are found, output: None

    **Requirements**:
    - Coordinates must be pixel-precise [x1,y1,x2,y2] based on visual observation
    - Suggestions must be actionable and specific
    - When DOM signals indicate potential issues, verify visually and provide precise coordinates
    """

    #     elif is_missing_element_check:
    #         # 为元素缺失检查提供图片元素的基础信息
    #         image_elements_info = ''
    #         if id_map:
    #             image_elements = []
    #             for element_id, info in id_map.items():
    #                 if not isinstance(info, dict):
    #                     continue

    #                 tag = info.get('tagName', '')
    #                 if tag in ['img', 'svg']:
    #                     viewport = info.get('viewport', {})
    #                     styles = info.get('styles', {}) or {}

    #                     img_info = {
    #                         'id': element_id,
    #                         'tag': tag,
    #                         'position': f"({viewport.get('x', 0):.0f}, {viewport.get('y', 0):.0f})",
    #                         'size': f"{viewport.get('width', 0):.0f}×{viewport.get('height', 0):.0f}",
    #                         'src': info.get('src', 'N/A'),
    #                         'alt': info.get('alt', 'N/A')
    #                     }

    #                     # 检查可能的占位图信号
    #                     placeholder_signals = []
    #                     bg_image = styles.get('backgroundImage', '')
    #                     if 'placeholder' in str(img_info['src']).lower() or 'placeholder' in bg_image.lower():
    #                         placeholder_signals.append('PLACEHOLDER_SRC')
    #                     if bg_image and bg_image != 'none':
    #                         placeholder_signals.append('HAS_BACKGROUND')
    #                     if viewport.get('width', 0) == viewport.get('height', 0):  # 正方形可能是占位图
    #                         placeholder_signals.append('SQUARE_ASPECT')

    #                     if placeholder_signals:
    #                         img_info['signals'] = placeholder_signals

    #                     image_elements.append(img_info)

    #             if image_elements:
    #                 image_elements_info = f'\nImage Elements Found: {len(image_elements)}\n'
    #                 for img in image_elements[:10]:  # 限制显示数量
    #                     desc = f"- {img['tag']}@{img['position']} [{img['size']}]"
    #                     if img['src'] != 'N/A':
    #                         desc += f" src=\"{img['src'][:50]}{'...' if len(img['src']) > 50 else ''}\""
    #                     if img.get('signals'):
    #                         desc += f" [⚠️ {','.join(img['signals'])}]"
    #                     image_elements_info += f'\n{desc}'
    #             else:
    #                 image_elements_info = '\nNo image elements detected in DOM.'

    #             logging.debug(f'image_elements_info: {image_elements_info}')
    #         return f"""## Missing Image Element Analysis Task
    # **Input**: Visual analysis with DOM context - {screenshot_count} screenshots (index 0-{screenshot_count-1})

    # **Objective**: {user_case}

    # **Image Reference**: {image_elements_info}

    # ### Output Requirements
    #     {LLMPrompt.OUTPUT_FORMAT}

    # **Rules**:
    # - Focus on visual evidence, use DOM signals as supporting hints
    # - Pay special attention to elements marked with ⚠️ placeholder signals
    # - For gray blocks or obvious placeholders, identify them as missing content
    # - If unsure about rendering vs loading state, provide evidence-based judgment
    # - For multiple issues in one screenshot, create separate objects for each
    # - If no issues found, output strictly: None (no explanation needed)

    # **Requirements**:
    # - Coordinates must be pixel-precise [x1,y1,x2,y2] based on visual observation
    # - Clearly identify what type of content appears to be missing
    # - Fix suggestions must be actionable and specific
    #             """

    #     elif is_text_check:
    #         return f"""## Text Typography Analysis Task
    # **Input**: Visual analysis with DOM context - {screenshot_count} screenshots (index 0-{screenshot_count-1})

    # **Objective**: {user_case}

    # ### Output Requirements
    #     {LLMPrompt.OUTPUT_FORMAT}

    # **Requirements**:
    # - Coordinates must be pixel-precise [x1,y1,x2,y2] based on visual observation
    # - Clearly describe the specific style or layout inconsistency observed
    # - Suggestions must be actionable and specific (e.g., "Increase line-height from 1.1 to 1.4 for better readability")
    #         """
    #     else:
            # 默认情况，处理未知的检查类型
    #         return f"""## General Content Analysis Task
    # **Input**: Visual analysis with DOM context - {screenshot_count} screenshots (index 0-{screenshot_count-1})

    # **Objective**: {user_case}

    # ### Output Requirements
    #     {LLMPrompt.OUTPUT_FORMAT}

    # **Requirements**:
    # - Coordinates must be pixel-precise [x1,y1,x2,y2] based on visual observation
    # - Clearly describe any issues found
    # - Suggestions must be actionable and specific
    #         """

    async def _get_llm_response(self, prompt: str, page_img: bool, browser_screenshot=None):
        if page_img and browser_screenshot:
            return await self.llm.get_llm_response(
                LLMPrompt.page_default_prompt,
                prompt,
                images=browser_screenshot,
            )
        return await self.llm.get_llm_response(LLMPrompt.page_default_prompt, prompt)
