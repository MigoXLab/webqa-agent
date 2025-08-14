import ast
import asyncio
import json
import logging
import uuid
from typing import List

from html2text import html2text
from playwright.async_api import Page

from webqa_agent.actions.action_handler import ActionHandler
from webqa_agent.actions.scroll_handler import ScrollHandler
from webqa_agent.data.test_structures import SubTestReport, SubTestResult, SubTestScreenshot, SubTestStep, TestStatus
from webqa_agent.llm.llm_api import LLMAPI
from webqa_agent.llm.prompt import LLMPrompt
from webqa_agent.utils.log_icon import icon
from webqa_agent.utils import Display


class PageTextTest:

    def __init__(self, llm_config: dict, user_cases: List[str] = None):
        self.llm_config = llm_config
        self.user_cases = user_cases or LLMPrompt.TEXT_USER_CASES
        self.llm = LLMAPI(self.llm_config)

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
        result = SubTestResult(name="文本检查")
        logging.info(f"{icon['running']} Running Sub Test: {result.name}")
        
        with Display.display('用户体验测试 - ' + result.name):
            try:
                # 创建ActionHandler用于截图
                action_handler = ActionHandler()
                action_handler.page = page
                await asyncio.sleep(2)

                # 检查页面是否空白
                is_blank = await page.evaluate("document.body.innerText.trim() === ''")
                if is_blank:
                    logging.error("page is blank, no visible content")
                    result.status = TestStatus.FAILED
                    result.messages = {"page": "页面白屏，没有任何可见内容"}
                    return result

                logging.debug("page is not blank, start crawling page content")

                # 获取页面文本内容
                page_text = html2text(await page.content())
                for frame in page.frames:
                    if frame != page.main_frame:
                        page_text += await self.get_iframe_content(frame)

                # 运行每个用例
                for user_case in self.user_cases:
                    logging.debug(f"page_text: {page_text}")
                    prompt = self._build_prompt(page_text, user_case)

                    # 确保LLM已初始化
                    if not hasattr(self.llm, "_client") or self.llm._client is None:
                        await self.llm.initialize()

                    test_page_content = await self.llm.get_llm_response(LLMPrompt.page_default_prompt, prompt)

                    has_issues = test_page_content and "None" not in str(test_page_content)
                    if has_issues:
                        result.status = TestStatus.FAILED 
                        issues = test_page_content
                    else:
                        result.status = TestStatus.PASSED
                        issues = "没有发现错别字"
                    result.report.append(
                        SubTestReport(
                            title=user_case[:4],
                            issues=issues,
                        )
                    )
                logging.info(f"{icon['check']} Sub Test Completed: {result.name}")

            except Exception as e:
                error_message = f"PageTextTest error: {str(e)}"
                logging.error(error_message)
                result.status = TestStatus.FAILED
                result.messages = {"page": str(e)}
                raise
            
            return result

    @staticmethod
    def _build_prompt(page_text: str, user_case: str) -> str:
        """构建LLM提示."""
        return f"""任务描述：根据提供的网页内容用户用例，检查是否存在任何错别字，或者英文语法错误。如果发现错误，请按照指定的JSON格式输出结果。
                输入信息：
                - 网页内容：${page_text}
                - 用户用例：${user_case}
                输出要求：
                - 如果没有发现错误，请只输出 None ，不要包含任何解释。
                - 如果发现了错误，请使用以下JSON格式输出：  {{'error': '', 'reason': ''}}； error表示错误点，reason给出具体错误的原因和更改结果。
                """


