import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional, Union

from playwright.async_api import BrowserContext, Page

from webqa_agent.browser.config import DEFAULT_CONFIG

# Browser creation is now delegated to Driver to ensure a single entry-point.
from webqa_agent.browser.driver import Driver


class BrowserSession:
    """Browser session manager for parallel test execution."""

    def __init__(self, session_id: str = None, browser_config: Dict[str, Any] = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.browser_config = {**DEFAULT_CONFIG, **(browser_config or {})}
        self.driver: Optional[Driver] = None
        # Driver will own browser, context, page and playwright instances
        self._playwright = None  # retained only for backward compatibility when needed
        self._is_closed = False
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Initialize browser session."""
        async with self._lock:
            if self._is_closed:
                raise RuntimeError("Browser session is closed")

            logging.debug(f"Initializing browser session {self.session_id} with config: {self.browser_config}")

            try:
                # Use Driver as the single browser creation entry-point.
                self.driver = await Driver.getInstance(browser_config=self.browser_config)

                # Keep reference if external code needs direct access (optional)
                self._playwright = self.driver.playwright

                logging.debug(f"Browser session {self.session_id} initialized successfully via Driver")

            except Exception as e:
                logging.error(f"Failed to initialize browser session {self.session_id}: {e}")
                await self._cleanup()
                raise

    async def navigate_to(self, url: str, cookies: Optional[Union[str, list]] = None, **kwargs):
        """Navigate to URL."""
        if self._is_closed or not self.driver:
            raise RuntimeError("Browser session not initialized or closed")

        logging.info(f"Session {self.session_id} navigating to: {url}")
        kwargs.setdefault("timeout", 60000)
        kwargs.setdefault("wait_until", "domcontentloaded")

        page = self.driver.get_page()

        # Normalize cookies into list[dict] as required by Playwright.
        if cookies:
            try:
                cookie_list: list
                if isinstance(cookies, str):
                    cookie_list = json.loads(cookies)
                elif isinstance(cookies, dict):
                    cookie_list = [cookies]
                elif isinstance(cookies, (list, tuple)):
                    cookie_list = list(cookies)
                else:
                    raise TypeError("Unsupported cookies type; expected str, dict or list")

                if not isinstance(cookie_list, list):
                    raise ValueError("Parsed cookies is not a list")

                await page.context.add_cookies(cookie_list)
                logging.info("Cookies added success")
            except Exception as e:
                logging.error(f"Failed to add cookies: {e}")

        # Navigate to the target URL and wait until DOM is ready
        await page.goto(url, **kwargs)
        await page.wait_for_load_state("networkidle", timeout=60000)
        try:
            is_blank = await page.evaluate("!document.body || document.body.innerText.trim().length === 0")
        except Exception as e:
            logging.warning(f"Error while checking page content after navigation: {e}")
            is_blank = False  # Fail open – don't block execution if evaluation fails

        if is_blank:
            raise RuntimeError(f"Page load timeout or blank content after navigation to {url}, Please check the url and try again.")

    def get_page(self) -> Page:
        """Return current page via Driver."""
        if self._is_closed or not self.driver:
            raise RuntimeError("Browser session not initialized or closed")
        return self.driver.get_page()

    def get_context(self) -> BrowserContext:
        if self._is_closed or not self.driver:
            raise RuntimeError("Browser session not initialized or closed")
        return self.driver.get_context()

    def is_closed(self) -> bool:
        """Check if session is closed."""
        return self._is_closed

    async def _cleanup(self):
        """Internal cleanup method."""
        try:
            # Delegate cleanup to Driver if available
            if self.driver and not self.driver.is_closed():
                await self.driver.close_browser()

        except Exception as e:
            logging.error(f"Error during cleanup: {e}")
        finally:
            self.driver = None
            self._playwright = None

    async def close(self):
        """Close browser session."""
        async with self._lock:
            if self._is_closed:
                return

            logging.info(f"Closing browser session {self.session_id}")
            self._is_closed = True
            await self._cleanup()
            logging.info(f"Browser session {self.session_id} closed")

    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()


class BrowserSessionManager:
    """Manager for multiple browser sessions."""

    def __init__(self):
        self.sessions: Dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()

    async def browser_session(self, browser_config: Dict[str, Any] = None) -> BrowserSession:
        """Create a new browser session."""
        session = BrowserSession(browser_config=browser_config)
        return session

    async def create_session(self, browser_config: Dict[str, Any] = None) -> BrowserSession:
        """Create a new browser session."""
        session = BrowserSession(browser_config=browser_config)
        await session.initialize()

        async with self._lock:
            self.sessions[session.session_id] = session

        logging.info(f"Created browser session: {session.session_id}")
        return session

    async def get_session(self, session_id: str) -> Optional[BrowserSession]:
        """Get session by ID."""
        async with self._lock:
            return self.sessions.get(session_id)

    async def close_session(self, session_id: str):
        """Close and remove session."""
        async with self._lock:
            session = self.sessions.pop(session_id, None)
            if session:
                await session.close()
                logging.info(f"Closed session: {session_id}")

    async def close_all_sessions(self):
        """Close all sessions."""
        async with self._lock:
            sessions = list(self.sessions.values())
            self.sessions.clear()

        # Close sessions in parallel
        if sessions:
            await asyncio.gather(*[session.close() for session in sessions], return_exceptions=True)
            logging.info(f"Closed {len(sessions)} browser sessions")

    def list_sessions(self) -> Dict[str, Dict[str, Any]]:
        """List all active sessions."""
        return {
            session_id: {"browser_config": session.browser_config, "is_closed": session.is_closed()}
            for session_id, session in self.sessions.items()
        }
