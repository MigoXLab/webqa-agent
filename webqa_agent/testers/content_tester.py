import uuid
import json
import ast
import asyncio
from typing import List
from html2text import html2text
from webqa_agent.llm.llm_api import LLMAPI
from webqa_agent.llm.prompt import LLMPrompt
from webqa_agent.actions.scroll_handler import ScrollHandler
from webqa_agent.actions.action_handler import ActionHandler
from webqa_agent.crawler.deep_crawler import DeepCrawler
from playwright.async_api import Page
from webqa_agent.data.test_structures import SubTestResult, SubTestStep, SubTestScreenshot, SubTestReport, TestStatus, SubTestAction
import logging


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
        """
        Runs a test to check the text content of a web page and identifies any issues based on predefined user cases.
        """
        test_name = f"错别字检查"

        result = SubTestResult(name=test_name)

        try:
            # 创建ActionHandler用于截图
            action_handler = ActionHandler()
            action_handler.page = page

            # 检查页面是否空白
            is_blank = await page.evaluate("document.body.innerText.trim() === ''")
            if is_blank:
                logging.error("page is blank, no visible content")
                result.status = TestStatus.FAILED
                result.messages = {"page": "页面白屏，没有任何可见内容"}
                return result

            logging.info("page is not blank, start crawling page content")

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
                if not hasattr(self.llm, '_client') or self.llm._client is None:
                    await self.llm.initialize()

                test_page_content = await self.llm.get_llm_response(LLMPrompt.page_default_prompt, prompt)

                # 如果LLM返回实际问题内容(不是None)，标记为发现问题但测试完成
                has_issues = test_page_content and "None" not in str(test_page_content)
                if has_issues:
                    result.status = TestStatus.FAILED  # 发现了文本错误
                    issues = test_page_content
                else:
                    result.status = TestStatus.PASSED
                    issues = "没有发现错别字" 
                result.report.append(SubTestReport(
                    title=user_case[:4],
                    issues=issues,
                ))

        except Exception as e:
            error_message = f"PageTextTest error: {str(e)}"
            logging.error(error_message)
            result.status = TestStatus.FAILED
            result.messages = {"page": str(e)}

        return result

    @staticmethod
    def _build_prompt(page_text: str, user_case: str) -> str:
        """构建LLM提示"""
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
        test_name = f"网页内容检查_{page.viewport_size['width']}x{page.viewport_size['height']}"
        result = SubTestResult(name=test_name)
        logging.info(
            f"Testing with browser configuration: {page.viewport_size['width']}x{page.viewport_size['height']}")

        try:
            if not hasattr(self.llm, '_client') or self.llm._client is None:
                await self.llm.initialize()

            page_identifier = str(int(uuid.uuid4().int) % 10000)
            _scroll = ScrollHandler(page)
            browser_screenshot = await _scroll.scroll_and_crawl(
                scroll=True,
                max_scrolls=10,
                page_identifier=page_identifier
            )
            id_map = {}
            # dp = DeepCrawler(page)
            # _, id_map = await dp.crawl(highlight=True, viewport_only=True)

            page_img = True
            id_counter = 0
            for user_case in self.user_cases:
                prompt = self._build_prompt(user_case, id_map)
                test_page_content = await self._get_llm_response(
                    prompt, page_img, browser_screenshot
                )

                # parse LLM response
                summary_text = None
                issues_list = []

                logging.debug(f"LLM response for user case '{user_case[:20]}...': {test_page_content}")

                if test_page_content and "None" not in str(test_page_content):
                    try:
                        parsed = json.loads(test_page_content)
                    except Exception:
                        try:
                            parsed = ast.literal_eval(test_page_content)
                        except Exception:
                            logging.warning("Unable to parse LLM output as JSON, keep raw text")
                            parsed = None

                    if isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, dict) and "summary" in item:
                                summary_text = item.get("summary")
                            elif isinstance(item, str):
                                summary_text = item if summary_text is None else summary_text
                            elif isinstance(item, dict):
                                issues_list.append(item)
                    elif isinstance(parsed, dict):
                        summary_text = parsed.get("summary")
                        issues_candidate = {k: v for k, v in parsed.items() if k != "summary"}
                        if issues_candidate:
                            issues_list.append(issues_candidate)
                    else:
                        # 非结构化，直接当 summary
                        summary_text = str(test_page_content) if test_page_content else None

                    # 如果有发现问题，则将测试结果标记为失败
                    if issues_list or (summary_text and summary_text.strip()):
                        result.status = TestStatus.FAILED

                    # 组织 steps 信息和收集 issue 信息
                    all_issues = []
                    if summary_text:
                        all_issues.append(f"总结: {summary_text}")
                    
                    for idx, issue in enumerate(issues_list):
                        # collect issue info for report
                        issue_desc = issue.get("issue") or issue.get("description") or str(issue)
                        suggestion = issue.get("suggestion")
                        if suggestion:
                            all_issues.append(f"问题: {issue_desc} | 建议: {suggestion}")
                        else:
                            all_issues.append(f"问题: {issue_desc}")

                        # if screenshot index, append corresponding screenshot and create step
                        screenshot_idx = issue.get("id")
                        if isinstance(screenshot_idx, int) and 1 <= screenshot_idx <= len(browser_screenshot):
                            screenshot_data = browser_screenshot[screenshot_idx - 1]
                            
                            screenshot = SubTestScreenshot(
                                type="base64",
                                data=screenshot_data
                            )

                            result.steps.append(SubTestStep(
                                id=int(id_counter+1),
                                description=user_case[:4]+": "+ issue_desc,
                                modelIO=suggestion,
                                screenshots=[screenshot],
                                status=TestStatus.FAILED if suggestion else TestStatus.PASSED
                            ))
                            id_counter += 1
                
                issues_text = "; ".join(all_issues) if all_issues else "无发现问题"
                
                result.report.append(SubTestReport(
                    title=user_case[:4],
                    issues=issues_text
                ))

        except Exception as e:
            error_message = f"PageContentTest error: {str(e)}"
            logging.error(error_message)
            result.status = TestStatus.FAILED
            result.messages = {"page": str(e)}

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


