import asyncio
import logging

from playwright.async_api import async_playwright

from webqa_agent.browser.page_manager import PageManager


class Driver:
    # Lock used to ensure thread-safety when multiple coroutines create Driver instances concurrently
    __lock = asyncio.Lock()

    @staticmethod
    async def getInstance(browser_config, *args, **kwargs):
        """Returns the singleton instance of the Driver class. If the instance
        is closed, creates a new one.

        Args:
            browser_config (dict, optional): Browser configuration options.
        """
        logging.debug(f"Driver.getInstance called with browser_config: {browser_config}")

        # Always create a *new* Driver instance – singleton restriction removed to
        # allow multiple browsers to run in parallel.  Keeping the public API
        # unchanged ensures existing call-sites keep working.
        async with Driver.__lock:
            driver = Driver(browser_config=browser_config)
            await driver.create_browser(browser_config=browser_config)
            return driver

    def __init__(self, browser_config=None, *args, **kwargs):
        # Each call constructs an independent browser driver.
        self._is_closed = False
        self.page = None
        self.browser = None
        self.context = None
        self.playwright = None
        self.page_manager = None  # Multi-tab page manager

    def is_closed(self):
        """Check if the browser instance is closed."""
        return getattr(self, "_is_closed", True)

    async def create_browser(self, browser_config):
        """Creates a new browser instance and sets up the page.

        Args:
            browser_config (dict, optional): Browser configuration containing:
                - headless (bool): Whether to run browser in headless mode
                - viewport_width (int): Browser viewport width
                - viewport_height (int): Browser viewport height
                - device_scale_factor (float): Device scale factor

        Returns:
            None
        """
        try:
            # logging.debug(f"Driver create_browser called with browser_config: {browser_config}")

            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=browser_config["headless"],
                args=[
                    "--disable-dev-shm-usage",  # Mitigate shared memory issues in Docker
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-gpu",
                    "--force-device-scale-factor=1",
                    f'--window-size={browser_config["viewport"]["width"]},{browser_config["viewport"]["height"]}',
                ],
            )

            # 创建新的上下文，使用配置的视口大小
            self.context = await self.browser.new_context(
                viewport={"width": browser_config["viewport"]["width"], "height": browser_config["viewport"]["height"]},
                device_scale_factor=1,
                is_mobile=False,
                locale=browser_config["language"],
            )
            # await self.context.tracing.start(screenshots=True, snapshots=True)
            self.page = await self.context.new_page()
            browser_config["browser"] = "Chromium"
            self.config = browser_config

            # Initialize page manager for multi-tab support
            self.page_manager = PageManager(self.context)
            # Register the initial main page
            initial_page_info = await self.page_manager.register_page(
                self.page,
                parent_id=None,
                page_type='main'
            )
            await self.page_manager.push_page(initial_page_info)
            logging.debug("PageManager initialized with main page")

            logging.debug(f"Browser instance created successfully with config: {browser_config}")
            return self.page

        except Exception as e:
            logging.error("Failed to create browser instance.", exc_info=True)
            raise

    def get_context(self):
        try:
            return self.context
        except Exception as e:
            logging.error("Failed to get context: %s", e, exc_info=True)
            raise

    def get_page(self):
        """Returns the current page instance.

        Always returns the active page from page manager if available,
        ensuring we're operating on the correct page in multi-tab scenarios.

        Returns:
            Page: The current page instance.
        """
        try:
            # Delegate to page manager if available
            if self.page_manager:
                managed_page = self.page_manager.get_current_page()
                if managed_page:
                    self.page = managed_page  # Keep self.page in sync
                    return managed_page

            # Fallback to direct page reference
            return self.page
        except Exception as e:
            logging.error("Failed to get Driver instance: %s", e, exc_info=True)
            raise
    
    async def get_url(self):
        """Returns: the current page URL and title."""
        try:
            if self.page is None:
                raise RuntimeError("No active page. Did you call create_browser?")
            url = self.page.url
            title = await self.page.title()
            return url, title
        except Exception as e:
            logging.error("Failed to get URL: %s", e, exc_info=True)
            raise

    async def get_new_page(self):
        """Switches to the most recently opened page in the browser.

        Uses PageManager for robust multi-tab tracking when available.
        Automatically registers new pages and establishes parent-child relationships.

        Returns:
            Page: The new page instance, or None if no new page detected.
        """
        try:
            pages = self.context.pages
            logging.debug(f"Total pages in context: {len(pages)}")

            # Use page manager if available
            if self.page_manager:
                # Check if there are new pages not yet registered
                registered_count = self.page_manager.get_total_pages()
                logging.debug(f"Registered pages: {registered_count}, Context pages: {len(pages)}")

                if len(pages) > registered_count:
                    # New page(s) detected, register the newest one
                    new_page = pages[-1]
                    current_info = self.page_manager.get_current_page_info()

                    # Register new page with current page as parent
                    new_page_info = await self.page_manager.register_page(
                        new_page,
                        parent_id=current_info.page_id if current_info else None,
                        page_type='new_tab'
                    )

                    # Push to stack (switch to new page)
                    await self.page_manager.push_page(new_page_info)

                    # Update self.page reference
                    self.page = new_page

                    logging.info(
                        f"Switched to new page: {new_page_info.page_id} "
                        f"(parent: {new_page_info.parent_id})"
                    )
                    return self.page
                else:
                    logging.warning("get_new_page called but no new page detected in context")
                    return self.page
            else:
                # Fallback to legacy behavior (without page manager)
                logging.debug("PageManager not available, using legacy behavior")
                if len(pages) > 1:
                    self.page = pages[-1]
                    logging.debug(f"New page detected, page index: {len(pages) - 1}")
                    return self.page
                else:
                    return self.page

        except Exception as e:
            logging.error("Failed to get new page: %s", e, exc_info=True)
            raise

    async def get_previous_page(self):
        """Returns to the previous page in the navigation stack.

        This is used for SwitchBackTab action to return to the parent tab
        after completing operations on a child tab.

        Returns:
            Page: The previous page instance, or None if no previous page exists.
        """
        try:
            if not self.page_manager:
                logging.warning("PageManager not available, cannot switch to previous page")
                return None

            # Pop from stack to get previous page
            previous_page_info = await self.page_manager.pop_page()

            if previous_page_info:
                # Update self.page reference
                self.page = previous_page_info.page

                logging.info(
                    f"Switched to previous page: {previous_page_info.page_id} "
                    f"(url: {previous_page_info.url})"
                )
                return self.page
            else:
                logging.warning("No previous page to return to (stack is empty)")
                return None

        except Exception as e:
            logging.error("Failed to get previous page: %s", e, exc_info=True)
            raise

    async def close_browser(self):
        """Closes the browser instance and stops Playwright."""
        try:
            if not self.is_closed():
                # Cleanup page manager first
                if self.page_manager:
                    await self.page_manager.cleanup()
                    logging.debug("PageManager cleaned up successfully.")

                await self.browser.close()
                await self.playwright.stop()
                self._is_closed = True  # mark closed
                logging.debug("Browser instance closed successfully.")
        except Exception as e:
            logging.error("Failed to close browser instance.", exc_info=True)
            raise