class PageContentTest:

    def __init__(self, llm_config: dict, user_cases: List[str] = None):
        self.llm_config = llm_config
        self.user_cases = user_cases or LLMPrompt.CONTENT_USER_CASES
        self.llm = LLMAPI(self.llm_config)

    async def run(self, page: Page, **kwargs) -> SubTestResult:
        """run single page content test
        Args:
            page: playwright page
            **kwargs: additional arguments

        Returns:
            SubTestResult containing test results and screenshots
        """
        result = SubTestResult(name=f"网页内容检查_{page.viewport_size['width']}x{page.viewport_size['height']}")
        logging.info(f"{icon['running']} Running Sub Test: {result.name}")

        with Display.display('用户体验测试 - ' + result.name):
            try:
                if not hasattr(self.llm, "_client") or self.llm._client is None:
                    await self.llm.initialize()

                page_identifier = str(int(uuid.uuid4().int) % 10000)
                _scroll = ScrollHandler(page)
                logging.info("Scrolling the page...")
                browser_screenshot = await _scroll.scroll_and_crawl(
                    scroll=True, max_scrolls=10, page_identifier=page_identifier
                )
                id_map = {}
                # dp = DeepCrawler(page)
                # _, id_map = await dp.crawl(highlight=True, viewport_only=True)

                page_img = True
                id_counter = 0
                overall_status = TestStatus.PASSED
                for user_case in self.user_cases:
                    prompt = self._build_prompt(user_case, id_map)
                    logging.info(f"Vision model: evaluating use case '{user_case[:4]}'...")
                    test_page_content = await self._get_llm_response(prompt, page_img, browser_screenshot)

                    # parse LLM response
                    summary_text = None
                    issues_list = []
                    issues_text = "无发现问题"  # initialize with default value
                    case_status = TestStatus.PASSED

                    logging.debug(f"LLM response for user case '{user_case[:4]}...': {test_page_content}")

                    if test_page_content and "None" not in str(test_page_content):
                        try:
                            parsed = json.loads(test_page_content)
                        except Exception:
                            try:
                                parsed = ast.literal_eval(test_page_content)
                                logging.debug(f"Parsed LLM output: {parsed}")
                            except Exception:
                                logging.warning("Unable to parse LLM output as JSON, keep raw text")
                                parsed = None

                        if isinstance(parsed, list):
                            for item in parsed:
                                if isinstance(item, dict) and "summary" in item:
                                    summary_text = item.get("summary")
                                elif isinstance(item, str):
                                    # accept leading plain string like "summary: ..."
                                    if summary_text is None:
                                        summary_text = item
                                elif isinstance(item, dict):
                                    issues_list.append(item)
                        elif isinstance(parsed, dict):
                            summary_text = parsed.get("summary")
                            issues_candidate = {k: v for k, v in parsed.items() if k != "summary"}
                            if issues_candidate:
                                issues_list.append(issues_candidate)
                        else:
                            # if not structured, use raw text as summary
                            summary_text = str(test_page_content) if test_page_content else None

                        # determine case status: any discovered issues are warnings
                        if issues_list or (summary_text and str(summary_text).strip()):
                            case_status = TestStatus.WARNING

                        for idx, issue in enumerate(issues_list):
                            # collect issue info for report
                            issue_desc = issue.get("issue") or issue.get("description") or str(issue)
                            suggestion = issue.get("suggestion")

                            # if screenshot index, append corresponding screenshot and create step
                            screenshot_idx = issue.get("screenshotid", issue.get("id"))
                            if isinstance(screenshot_idx, int) and 1 <= screenshot_idx <= len(browser_screenshot):
                                screenshot_data = browser_screenshot[screenshot_idx - 1]

                                screenshots = []
                                if isinstance(screenshot_data, str):
                                    screenshots.append(SubTestScreenshot(type="base64", data=screenshot_data))
                                elif isinstance(screenshot_data, dict):
                                    screenshots.append(SubTestScreenshot(**screenshot_data))

                                # step status: all discovered issues are warnings
                                step_status = TestStatus.WARNING
                                result.steps.append(SubTestStep(
                                    id=int(id_counter + 1),
                                    description=user_case[:4] + ": " + issue_desc,
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
                        issues_text = "无发现问题"

                    result.report.append(SubTestReport(title=user_case[:4], issues=issues_text))
                    # aggregate overall status: any WARNING -> WARNING; else PASSED
                    if case_status == TestStatus.WARNING and overall_status != TestStatus.WARNING:
                        overall_status = TestStatus.WARNING
                logging.info(f"{icon['check']} Sub Test Completed: {result.name}")
                result.status = overall_status
            except Exception as e:
                error_message = f"PageContentTest error: {str(e)}"
                logging.error(error_message)
                result.status = TestStatus.FAILED
                result.messages = {"page": str(e)}
                raise

            return result

    @staticmethod
    def _build_prompt(user_case: str, id_map: dict) -> str:
        return f"""任务描述：根据提供的网页截图以及用户用例，检查是否存在任何错误。如果发现错误，请按照指定的文本格式输出结果。
                输入信息：
                - 用户用例：${user_case}
                - 网页截图
                - 网页dom元素信息: ${id_map}
                输出要求：
                ${LLMPrompt.OUTPUT_FORMAT}
                """

    async def _get_llm_response(self, prompt: str, page_img: bool, browser_screenshot=None):
        if page_img and browser_screenshot:
            return await self.llm.get_llm_response(
                LLMPrompt.page_default_prompt,
                prompt,
                images=browser_screenshot,
            )
        return await self.llm.get_llm_response(LLMPrompt.page_default_prompt, prompt)
