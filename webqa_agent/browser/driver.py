import asyncio
import logging

from playwright.async_api import async_playwright


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
        logging.info(f"Driver.getInstance called with browser_config: {browser_config}")

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
            # logging.info(f"Driver create_browser called with browser_config: {browser_config}")

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

            logging.debug(f"Browser instance created successfully with config: {browser_config}")
            return self.page

        except Exception as e:
            logging.error("Failed to create browser instance.", exc_info=True)
            raise e

    def get_context(self):
        try:
            return self.context
        except Exception as e:
            logging.error("Failed to get context: %s", e, exc_info=True)
            raise

    def get_page(self):
        """Returns the current page instance.

        Returns:
            Page: The current page instance.
        """
        try:
            return self.page
        except Exception as e:
            logging.error("Failed to get Driver instance: %s", e, exc_info=True)
            raise

    async def get_new_page(self):
        """Switches to the most recently opened page in the browser.

        Returns:
            Page: The new page instance.
        """
        try:
            pages = self.context.pages
            logging.info(f"page number: {len(pages)}")
            if len(pages) > 1:
                logging.info("New page detected.")
                self.page = pages[-1]
                return self.page
            else:
                return self.page
        except Exception as e:
            logging.error("Failed to get new page: %s", e, exc_info=True)
            raise

    async def close_browser(self):
        """Closes the browser instance and stops Playwright."""
        try:
            if not self.is_closed():
                await self.browser.close()
                await self.playwright.stop()
                self._is_closed = True  # mark closed
                logging.info("Browser instance closed successfully.")
        except Exception as e:
            logging.error("Failed to close browser instance.", exc_info=True)
            raise e
