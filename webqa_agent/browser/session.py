import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from playwright.async_api import (Browser, BrowserContext, Page,
                                  async_playwright)

from webqa_agent.browser.config import DEFAULT_CONFIG

__all__ = ['BrowserSessionPool', 'BrowserSession']  # BrowserSessionPool 为唯一入口，BrowserSession 为类型标注用


class _SessionToken:
    """Pool-only token.

    External code cannot obtain this (unless they import internals).
    """
    pass


_POOL_TOKEN = _SessionToken()

# Ad/popup URL patterns to filter during tab interception
_AD_PATTERNS = [
    'doubleclick.net',
    'googlesyndication.com',
    'googleadservices.com',
    'adservice',
    'popup',
    'banner',
]


class _BrowserSession:
    """Internal session implementation.

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
                '_BrowserSession is internal. Use BrowserSessionPool.acquire() instead.'
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
        self._closed_page_ids = set()  # Track closed page IDs for deduplication

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

    async def initialize(self) -> '_BrowserSession':
        async with self._lock:
            if self._is_closed:
                raise RuntimeError('Session already closed')
            if self._page:
                return self

            cfg = self.browser_config
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=cfg['headless'],
                args=[
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-gpu',
                    '--force-device-scale-factor=1',
                    f'--window-size={cfg["viewport"]["width"]},{cfg["viewport"]["height"]}',
                    '--block-new-web-contents',
                ],
            )
            self._context = await self._browser.new_context(
                viewport=cfg['viewport'],
                device_scale_factor=1,
                locale=cfg.get('language', 'en-US'),
            )

            # Single-Tab Architecture (Layered Defense with Coordination)
            #
            # Layer 0 (Base - This File): Context-level prevention via add_init_script()
            #   - Runs BEFORE any page JavaScript
            #   - Sets global flags for coordination with action_handler.py
            #   - Provides: DOM preprocessing, window.open override, MutationObserver
            #
            # Layer 1 (Enhancement - action_handler.py): Click-level enhancements
            #   - Detects Layer 0 presence via flags
            #   - Adds unique features: history recording, periodic checks
            #   - Fallback: full protection if Layer 0 not present
            #
            # Coordination: Global flags prevent redundancy
            #   - window.__webqa_session_init_active: Layer 0 initialized
            #   - window.__webqa_window_open_intercepted: window.open handled
            #   - window.__webqa_mutation_observer_active: MutationObserver created
            #
            # IMPORTANT: Init scripts must be added BEFORE creating pages,
            # but event listeners AFTER (to avoid closing the initial page)
            if not self.disable_tab_interception:
                # Layer 0.1: DOM preprocessing (prevents 95%+ of new tabs at source)
                await self._enforce_single_tab_dom_preprocessing()

                logging.info(f'[Session {self.session_id}] Single-tab enforcement ENABLED (layered coordination)')
            else:
                logging.debug(f'[Session {self.session_id}] Tab interception DISABLED (multi-tab allowed)')

            # Create page AFTER init scripts are registered
            self._page = await self._context.new_page()

            # Layer 0.2: Event listener fallback (set up AFTER page creation)
            if not self.disable_tab_interception:
                await self._setup_tab_interception_listeners()

            # Auto-handle browser dialogs (alert/confirm/prompt) to prevent test blocking
            async def _handle_dialog(dialog):
                dialog_type = dialog.type
                message = dialog.message[:200] if dialog.message else ''
                logging.info(f'[DIALOG] Auto-handled {dialog_type}: {message}')
                await dialog.accept()

            self._page.on('dialog', _handle_dialog)

            return self

    async def close(self) -> None:
        """Internal close.

        Pool is the owner that should trigger this.
        """
        async with self._lock:
            if self._is_closed:
                return
            self._is_closed = True

            try:
                if self._page:
                    await self._page.close()
            except Exception:
                logging.debug('Failed to close page', exc_info=True)

            try:
                if self._context:
                    await self._context.close()
            except Exception:
                logging.debug('Failed to close context', exc_info=True)

            try:
                if self._browser:
                    await self._browser.close()
            except Exception:
                logging.debug('Failed to close browser', exc_info=True)

            try:
                if self._playwright:
                    await self._playwright.stop()
            except Exception:
                logging.debug('Failed to stop playwright', exc_info=True)

            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None

    async def navigate_to(self, url: str, cookies: Optional[Union[str, List[dict]]] = None, **kwargs):
        self._check_state()
        logging.debug(f'Session {self.session_id} navigating to: {url}')

        if cookies:
            try:
                cookie_list = json.loads(cookies) if isinstance(cookies, str) else cookies
                cookie_list = [cookie_list] if isinstance(cookie_list, dict) else list(cookie_list)
                await self._context.add_cookies(cookie_list)
            except Exception as e:
                logging.error(f'Failed to add cookies: {e}')

        kwargs.setdefault('timeout', 60000)
        kwargs.setdefault('wait_until', 'domcontentloaded')

        try:
            await self._page.goto(url, **kwargs)
            await self._page.wait_for_load_state('networkidle', timeout=60000)
            is_blank = await self._page.evaluate(
                '!document.body || document.body.innerText.trim().length === 0'
            )
        except Exception as e:
            logging.warning(f'Error during navigation: {e}')
            is_blank = False  # fail-open

        if is_blank:
            raise RuntimeError(f'Page load timeout or blank content after navigation to {url}')

    async def get_url(self) -> tuple[str, str]:
        self._check_state()
        return self._page.url, await self._page.title()

    async def _enforce_single_tab_dom_preprocessing(self):
        """
        Layer 1: Prevent new tabs at DOM level via init script.

        This is the PRIMARY defense mechanism that runs BEFORE any page loads.
        Advantages:
        - Executes before page JavaScript runs
        - No race conditions with event listeners
        - Works on dynamically added elements via MutationObserver
        - Minimal performance overhead
        """
        await self._context.add_init_script("""
            (() => {
                // Override window.open to navigate current window
                const originalOpen = window.open;
                window.open = function(url, target, features) {
                    console.log('[WebQA Single-Tab] Intercepted window.open:', url);
                    if (url && url !== 'about:blank') {
                        window.location.href = url;
                    }
                    return null;  // Return null to signal failure to caller
                };
                window.__webqa_window_open_intercepted = true;  // Coordination flag for action_handler.py

                // Remove target attributes from all elements (links, forms, areas, base)
                function removeTargetAttributes() {
                    // Handle <a>, <form>, <area>, and <base> elements
                    document.querySelectorAll('a[target], form[target], area[target], base[target]').forEach(elem => {
                        const originalTarget = elem.getAttribute('target');
                        if (originalTarget) {
                            elem.removeAttribute('target');
                            // Store original for debugging
                            elem.setAttribute('data-original-target', originalTarget);
                        }
                    });
                }

                // Set up MutationObserver for dynamic content
                function setupObserver() {
                    removeTargetAttributes();  // Initial cleanup

                    const observer = new MutationObserver((mutations) => {
                        mutations.forEach((mutation) => {
                            mutation.addedNodes.forEach((node) => {
                                if (node.nodeType === 1) {  // Element node
                                    // Check the node itself for target attribute
                                    if (['A', 'FORM', 'AREA', 'BASE'].includes(node.tagName) && node.hasAttribute('target')) {
                                        const target = node.getAttribute('target');
                                        node.removeAttribute('target');
                                        node.setAttribute('data-original-target', target);
                                    }
                                    // Check descendants
                                    node.querySelectorAll?.('a[target], form[target], area[target], base[target]').forEach(elem => {
                                        const target = elem.getAttribute('target');
                                        elem.removeAttribute('target');
                                        elem.setAttribute('data-original-target', target);
                                    });
                                }
                            });
                        });
                    });

                    observer.observe(document.documentElement, {
                        childList: true,
                        subtree: true
                    });
                    window.__webqa_mutation_observer_active = true;  // Coordination flag for action_handler.py
                }

                // Execute on DOMContentLoaded or immediately if already loaded
                if (document.readyState === 'loading') {
                    document.addEventListener('DOMContentLoaded', setupObserver);
                } else {
                    setupObserver();
                }

                // Set master coordination flag
                window.__webqa_session_init_active = true;  // Indicates session.py has initialized
            })();
        """)

    async def _setup_tab_interception_listeners(self):
        """
        Layer 2: Event listener fallback for edge cases.

        This handles scenarios where Layer 1 failed (rare):
        - Middle-click on links
        - Ctrl+Click combinations
        - JavaScript that creates <a> and immediately clicks it
        - Browser extensions interfering with init script
        """
        async def _handle_new_page(page: Page):
            """Intelligent new page handler.

            Strategy:
            1. Check if page is a legitimate navigation target
            2. If yes: close new tab, navigate current tab to target URL
            3. If no (ad/popup): just close it
            """
            # Skip the main page (this handler should only process NEW tabs)
            if page == self._page:
                logging.debug('[Single-Tab] Skipping main page in event handler')
                return

            page_id = id(page)

            # Deduplicate
            if page_id in self._closed_page_ids:
                logging.debug(f'[Single-Tab] Page {page_id} already handled, skipping')
                return

            self._closed_page_ids.add(page_id)

            try:
                # Wait briefly for URL to populate
                await asyncio.wait_for(page.wait_for_load_state('domcontentloaded'), timeout=2.0)
                url = page.url

                # Classify page type
                is_navigation = self._is_legitimate_navigation(url)

                if is_navigation:
                    logging.info(f'[Single-Tab] New tab detected for navigation: {url}')
                    logging.info(f'[Single-Tab] Closing new tab and navigating current tab to: {url}')

                    # Close new tab
                    await page.close()

                    # Navigate current tab to target
                    await self._page.goto(url, wait_until='domcontentloaded', timeout=30000)
                else:
                    logging.warning(f'[Single-Tab] Closing popup/ad: {url}')
                    await page.close()

            except asyncio.TimeoutError:
                logging.warning(f'[Single-Tab] New page timeout, closing: {page_id}')
                try:
                    await page.close()
                except Exception:
                    pass
            except Exception as e:
                logging.debug(f'[Single-Tab] Failed to handle new page: {e}')
                try:
                    await page.close()
                except Exception:
                    pass

        # Only one listener needed (context.on('page') catches everything)
        self._context.on('page', _handle_new_page)
        logging.debug(f'[Single-Tab] Event listener registered for session {self.session_id}')

    def _is_legitimate_navigation(self, url: str) -> bool:
        """Determine if a new page is a legitimate navigation target.

        Returns:
            True if this is a user-intended navigation (should redirect current tab)
            False if this is a popup/ad (should just close)
        """
        if not url or url == 'about:blank':
            return False

        # Filter out common ad/popup patterns
        for pattern in _AD_PATTERNS:
            if pattern in url.lower():
                return False

        # Same origin = likely legitimate navigation
        current_url = self._page.url
        if current_url:
            current_origin = f'{urlparse(current_url).scheme}://{urlparse(current_url).netloc}'
            new_origin = f'{urlparse(url).scheme}://{urlparse(url).netloc}'
            if current_origin == new_origin:
                return True

        # Default: treat as navigation
        return True

    def _check_state(self):
        if self._is_closed or not self._page:
            raise RuntimeError('Session not initialized or closed')


class BrowserSessionPool:
    """Pool is the ONLY owner/entry for browser lifecycle:

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
        vp_str = f'{width}x{height}'
        return (vp_str, config.get('language', 'en-US'), config.get('headless', True))

    def __init__(self, pool_size: int = 2, browser_config: Optional[dict] = None):
        if pool_size <= 0:
            raise ValueError('pool_size must > 0')

        self.pool_size = pool_size
        self.browser_config = browser_config or {}
        self.disable_tab_interception = False  # Control tab interception behavior

        self._available_sessions: Dict[tuple, asyncio.Queue] = {}  # config_key -> Queue[session]
        self._all_sessions: Dict[tuple, List[_BrowserSession]] = {}  # all sessions with config_key -> [sessions]
        self._session_counter = 0  # Session counter: unique ID generation & pool limit check

        self._initialized = True  # Auto-initialized (lazy mode - sessions created on-demand)
        self._closed = False
        self._creation_lock = asyncio.Lock()

    async def initialize(self) -> 'BrowserSessionPool':
        """Initialize the session pool (optional, auto-initialized on
        creation)"""
        if self._closed:
            raise RuntimeError('BrowserSessionPool has been closed')

        self._initialized = True
        logging.info(f'[SessionPool] Initialized (lazy mode, max_size={self.pool_size})')
        return self

    async def _create_session(self, config: Optional[dict] = None) -> Optional[_BrowserSession]:
        config = config or self.browser_config
        config_key = self._make_config_key(config)

        async with self._creation_lock:
            if self._session_counter >= self.pool_size:
                return None  # Pool limit reached
            session_id = f'pool_session_{self._session_counter}'
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

        logging.info(f'[SessionPool] Created session: {s.session_id} with config {config_key} (total: {self._session_counter}/{self.pool_size})')
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
            raise RuntimeError('BrowserSessionPool not initialized')
        if self._closed:
            raise RuntimeError('BrowserSessionPool has been closed')

        config = browser_config or self.browser_config
        config_key = self._make_config_key(config)

        # double-checked locking, avoid overwrite in parallel execution
        if config_key not in self._available_sessions:
            async with self._creation_lock:
                if config_key not in self._available_sessions:
                    self._available_sessions[config_key] = asyncio.Queue()
                    logging.debug(f'[SessionPool] Registered new config: {config_key}')

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
            raise RuntimeError(f'Session pool for config {config_key} is full') from e

    async def _recover(self, session: _BrowserSession) -> _BrowserSession:
        """Recover a failed session by closing and recreating it with the same
        config."""
        session_id = getattr(session, 'session_id', 'unknown')
        original_config = getattr(session, 'browser_config', self.browser_config)
        config_key = self._make_config_key(original_config)
        logging.info(f'[SessionPool] Recovering session: {session_id} with config {config_key}')

        try:
            await session.close()
        except Exception:
            logging.exception(f'[SessionPool] Failed to close session {session_id}')

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

        logging.info('[SessionPool] Closed')

    async def __aenter__(self):
        if not self._initialized:
            await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close_all()


BrowserSession = _BrowserSession  # Type alias for external type annotations
