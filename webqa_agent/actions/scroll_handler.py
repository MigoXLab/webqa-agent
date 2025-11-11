import asyncio
import logging
import time

from playwright.async_api import Page

from webqa_agent.actions.action_handler import ActionHandler


class ScrollHandler:
    def __init__(self, page: Page):
        self.page = page
        self.id_counter = 1

        self._action_handler = ActionHandler()
        self._action_handler.page = page

    async def detect_scrollable_containers(self):
        scrollable_containers_script = """
        (function() {
            function findScrollableContainers() {
                const elements = document.querySelectorAll('*');
                const scrollableContainers = [];

                for (let element of elements) {
                    if (element === document.body || element === document.documentElement) {
                        continue;
                    }

                    const style = window.getComputedStyle(element);
                    const hasScrollableContent = element.scrollHeight > element.clientHeight ||
                                               element.scrollWidth > element.clientWidth;
                    const hasScrollableStyle = style.overflow === 'auto' ||
                                             style.overflow === 'scroll' ||
                                             style.overflowY === 'auto' ||
                                             style.overflowY === 'scroll' ||
                                             style.overflowX === 'auto' ||
                                             style.overflowX === 'scroll';

                    if (hasScrollableContent && hasScrollableStyle) {
                        const rect = element.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            scrollableContainers.push({
                                tagName: element.tagName,
                                className: element.className,
                                id: element.id,
                                scrollHeight: element.scrollHeight,
                                clientHeight: element.clientHeight,
                                scrollWidth: element.scrollWidth,
                                clientWidth: element.clientWidth,
                                rect: {
                                    top: rect.top,
                                    left: rect.left,
                                    width: rect.width,
                                    height: rect.height
                                }
                            });
                        }
                    }
                }

                return scrollableContainers.sort((a, b) =>
                    (b.rect.width * b.rect.height) - (a.rect.width * a.rect.height)
                );
            }

            return findScrollableContainers();
        })()
        """

        try:
            containers = await self.page.evaluate(scrollable_containers_script)
            logging.debug(f"Found {len(containers)} scrollable containers")
            return containers
        except Exception as e:
            logging.error(f"Error detecting scrollable containers: {e}")
            return []

    async def can_global_scroll(self):
        can_scroll_script = """
        (function() {
            function canGlobalScroll() {
                const documentHeight = Math.max(
                    document.body.scrollHeight,
                    document.body.offsetHeight,
                    document.documentElement.clientHeight,
                    document.documentElement.scrollHeight,
                    document.documentElement.offsetHeight
                );
                const windowHeight = window.innerHeight;
                const currentScrollY = window.scrollY;

                return {
                    canScroll: documentHeight > windowHeight,
                    documentHeight: documentHeight,
                    windowHeight: windowHeight,
                    currentScrollY: currentScrollY,
                    maxScrollY: documentHeight - windowHeight
                };
            }

            return canGlobalScroll();
        })()
        """

        try:
            scroll_info = await self.page.evaluate(can_scroll_script)
            logging.debug(f"Global scroll info: {scroll_info}")
            return scroll_info
        except Exception as e:
            logging.error(f"Error checking global scroll capability: {e}")
            return {"canScroll": False, "documentHeight": 0, "windowHeight": 0, "currentScrollY": 0, "maxScrollY": 0}

    async def scroll_global(self, max_scrolls: int = 10, capture_screenshots: bool = True, page_identifier: str = ""):
        logging.debug("Executing global page scrolling")

        viewport_height = await self.page.evaluate("window.innerHeight")
        screenshot_image_list = []

        async def capture_viewport(screenshot_counter=0):
            if capture_screenshots:
                processed_filename = f"{page_identifier}_global_viewport_{screenshot_counter}"

                screenshot_base64 = await self._action_handler.b64_page_screenshot(
                    file_name=processed_filename,
                    context="scroll"
                )

                if screenshot_base64:
                    screenshot_image_list.append(screenshot_base64)

        scroll_count = 0
        await capture_viewport(scroll_count)

        while scroll_count < max_scrolls:
            current_scroll_y = await self.page.evaluate("window.scrollY")
            document_height = await self.page.evaluate("document.documentElement.scrollHeight")

            if current_scroll_y + viewport_height >= document_height:
                logging.debug("Reached bottom of the page.")
                break

            await self.page.evaluate(f"window.scrollBy(0, {viewport_height})")
            await asyncio.sleep(2)
            scroll_count += 1
            logging.info(f"Global scrolling down... count: {scroll_count}")
            await capture_viewport(scroll_count)

        return screenshot_image_list

    async def scroll_container(
        self,
        container_selector: str,
        max_scrolls: int = 10,
        capture_screenshots: bool = True,
        page_identifier: str = "",
    ):
        logging.debug(f"Executing container scrolling for: {container_selector}")

        safe_selector = self._escape_selector(container_selector)
        if safe_selector != container_selector:
            logging.warning(f"Selector escaped from '{container_selector}' to '{safe_selector}'")

        screenshot_image_list = []

        async def capture_viewport(screenshot_counter=0):
            if capture_screenshots:
                processed_filename = f"{page_identifier}_container_viewport_{screenshot_counter}"

                screenshot_base64 = await self._action_handler.b64_page_screenshot(
                    file_name=processed_filename,
                    context="scroll"
                )

                if screenshot_base64:
                    screenshot_image_list.append(screenshot_base64)

        try:
            container_exists = await self.page.evaluate(
                f"""
            (function() {{
                try {{
                    return !!document.querySelector('{safe_selector}');
                }} catch(e) {{
                    console.error('Selector error:', e);
                    return false;
                }}
            }})()
            """
            )
        except Exception as e:
            logging.error(f"Error checking container existence: {e}")
            return screenshot_image_list

        if not container_exists:
            logging.error(f"Container with selector '{safe_selector}' not found")
            return screenshot_image_list

        scroll_count = 0
        await capture_viewport(scroll_count)

        while scroll_count < max_scrolls:

            try:
                scroll_info = await self.page.evaluate(
                    f"""
                (function() {{
                    try {{
                        const container = document.querySelector('{safe_selector}');
                        if (!container) return null;

                        return {{
                            scrollTop: container.scrollTop,
                            scrollHeight: container.scrollHeight,
                            clientHeight: container.clientHeight,
                            canScroll: container.scrollHeight > container.clientHeight
                        }};
                    }} catch(e) {{
                        console.error('Scroll info error:', e);
                        return null;
                    }}
                }})()
                """
                )
            except Exception as e:
                logging.error(f"Error getting scroll info: {e}")
                break

            if not scroll_info or not scroll_info["canScroll"]:
                logging.debug("Container cannot scroll or reached bottom")
                break

            if scroll_info["scrollTop"] + scroll_info["clientHeight"] >= scroll_info["scrollHeight"]:
                logging.debug("Reached bottom of the container")
                break

            # scroll container
            scroll_amount = scroll_info["clientHeight"]
            try:
                await self.page.evaluate(
                    f"""
                (function() {{
                    try {{
                        const container = document.querySelector('{safe_selector}');
                        if (container) {{
                            container.scrollBy(0, {scroll_amount});
                        }}
                    }} catch(e) {{
                        console.error('Scroll error:', e);
                    }}
                }})()
                """
                )
            except Exception as e:
                logging.error(f"Error scrolling container: {e}")
                break

            await asyncio.sleep(2)
            scroll_count += 1
            logging.info(f"Container scrolling down... count: {scroll_count}")
            await capture_viewport(scroll_count)

        return screenshot_image_list

    def _safe_selector(self, element_info):
        if element_info.get("id") and element_info["id"].strip():
            element_id = element_info["id"].strip()
            if element_id and not any(c in element_id for c in [" ", '"', "'", "\\", "/"]):
                return f"#{element_id}"

        if element_info.get("className") and element_info["className"].strip():
            class_names = element_info["className"].strip().split()
            for class_name in class_names:
                if class_name and all(c.isalnum() or c in ["-", "_"] for c in class_name):
                    return f".{class_name}"

        tag_name = element_info.get("tagName", "div").lower()
        return tag_name

    def _escape_selector(self, selector):

        if any(c in selector for c in ['"', "'", "\\", "/"]):
            return "div"
        return selector

    async def scroll_and_crawl(
        self,
        scroll: bool = True,
        max_scrolls: int = 10,
        capture_screenshots: bool = True,
        page_identifier: str = "",
        prefer_container: bool = True,
    ):

        screenshot_image_list = []

        # if not scroll, exit after initial capture
        if not scroll:
            logging.debug("Scrolling disabled, exiting after initial capture.")
            processed_filename = f"{page_identifier}_initial"
            screenshot_base64 = await self._action_handler.b64_page_screenshot(
                file_name=processed_filename,
                context="scroll"
            )
            if screenshot_base64:
                screenshot_image_list.append(screenshot_base64)
            return screenshot_image_list

        try:
            # check global scroll ability
            global_scroll_info = await self.can_global_scroll()

            if global_scroll_info["canScroll"]:
                logging.debug("Global scrolling is possible, using global scroll")
                screenshot_image_list = await self.scroll_global(max_scrolls, capture_screenshots, page_identifier)
            else:
                logging.debug("Global scrolling not possible, checking for scrollable containers")

                # detect scrollable containers
                containers = await self.detect_scrollable_containers()

                if containers:
                    # select the largest container for scrolling
                    main_container = containers[0]
                    logging.debug(
                        f"Using main container: {main_container['tagName']} (class: {main_container.get('className', 'N/A')})"
                    )

                    # build safe selector
                    selector = self._safe_selector(main_container)
                    logging.debug(f"Using selector: {selector}")

                    screenshot_image_list = await self.scroll_container(
                        selector, max_scrolls, capture_screenshots, page_identifier
                    )

                    # if first container scrolling failed, try other containers
                    if len(screenshot_image_list) <= 1 and len(containers) > 1:
                        logging.debug("Main container scrolling failed, trying other containers")
                        for i, container in enumerate(containers[1:], 1):
                            logging.debug(
                                f"Trying container {i+1}: {container['tagName']} (class: {container.get('className', 'N/A')})"
                            )

                            selector = self._safe_selector(container)
                            logging.debug(f"Using selector: {selector}")

                            container_screenshots = await self.scroll_container(
                                selector, max_scrolls, capture_screenshots, page_identifier
                            )
                            if len(container_screenshots) > 1:
                                screenshot_image_list = container_screenshots
                                break
                else:
                    logging.debug("No scrollable containers found, taking single screenshot")
                    processed_filename = f"{page_identifier}_no_scroll"
                    screenshot_base64 = await self._action_handler.b64_page_screenshot(
                        file_name=processed_filename,
                        context="scroll"
                    )
                    if screenshot_base64:
                        screenshot_image_list.append(screenshot_base64)

        except Exception as e:
            logging.error(f"Error in smart scroll: {e}")
            # if error, at least take one screenshot
            processed_filename = f"{page_identifier}_error_fallback"
            screenshot_base64 = await self._action_handler.b64_page_screenshot(
                file_name=processed_filename,
                context="error"
            )
            if screenshot_base64:
                screenshot_image_list.append(screenshot_base64)

        return screenshot_image_list
