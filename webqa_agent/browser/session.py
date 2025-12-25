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
    """

    def __init__(self, pool_size: int = 2, browser_config: Optional[dict] = None):
        if pool_size <= 0:
            raise ValueError("pool_size must > 0")

        self.pool_size = pool_size
        self.browser_config = browser_config or {}
        self.disable_tab_interception = False  # Control tab interception behavior

        self._available_sessions: asyncio.Queue[_BrowserSession] = asyncio.Queue(maxsize=pool_size)
        self._sessions: List[_BrowserSession] = []
        self._session_counter = 0

        self._initialized = False
        self._closed = False
        self._creation_lock = asyncio.Lock()

    async def initialize(self) -> "BrowserSessionPool":
        if self._initialized:
            return self
        if self._closed:
            raise RuntimeError("BrowserSessionPool has been closed")

        self._initialized = True
        logging.info(f"[SessionPool] Initialized (lazy mode, max_size={self.pool_size})")
        return self

    async def _create_session(self) -> Optional[_BrowserSession]:
        # Allocate session ID under lock, but initialize outside lock for parallelism
        async with self._creation_lock:
            if self._session_counter >= self.pool_size:
                return None  # Pool limit reached
            session_id = f"pool_session_{self._session_counter}"
            self._session_counter += 1

        s = _BrowserSession(
            session_id=session_id,
            browser_config=self.browser_config,
            disable_tab_interception=self.disable_tab_interception,
            _token=_POOL_TOKEN,
        )
        await s.initialize()  # Parallel browser init
        async with self._creation_lock:
            self._sessions.append(s)
            sessions_count = len(self._sessions)
        logging.info(f"[SessionPool] Created session: {s.session_id} (total: {sessions_count}/{self.pool_size})")
        return s

    async def acquire(self, timeout: Optional[float] = 60.0) -> _BrowserSession:
        if not self._initialized:
            raise RuntimeError("BrowserSessionPool not initialized")
        if self._closed:
            raise RuntimeError("BrowserSessionPool has been closed")

        try:
            return self._available_sessions.get_nowait()
        except asyncio.QueueEmpty:
            pass

        # Queue empty, try to create new session
        s = await self._create_session()
        if s is not None:
            return s

        # Pool full, wait for available session
        if timeout is None:
            return await self._available_sessions.get()
        return await asyncio.wait_for(self._available_sessions.get(), timeout=timeout)

    async def release(self, session: Optional[_BrowserSession], failed: bool = False) -> None:
        if self._closed or session is None:
            return

        if failed or session.is_closed():
            session = await self._recover(session)

        try:
            self._available_sessions.put_nowait(session)
        except asyncio.QueueFull as e:
            raise RuntimeError("Session pool is full") from e

    async def _recover(self, session: _BrowserSession) -> _BrowserSession:
        session_id = getattr(session, "session_id", "unknown")
        logging.info(f"[SessionPool] Recovering session: {session_id}")

        try:
            await session.close()
        except Exception:
            logging.exception(f"[SessionPool] Failed to close session {session_id}")

        new_s = _BrowserSession(
            session_id=session_id,
            browser_config=self.browser_config,
            disable_tab_interception=self.disable_tab_interception,
            _token=_POOL_TOKEN,
        )
        await new_s.initialize()

        async with self._creation_lock:
            try:
                idx = self._sessions.index(session)
                self._sessions[idx] = new_s
            except ValueError:
                self._sessions.append(new_s)

        return new_s

    async def close_all(self) -> None:
        if self._closed:
            return
        self._closed = True

        await asyncio.gather(*[s.close() for s in self._sessions], return_exceptions=True)
        self._sessions.clear()

        while not self._available_sessions.empty():
            try:
                self._available_sessions.get_nowait()
            except Exception:
                break

        logging.info("[SessionPool] Closed")

    async def __aenter__(self):
        if not self._initialized:
            await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close_all()


BrowserSession = _BrowserSession  # Type alias for external type annotations
