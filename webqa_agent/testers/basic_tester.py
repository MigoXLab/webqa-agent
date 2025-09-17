import asyncio
import logging
import socket
import ssl
from datetime import datetime
from urllib.parse import urlparse

import requests
from playwright.async_api import Page

from webqa_agent.data.test_structures import SubTestReport, SubTestResult, TestStatus, SubTestScreenshot, SubTestStep
from webqa_agent.utils import Display
from webqa_agent.utils import i18n
from webqa_agent.utils.log_icon import icon

class WebAccessibilityTest:
    def __init__(self, report_config: dict = None):
        self.language = report_config.get("language", "zh-CN") if report_config else "zh-CN"
        self.localized_strings = {
            'zh-CN': i18n.get_lang_data('zh-CN').get('testers', {}).get('basic', {}),
            'en-US': i18n.get_lang_data('en-US').get('testers', {}).get('basic', {}),
        }
    
    def _get_text(self, key: str) -> str:
        """Get localized text for the given key."""
        return self.localized_strings.get(self.language, {}).get(key, key)

    async def run(self, url: str, sub_links: list) -> SubTestResult:
        logging.debug(f"Starting combined HTTPS and status check for {url}")
        result = SubTestResult(name=self._get_text('accessibility_check'))

        with Display.display(self._get_text('basic_test_display') + result.name):
            try:
                # check the main link
                main_valid, main_reason, main_expiry_date = await self.check_https_expiry(url)
                main_status = await self.check_page_status(url)
                main_url_result = {
                    "url": url,
                    "status": main_status,
                    "https_valid": main_valid,
                    "https_reason": main_reason,
                    "https_expiry_date": main_expiry_date,
                }

                # check sub links
                sub_link_results = []
                failed_links = 0
                total_links = 1  # include main link

                if sub_links:
                    total_links += len(sub_links)
                    for link in sub_links:
                        sub_result = {
                            "url": link,
                            "status": None,
                            "https_valid": None,
                            "https_reason": None,
                            "https_expiry_date": None,
                        }
                        try:
                            sub_result["https_valid"], sub_result["https_reason"], sub_result["https_expiry_date"] = (
                                await self.check_https_expiry(link)
                            )
                        except Exception as e:
                            logging.error(f"Failed to check HTTPS for {link}: {str(e)}")
                            sub_result["https"] = {"error": str(e)}
                        try:
                            sub_result["status"] = await self.check_page_status(link)
                        except Exception as e:
                            logging.error(f"Failed to check status for {link}: {str(e)}")
                            sub_result["status"] = {"error": str(e)}
                        sub_link_results.append(sub_result)

                # check if all passed
                def is_passed(item):
                    https_valid = item["https_valid"]
                    status_code = item["status"]
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
                error_message = f"An error occurred in WebAccessibilityTest: {str(e)}"
                logging.error(error_message)
                result.status = TestStatus.FAILED
                result.messages = {"error": error_message}

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

                expiry_date = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
                formatted_expiry_date = expiry_date.strftime("%Y-%m-%d %H:%M:%S")
                result_valid = datetime.now() < expiry_date
                result_expiry_date = formatted_expiry_date
                logging.debug(f"HTTPS certificate is {'valid' if result_valid else 'expired'} for {url}")
            except ssl.SSLCertVerificationError as ssl_error:
                result_valid = False
                result_reason = ssl_error
                logging.error(f"SSL verification error: {ssl_error}")
            except Exception as e:
                result_valid = False
                result_reason = e
                logging.error(f"Error checking certificate: {str(e)}")
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
            logging.debug(f"Page {url} returned status {status_code}")
            return status_code
        except requests.RequestException as e:
            error_message = f"Failed to load page {url}: {str(e)}"
            logging.error(error_message)
            raise Exception(error_message)


class PageButtonTest:

    def __init__(self, report_config: dict = None):
        self.language = report_config.get("language", "zh-CN") if report_config else "zh-CN"
        self.localized_strings = {
            'zh-CN': i18n.get_lang_data('zh-CN').get('testers', {}).get('basic', {}),
            'en-US': i18n.get_lang_data('en-US').get('testers', {}).get('basic', {}),
        }

    def _get_text(self, key: str) -> str:
        """Get localized text for the given key."""
        return self.localized_strings.get(self.language, {}).get(key, key)

    async def run(self, url: str, page: Page, clickable_elements: dict, **kwargs) -> SubTestResult:
        """Run page button test.

        Args:
            url: target url
            page: playwright page
            clickable_elements: list of clickable elements

        Returns:
            SubTestResult containing test results and click screenshots
        """

        result = SubTestResult(name=self._get_text('clickable_element_check'))
        logging.info(f"{icon['running']} Running Sub Test: {result.name}")
        sub_test_results = []
        with Display.display(self._get_text('basic_test_display') + result.name):
            try:
                status = TestStatus.PASSED
                from webqa_agent.actions.click_handler import ClickHandler

                click_handler = ClickHandler()
                await click_handler.setup_listeners(page)

                # count total passed / failed
                total, total_failed = 0, 0

                if clickable_elements:
                    for highlight_id, element in clickable_elements.items():
                        # Run single test with the provided browser configuration
                        element_text = element.get("selector", "Unknown")
                        logging.info(f"Testing clickable element {highlight_id}...")

                        try:
                            current_url = page.url
                            if current_url != url:
                                await page.goto(url)
                                await asyncio.sleep(0.5)  # Wait for page to stabilize

                            screenshots = []
                            click_result = await click_handler.click_and_screenshot(page, element, highlight_id)
                            if click_result.get("screenshot_after"):
                                scr = click_result["screenshot_after"]
                                if isinstance(scr, str):
                                    screenshots.append(SubTestScreenshot(type="base64", data=scr))
                                elif isinstance(scr, dict):
                                    screenshots.append(SubTestScreenshot(**scr))
                            if click_result.get("new_page_screenshot"):
                                scr = click_result["new_page_screenshot"]
                                if isinstance(scr, str):
                                    screenshots.append(SubTestScreenshot(type="base64", data=scr))
                                elif isinstance(scr, dict):
                                    screenshots.append(SubTestScreenshot(**scr))

                            business_success = click_result["success"]
                            step = SubTestStep(
                                id=int(highlight_id), description=f"{self._get_text('click_element')}: {element_text}", screenshots=screenshots
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

                logging.info(f"{icon['check']} Sub Test Completed: {result.name}")
                result.report.append(
                    SubTestReport(
                        title=self._get_text('traversal_test_results'),
                        issues=f"{self._get_text('clickable_elements_count')}{total}{self._get_text('click_failed_count')}{total_failed}",
                    )
                )

                logging.info(f"{icon['check']} Sub Test Completed: {result.name}")

            except Exception as e:
                error_message = f"PageButtonTest error: {str(e)}"
                logging.error(error_message)
                status = TestStatus.FAILED
                raise

            result.status = status
            result.steps = sub_test_results
            return result
