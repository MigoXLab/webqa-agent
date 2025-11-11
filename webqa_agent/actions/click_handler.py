import asyncio
import logging
from typing import Any, Dict, Optional

from playwright.async_api import Page

from webqa_agent.actions.action_handler import ActionHandler


class ClickHandler:
    """Enhanced click handler with multiple locating strategies."""

    def __init__(self):
        self.console_errors = []
        self.network_errors = []
        self.response_errors = []

    async def setup_listeners(self, page: Page):
        """Setup console and network error listeners."""

        # Console error listener
        async def on_console(msg):
            if msg.type in ["error", "warning"]:
                error_info = {
                    "type": msg.type,
                    "text": msg.text,
                    "location": msg.location,
                    "timestamp": asyncio.get_event_loop().time(),
                }
                self.console_errors.append(error_info)
                logging.debug(f"Console {msg.type}: {msg.text}")

        # Network error listener
        async def on_request_failed(request):
            IGNORE_ERRORS = [
                "net::ERR_ABORTED",
                "net::ERR_CACHE_MISS",
            ]
            if request.failure not in IGNORE_ERRORS:
                error_info = {
                    "url": request.url,
                    "method": request.method,
                    "failure": request.failure,
                }
                self.network_errors.append(error_info)
                logging.debug(f"Network error: {request.url} - {request.failure}")

        # Response error listener (4xx, 5xx)
        async def on_response(response):
            if response.status >= 400:
                error_info = {
                    "url": response.url,
                    "status": response.status,
                    "status_text": response.status_text,
                }
                self.response_errors.append(error_info)
                logging.debug(f"Response error: {response.url} - {response.status}")

        # Attach listeners
        page.on("console", on_console)
        page.on("requestfailed", on_request_failed)
        page.on("response", on_response)

    async def click_and_screenshot(
        self, page: Page, element_info: Dict[str, Any], element_index: int = 0
    ) -> Dict[str, Any]:
        """Click an element and monitor for errors.

        Args:
            page: Playwright page object
            element_info: Element information from clickable_elements_detection
            element_index: Index of the element being tested

        Returns:
            Dictionary containing click result and any errors
        """

        # Clear previous errors
        action_handler = ActionHandler()
        action_handler.page = page

        click_result = {
            "element": element_info,
            "success": False,
            "error": None,
            "console_errors": [],
            "network_errors": [],
            "response_errors": [],
            "screenshot_before": None,
            "screenshot_after": None,
            "new_page_screenshot": None,
            "click_method": None,
            "click_coordinates": None,
            "has_new_page": False,
        }

        selector = element_info.get("selector")
        xpath = element_info.get("xpath")
        click_success = False

        logging.debug(f"Clicking element: {element_info}")

        context = page.context
        new_page = None

        def handle_new_page(page_obj):
            nonlocal new_page
            new_page = page_obj
            logging.debug(f"New page detected: {page_obj.url}")

        context.on("page", handle_new_page)

        click_success = await self._perform_click(page, selector, xpath, click_result)

        if click_success:
            click_result["success"] = True
            await asyncio.sleep(2)
            if new_page:
                click_result["has_new_page"] = True
                try:
                    await new_page.wait_for_load_state("networkidle", timeout=30000)

                    new_page_action_handler = ActionHandler()
                    new_page_action_handler.page = new_page
                    screenshot_b64 = await new_page_action_handler.b64_page_screenshot(
                        file_name=f"element_{element_index}_new_page",
                        context="test"
                    )
                    click_result["new_page_screenshot"] = screenshot_b64
                    logging.debug("New page screenshot saved")

                except Exception as e:
                    click_result["error"] = f"Failed to handle new page: {e}"
                    logging.warning(f"Failed to handle new page: {e}")

                await page.wait_for_load_state("networkidle", timeout=30000)
            else:
                screenshot_b64 = await action_handler.b64_page_screenshot(
                    file_name=f"element_{element_index}_after_click",
                    context="test"
                )
                click_result["screenshot_after"] = screenshot_b64
                logging.debug("After click screenshot saved")

        else:
            click_result["error"] = f"Failed to click element with all strategies. Element: '{element_info}'"
            logging.warning(f"Failed to click element: '{element_info}'")

        context.remove_listener("page", handle_new_page)
        await self._close_popups(page)

        return click_result

    async def _perform_click(
        self, page: Page, selector: Optional[str], xpath: Optional[str], click_result: Dict
    ) -> bool:
        click_timeout = 10000

        if xpath:
            locator_str = f"xpath={xpath}"
            try:
                await self._scroll_into_view_safely(page, locator_str)
                await page.click(locator_str, timeout=click_timeout)
                click_result["click_method"] = locator_str
                logging.debug(f"Successfully clicked using xpath: {xpath}")
                return True
            except Exception as e:
                logging.debug(f"XPath click failed: {e}")
                click_result["error"] = str(e)

        if selector:
            try:
                await self._scroll_into_view_safely(page, selector)
                await page.click(selector, timeout=click_timeout)
                click_result["click_method"] = selector
                logging.debug(f"Successfully clicked using selector: {selector}")
                return True
            except Exception as e:
                logging.debug(f"Selector click failed: {e}")
                click_result["error"] = str(e)

        try:
            element_handle = None
            if selector:
                try:
                    element_handle = await page.query_selector(selector)
                except Exception as e:
                    logging.debug(f"query_selector failed for selector: {e}")

            if not element_handle and xpath:
                try:
                    element_handle = await page.query_selector(f"xpath={xpath}")
                except Exception as e:
                    logging.debug(f"query_selector failed for xpath: {e}")

            if element_handle:
                await page.evaluate("el => el.click()", element_handle)
                click_result["click_method"] = f"js_evaluate_click:{selector or xpath}"
                logging.debug("Successfully clicked using JS evaluate")
                return True
            else:
                click_result["error"] = "No element handle found for JS click"

        except Exception as e:
            logging.debug(f"JS click failed: {e}")
            click_result["error"] = f"All click strategies failed. Last error: {e}"

        return False

    @staticmethod
    async def _scroll_into_view_safely(page: Page, locator: str):
        try:
            await page.locator(locator).scroll_into_view_if_needed(timeout=3000)
        except Exception as e:
            logging.debug(f"scroll_into_view_if_needed failed for {locator}: {e}")

    async def _close_popups(self, page: Page):
        try:
            popup_detected = await self._detect_popup(page)

            if not popup_detected:
                logging.debug("No popup detected, skipping close operation")
                return

            logging.debug("Popup detected, attempting to close...")

            close_selectors = [
                '[data-dismiss="modal"]',
                '[data-bs-dismiss="modal"]',
                ".modal-close",
                ".close",
                ".btn-close",
                ".fa-times",
                ".fa-close",
                ".icon-close",
                ".icon-x",
                '[aria-label*="close"]',
                '[aria-label*="Close"]',
                '[title*="close"]',
                '[title*="Close"]',
                'button:has-text("×")',
                'button:has-text("✕")',
                'button:has-text("Close")',
                'button:has-text("关闭")',
                ".modal-backdrop",
                ".overlay",
            ]

            popup_closed = False
            for selector in close_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        is_visible = await element.is_visible()
                        if is_visible:
                            await element.click(timeout=2000)
                            logging.debug(f"Closed popup using selector: {selector}")
                            popup_closed = True
                            await asyncio.sleep(0.3)  # Wait for close animation
                            break
                except Exception:
                    continue

            if not popup_closed:
                try:
                    await page.keyboard.press("Escape")
                    logging.debug("Attempted to close popup with ESC key")
                    await asyncio.sleep(0.3)
                except Exception:
                    pass

        except Exception as e:
            logging.debug(f"Popup close attempt failed: {e}")

    async def _detect_popup(self, page: Page):
        try:
            popup_selectors = [
                ".modal.show",
                ".modal.in",
                '.modal[style*="display: block"]',
                ".dialog",
                ".popup",
                ".overlay.show",
                '.overlay[style*="display: block"]',
                '[role="dialog"]',
                '[role="alertdialog"]',
                ".fancybox-overlay",
                ".ui-dialog",
                ".sweet-alert",
                ".swal-overlay",
                '[style*="z-index"]',
            ]

            for selector in popup_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        is_visible = await element.is_visible()
                        if is_visible:
                            bbox = await element.bounding_box()
                            if bbox and bbox["width"] > 100 and bbox["height"] > 100:
                                logging.debug(f"Popup detected with selector: {selector}")
                                return True
                except Exception:
                    continue

            backdrop_selectors = [".modal-backdrop", ".overlay", '[class*="backdrop"]']

            for selector in backdrop_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        is_visible = await element.is_visible()
                        if is_visible:
                            logging.debug(f"Backdrop detected with selector: {selector}")
                            return True
                except Exception:
                    continue

            return False

        except Exception as e:
            logging.debug(f"Popup detection failed: {e}")
            return False

    def get_error_summary(self) -> Dict[str, Any]:
        """Get a summary of all errors collected."""
        return {
            "total_console_errors": len(self.console_errors),
            "total_network_errors": len(self.network_errors),
            "total_response_errors": len(self.response_errors),
            "console_errors": self.console_errors,
            "network_errors": self.network_errors,
            "response_errors": self.response_errors,
        }

    def reset_errors(self):
        """Reset all error collections."""
        self.console_errors.clear()
        self.network_errors.clear()
        self.response_errors.clear()
