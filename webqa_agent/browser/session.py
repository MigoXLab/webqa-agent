import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Union

from playwright.async_api import (Browser, BrowserContext, Page,
                                  async_playwright)

from webqa_agent.browser.config import DEFAULT_CONFIG

__all__ = ["BrowserSessionPool", "BrowserSession"]  # BrowserSessionPool 为唯一入口，BrowserSession 为类型标注用


class _SessionToken:
    """Pool-only token. External code cannot obtain this (unless they import internals)."""
    pass


_POOL_TOKEN = _SessionToken()


class _BrowserSession:
    """
    Internal session implementation.
    - Must be created by BrowserSessionPool (token-gated).
    - DO NOT use `async with _BrowserSession` from outside pool.
    """

    def __init__(
            self,
            *,
            session_id: str = None,
            browser_config: Dict[str, Any] = None,
            disable_tab_interception: bool = False,
            _token: Optional[_SessionToken] = None,
    ):
        # Hard gate: only pool can create session
        if _token is not _POOL_TOKEN:
            raise RuntimeError(
                "_BrowserSession is internal. Use BrowserSessionPool.acquire() instead."
            )

        self.session_id = session_id or str(uuid.uuid4())
        self.browser_config = {**DEFAULT_CONFIG, **(browser_config or {})}
        self.disable_tab_interception = disable_tab_interception

        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._playwright = None

        self._is_closed = False
        self._lock = asyncio.Lock()  # per-session lock

    @property
    def page(self) -> Page:
        self._check_state()
        return self._page

    @property
    def context(self) -> BrowserContext:
        self._check_state()
        return self._context

    def is_closed(self) -> bool:
        return self._is_closed

    async def initialize(self) -> "_BrowserSession":
        async with self._lock:
            if self._is_closed:
                raise RuntimeError("Session already closed")
            if self._page:
                return self

            cfg = self.browser_config
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=cfg["headless"],
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-gpu",
                    "--force-device-scale-factor=1",
                    f'--window-size={cfg["viewport"]["width"]},{cfg["viewport"]["height"]}',
                    "--block-new-web-contents",
                ],
            )
            self._context = await self._browser.new_context(
                viewport=cfg["viewport"],
                device_scale_factor=1,
                locale=cfg.get("language", "en-US"),
            )
            self._page = await self._context.new_page()

            # keep single-tab (conditionally based on test type)
            if not self.disable_tab_interception:
                self._context.on('page', self._close_unexpected_page)
                self._page.on('popup', self._close_unexpected_page)
                logging.debug(f'Session {self.session_id} initialized - Tab interception ENABLED')
            else:
                logging.debug(f'Session {self.session_id} initialized - Tab interception DISABLED (multi-tab allowed)')

            # Auto-handle browser dialogs (alert/confirm/prompt) to prevent test blocking
            async def _handle_dialog(dialog):
                dialog_type = dialog.type
                message = dialog.message[:200] if dialog.message else ''
                logging.info(f'[DIALOG] Auto-handled {dialog_type}: {message}')
                await dialog.accept()

            self._page.on('dialog', _handle_dialog)

            return self

    async def close(self) -> None:
        """Internal close. Pool is the owner that should trigger this."""
        async with self._lock:
            if self._is_closed:
                return
            self._is_closed = True

            try:
                if self._page:
                    await self._page.close()
            except Exception:
                logging.debug("Failed to close page", exc_info=True)

            try:
                if self._context:
                    await self._context.close()
            except Exception:
                logging.debug("Failed to close context", exc_info=True)

            try:
                if self._browser:
                    await self._browser.close()
            except Exception:
                logging.debug("Failed to close browser", exc_info=True)

            try:
                if self._playwright:
                    await self._playwright.stop()
            except Exception:
                logging.debug("Failed to stop playwright", exc_info=True)

            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None

    async def navigate_to(self, url: str, cookies: Optional[Union[str, List[dict]]] = None, **kwargs):
        self._check_state()
        logging.debug(f"Session {self.session_id} navigating to: {url}")

        if cookies:
            try:
                cookie_list = json.loads(cookies) if isinstance(cookies, str) else cookies
                cookie_list = [cookie_list] if isinstance(cookie_list, dict) else list(cookie_list)
                await self._context.add_cookies(cookie_list)
            except Exception as e:
                logging.error(f"Failed to add cookies: {e}")

        kwargs.setdefault("timeout", 60000)
        kwargs.setdefault("wait_until", "domcontentloaded")

        try:
            await self._page.goto(url, **kwargs)
            await self._page.wait_for_load_state("networkidle", timeout=60000)
            is_blank = await self._page.evaluate(
                "!document.body || document.body.innerText.trim().length === 0"
            )
        except Exception as e:
            logging.warning(f"Error during navigation: {e}")
            is_blank = False  # fail-open

        if is_blank:
            raise RuntimeError(f"Page load timeout or blank content after navigation to {url}")

    async def get_url(self) -> tuple[str, str]:
        self._check_state()
        return self._page.url, await self._page.title()

    def _check_state(self):
        if self._is_closed or not self._page:
            raise RuntimeError("Session not initialized or closed")

    async def _close_unexpected_page(self, page: Page):
        try:
            await page.close()
            logging.warning(f"Closed unexpected page: {page.url}")
        except Exception as e:
            logging.debug(f"Failed to close unexpected page: {e}")