class PageButtonTest:

    @staticmethod
    async def run(url: str, page: Page, clickable_elements: list, **kwargs) -> SubTestResult:
        """
        run page button test
        
        Args:
            url: target url
            page: playwright page
            clickable_elements: list of clickable elements

        Returns:
            SubTestResult containing test results and click screenshots
        """

        result = SubTestResult(name="可点击元素遍历检查")
        sub_test_results = []
        try:
            status = TestStatus.PASSED
            from webqa_agent.actions.click_handler import ClickHandler
            click_handler = ClickHandler()
            await click_handler.setup_listeners(page)

            # count total passed / failed
            total, total_failed = 0, 0

            if clickable_elements:
                for i, element in enumerate(clickable_elements):
                    # Run single test with the provided browser configuration
                    element_text = element.get('selector', 'Unknown')
                    logging.info(f"Testing clickable element {i + 1}: {element_text}")

                    try:
                        current_url = page.url
                        if current_url != url:
                            await page.goto(url)
                            await asyncio.sleep(0.5)  # Wait for page to stabilize

                        screenshots = []
                        click_result = await click_handler.click_and_screenshot(page, element, i)
                        if click_result.get('screenshot_after'):
                            scr = click_result['screenshot_after']
                            if isinstance(scr, str):
                                screenshots.append(SubTestScreenshot(type="base64", data=scr))
                            elif isinstance(scr, dict):
                                screenshots.append(SubTestScreenshot(**scr))
                        if click_result.get('new_page_screenshot'):
                            scr = click_result['new_page_screenshot']
                            if isinstance(scr, str):
                                screenshots.append(SubTestScreenshot(type="base64", data=scr))
                            elif isinstance(scr, dict):
                                screenshots.append(SubTestScreenshot(**scr))

                        business_success = click_result['success']
                        step = SubTestStep(
                            id=int(i+1),
                            description=f"点击元素: {element_text}",
                            screenshots=screenshots
                        )
                        # Determine step status based on business result
                        step_status = TestStatus.PASSED if business_success else TestStatus.FAILED
                        step.status = step_status  # record status for each step
                        total += 1
                        if step_status != TestStatus.PASSED:
                            total_failed += 1
                            status = TestStatus.FAILED

                        # Brief pause between clicks
                        await asyncio.sleep(0.5)

                    except Exception as e:
                        error_message = f"PageButtonTest error: {str(e)}"
                        logging.error(error_message)
                        step.status = TestStatus.FAILED
                        step.errors = str(e)
                        total_failed += 1
                        status = TestStatus.FAILED
                    finally:
                        sub_test_results.append(step)

            result.report.append(SubTestReport(
                title="遍历测试结果",
                issues=f"可点击元素{total}个，点击行为失败{total_failed}个",
            ))

        except Exception as e:
            error_message = f"PageButtonTest error: {str(e)}"
            logging.error(error_message)
            status = TestStatus.FAILED

        result.status = status
        result.steps = sub_test_results
        return result