class BrowserSessionPool:
    """
    Pool is the ONLY owner/entry for browser lifecycle:
    - Queue is the only concurrency control
    - Sessions are created on-demand (lazy init)
    - Recover happens only when caller marks failed
    - Supports multiple browser configurations (sessions reused by config key)
    """

    @staticmethod
    def _make_config_key(config: dict) -> tuple:
        """Create simple tuple key from browser config for session matching.

        Handles edge cases:
        - viewport=None -> use default
        - viewport not a dict -> use default
        - missing width/height -> use default values
        """
        vp = config.get('viewport')
        if not vp or not isinstance(vp, dict):
            vp = {'width': 1280, 'height': 720}
        width = vp.get('width', 1280)
        height = vp.get('height', 720)
        vp_str = f"{width}x{height}"
        return (vp_str, config.get('language', 'en-US'), config.get('headless', True))

    def __init__(self, pool_size: int = 2, browser_config: Optional[dict] = None):
        if pool_size <= 0:
            raise ValueError("pool_size must > 0")

        self.pool_size = pool_size
        self.browser_config = browser_config or {}
        self.disable_tab_interception = False  # Control tab interception behavior

        self._available_sessions: Dict[tuple, asyncio.Queue] = {}  # config_key -> Queue[session]
        self._all_sessions: Dict[tuple, List[_BrowserSession]] = {}  # all sessions with config_key -> [sessions]
        self._session_counter = 0  # Session counter: unique ID generation & pool limit check

        self._initialized = True  # Auto-initialized (lazy mode - sessions created on-demand)
        self._closed = False
        self._creation_lock = asyncio.Lock()

    async def initialize(self) -> "BrowserSessionPool":
        """Initialize the session pool (optional, auto-initialized on creation)"""
        if self._closed:
            raise RuntimeError("BrowserSessionPool has been closed")

        self._initialized = True
        logging.info(f"[SessionPool] Initialized (lazy mode, max_size={self.pool_size})")
        return self

    async def _create_session(self, config: Optional[dict] = None) -> Optional[_BrowserSession]:
        config = config or self.browser_config
        config_key = self._make_config_key(config)

        async with self._creation_lock:
            if self._session_counter >= self.pool_size:
                return None  # Pool limit reached
            session_id = f"pool_session_{self._session_counter}"
            self._session_counter += 1

        s = _BrowserSession(
            session_id=session_id,
            browser_config=config,
            disable_tab_interception=self.disable_tab_interception,
            _token=_POOL_TOKEN,
        )
        await s.initialize()  # Parallel browser init

        async with self._creation_lock:
            if config_key not in self._all_sessions:  # config-specific session tracking
                self._all_sessions[config_key] = []
            self._all_sessions[config_key].append(s)

        logging.info(f"[SessionPool] Created session: {s.session_id} with config {config_key} (total: {self._session_counter}/{self.pool_size})")
        return s

    async def acquire(self, browser_config: Optional[dict] = None, timeout: Optional[float] = 60.0) -> _BrowserSession:
        """Acquire a session with the specified browser config (O(1) lookup).

        Args:
            browser_config: Desired browser configuration
            timeout: Timeout for acquiring session

        Returns:
            Session matching the requested config
        """
        if not self._initialized:
            raise RuntimeError("BrowserSessionPool not initialized")
        if self._closed:
            raise RuntimeError("BrowserSessionPool has been closed")

        config = browser_config or self.browser_config
        config_key = self._make_config_key(config)

        # double-checked locking, avoid overwrite in parallel execution
        if config_key not in self._available_sessions:
            async with self._creation_lock:
                if config_key not in self._available_sessions:
                    self._available_sessions[config_key] = asyncio.Queue()
                    logging.debug(f"[SessionPool] Registered new config: {config_key}")

        try:
            return self._available_sessions[config_key].get_nowait()  # get session from available session queue (O(1))
        except asyncio.QueueEmpty:
            pass

        # Queue empty, try to create new session
        s = await self._create_session(config)
        if s is not None:
            return s

        # Pool full - wait for ANY session release, then retry
        if timeout is None:
            return await self._available_sessions[config_key].get()
        return await asyncio.wait_for(self._available_sessions[config_key].get(), timeout=timeout)

    async def release(self, session: Optional[_BrowserSession], failed: bool = False) -> None:
        """Release session back to its config-specific queue."""
        if self._closed or session is None:
            return

        if failed or session.is_closed():
            session = await self._recover(session)

        config_key = self._make_config_key(session.browser_config)

        # Ensure queue exists for this config
        if config_key not in self._available_sessions:
            async with self._creation_lock:
                if config_key not in self._available_sessions:
                    self._available_sessions[config_key] = asyncio.Queue()

        try:
            self._available_sessions[config_key].put_nowait(session)  # Return to config-specific session queue
        except asyncio.QueueFull as e:
            raise RuntimeError(f"Session pool for config {config_key} is full") from e

    async def _recover(self, session: _BrowserSession) -> _BrowserSession:
        """Recover a failed session by closing and recreating it with the same config."""
        session_id = getattr(session, "session_id", "unknown")
        original_config = getattr(session, "browser_config", self.browser_config)
        config_key = self._make_config_key(original_config)
        logging.info(f"[SessionPool] Recovering session: {session_id} with config {config_key}")

        try:
            await session.close()
        except Exception:
            logging.exception(f"[SessionPool] Failed to close session {session_id}")

        # Create new session with same config
        new_s = _BrowserSession(
            session_id=session_id,
            browser_config=original_config,
            disable_tab_interception=self.disable_tab_interception,
            _token=_POOL_TOKEN,
        )
        await new_s.initialize()

        # Update config-specific session tracking
        async with self._creation_lock:
            if config_key in self._all_sessions:
                try:
                    idx = self._all_sessions[config_key].index(session)
                    self._all_sessions[config_key][idx] = new_s
                except ValueError:
                    self._all_sessions[config_key].append(new_s)

        return new_s

    async def close_all(self) -> None:
        """Close all browser sessions across all configurations."""
        if self._closed:
            return
        self._closed = True

        # Gather all sessions from all configs
        all_sessions = []
        for sessions_list in self._all_sessions.values():
            all_sessions.extend(sessions_list)

        # Close all sessions in parallel
        await asyncio.gather(*[s.close() for s in all_sessions], return_exceptions=True)

        # Clear all config-specific session lists
        self._all_sessions.clear()

        # Clear all config-specific queues
        for queue in self._available_sessions.values():
            while not queue.empty():
                try:
                    queue.get_nowait()
                except Exception:
                    break
        self._available_sessions.clear()

        # Reset session counter (for consistency, even though pool can't be reused)
        self._session_counter = 0

        logging.info("[SessionPool] Closed")

    async def __aenter__(self):
        if not self._initialized:
            await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close_all()


BrowserSession = _BrowserSession  # Type alias for external type annotations
