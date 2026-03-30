import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
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

    Supports two browser modes:
    - Local: Launches Playwright chromium locally
    - Cloud: Connects to AgentBay cloud browser via CDP
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

        # Cloud browser configuration (extracted from browser_config)
        self._cloud_config = self.browser_config.pop('cloud_config', None)
        self._is_cloud_mode = bool(self._cloud_config and self._cloud_config.get('enabled', False))

        # AgentBay-specific resources (only used in cloud mode)
        self._agentbay_client = None
        self._cloud_session = None

        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._playwright = None

        self._is_closed = False
        self._lock = asyncio.Lock()  # per-session lock
        self._closed_page_ids = set()  # Track closed page IDs for deduplication

        # Download directory & unified event collector
        self._downloads_dir = Path(tempfile.mkdtemp(prefix='webqa_downloads_'))

        from webqa_agent.browser.event_collector import BrowserEventCollector
        self._event_collector = BrowserEventCollector(
            downloads_dir=str(self._downloads_dir)
        )

    def __del__(self) -> None:
        """Safety net: clean up temp download directory if close() was never called."""
        try:
            if hasattr(self, '_downloads_dir') and self._downloads_dir and self._downloads_dir.exists():
                shutil.rmtree(self._downloads_dir, ignore_errors=True)
        except Exception:
            pass

    @property
    def page(self) -> Page:
        self._check_state()
        return self._page

    @property
    def context(self) -> BrowserContext:
        self._check_state()
        return self._context

    @property
    def downloads_dir(self) -> Path:
        """Directory where downloaded files are saved."""
        return self._downloads_dir

    @property
    def event_collector(self):
        """Unified browser event collector for per-action event capture."""
        return self._event_collector

    def is_closed(self) -> bool:
        return self._is_closed

    async def clean_state(self) -> None:
        """Clean session state (cookies + storage) for case isolation."""
        if self._is_closed:
            return
        try:
            await self._context.clear_cookies()
            if self._page and not self._page.is_closed():
                await self._page.evaluate('''() => {
                    try { localStorage.clear(); } catch(e) {}
                    try { sessionStorage.clear(); } catch(e) {}
                }''')
        except Exception as e:
            err_str = str(e)
            if 'Target crashed' in err_str or 'Page crashed' in err_str:
                # Session is dead — propagate so the caller (worker) can release it as failed
                logging.warning(f'[Session] clean_state detected crash, propagating: {e}')
                raise
            logging.warning(f'[Session] Failed to clean state: {e}')

    async def reset_context(self) -> None:
        async with self._lock:
            if self._is_closed:
                return

            # 1. Close old page and context
            if self._page:
                try:
                    await self._page.close()
                except Exception:
                    pass
                self._page = None

            if self._context:
                try:
                    await self._context.close()
                except Exception:
                    pass
                self._context = None

            cfg = self.browser_config

            # 2. Re-create context
            if self._is_cloud_mode:
                # AgentBay cloud mode usually operates differently with contexts
                if self._browser and self._browser.contexts:
                    self._context = self._browser.contexts[0]
                    # Clear existing context state in cloud mode
                    await self._context.clear_cookies()
                else:
                    self._context = await self._browser.new_context(
                        viewport=cfg.get('viewport'),
                        device_scale_factor=1,
                        locale=cfg.get('language', 'en-US'),
                        accept_downloads=True,
                    )
            else:
                self._context = await self._browser.new_context(
                    viewport=cfg.get('viewport'),
                    device_scale_factor=1,
                    locale=cfg.get('language', 'en-US'),
                    accept_downloads=True,
                )

                # Reset local browser interceptors
                abort = self._abort_route
                for pattern in ('**/*.woff', '**/*.woff2', '**/*.ttf', '**/*.otf', '**/*.eot'):
                    await self._context.route(pattern, abort)
                await self._context.route('**fonts.googleapis.com/**', abort)
                await self._context.route('**fonts.gstatic.com/**', abort)

            # 3. Re-apply single-tab enforcement (Layer 0)
            if not self.disable_tab_interception:
                await self._enforce_single_tab_dom_preprocessing()

            # 4. Create new page and bind events
            self._page = await self._context.new_page()

            if not self.disable_tab_interception:
                await self._setup_tab_interception_listeners()

            # Auto-handle dialogs
            async def _handle_dialog(dialog):
                dialog_type = dialog.type
                message = dialog.message[:200] if dialog.message else ''
                logging.info(f'[DIALOG] Auto-handled {dialog_type}: {message}')
                await dialog.accept()

            self._page.on('dialog', _handle_dialog)

            # Re-attach event collector on new page (old page is closed)
            await self._event_collector.reset(self._page)

    async def switch_account(
        self,
        cookies: List[Dict[str, Any]],
        navigate_url: Optional[str] = None,
    ) -> None:
        """Atomically switch browser identity by rebuilding the context."""
        await self.reset_context()
        if cookies:
            logging.info(
                f'[Session {self.session_id}] switch_account: adding {len(cookies)} cookies'
            )
            await self._context.add_cookies(cookies)
        else:
            logging.warning(f'[Session {self.session_id}] switch_account: no cookies provided')

        target_url = navigate_url or 'about:blank'
        await self._page.goto(target_url, wait_until='domcontentloaded', timeout=60000)
        final_url = self._page.url
        if final_url != target_url:
            logging.warning(
                f'[Session {self.session_id}] switch_account: navigation redirected '
                f'from {target_url} to {final_url}'
            )

    async def initialize(self) -> '_BrowserSession':
        async with self._lock:
            if self._is_closed:
                raise RuntimeError('Session already closed')
            if self._page:
                return self

            cfg = self.browser_config

            # Branch between local and cloud browser initialization
            if self._is_cloud_mode:
                await self._initialize_cloud_browser(cfg)
                logging.info(f'[Session {self.session_id}] Cloud browser initialized via AgentBay CDP')
            else:
                await self._initialize_local_browser(cfg)

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

            # Attach unified event collector (download, console error, pageerror, requestfailed)
            self._event_collector.attach(self._page)

            return self

    async def close(self) -> None:
        """Internal close.

        Pool is the owner that should trigger this.
        """
        async with self._lock:
            if self._is_closed:
                return
            self._is_closed = True

            # Detach event collector before closing page to reset _attached state
            try:
                if self._page and self._event_collector:
                    self._event_collector.detach(self._page)
            except Exception:
                logging.debug('Failed to detach event collector', exc_info=True)

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

            # Cleanup downloads directory
            try:
                if self._downloads_dir and self._downloads_dir.exists():
                    shutil.rmtree(self._downloads_dir, ignore_errors=True)
            except Exception:
                logging.debug('Failed to clean downloads directory', exc_info=True)

            # Cleanup cloud resources if in cloud mode
            if self._is_cloud_mode:
                await self._cleanup_cloud_resources()

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
            # networkidle is unreliable for SPAs with persistent connections
            # (WebSocket, SSE, analytics heartbeats).  Use a short timeout to
            # avoid wasting 60 s on every navigation in cluster environments.
            try:
                # Use a very short timeout to avoid wasting time on every navigation
                await self._page.wait_for_load_state('networkidle', timeout=3000)
            except Exception:
                logging.debug('networkidle not reached within 3 s; proceeding (domcontentloaded is sufficient)')
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

    @staticmethod
    async def _abort_route(route) -> None:
        """Abort an intercepted route.

        Must be async for Playwright's async API.
        """
        await route.abort()

    async def _initialize_local_browser(self, cfg: Dict[str, Any]) -> None:
        """Initialize local browser via Playwright launch."""
        self._playwright = await async_playwright().start()

        launch_args = [
            '--force-device-scale-factor=1',
            f'--window-size={cfg["viewport"]["width"]},{cfg["viewport"]["height"]}',
            '--num-raster-threads=2',
            '--disable-dev-shm-usage',
            '--use-gl=angle',
            '--enable-unsafe-swiftshader',
            '--ignore-gpu-blocklist',
        ]

        # Playwright 1.57+ headless uses chrome-headless-shell (no WebGL).
        # Force full Chrome binary; achieve headless via Chrome's own flag.
        if cfg['headless']:
            launch_args.append('--headless=new')

        self._browser = await self._playwright.chromium.launch(
            headless=False,
            args=launch_args,
        )
        self._context = await self._browser.new_context(
            viewport=cfg['viewport'],
            device_scale_factor=1,
            is_mobile=False,
            locale=cfg.get('language', 'en-US'),
            accept_downloads=True,
        )

        # ── Cluster stability: intercept external font requests ──
        abort = self._abort_route
        for pattern in ('**/*.woff', '**/*.woff2', '**/*.ttf', '**/*.otf', '**/*.eot'):
            await self._context.route(pattern, abort)
        await self._context.route('**fonts.googleapis.com/**', abort)
        await self._context.route('**fonts.gstatic.com/**', abort)
        logging.debug(f'[Session {self.session_id}] External font requests will be aborted for cluster stability')

    async def _initialize_cloud_browser(self, cfg: Dict[str, Any]) -> None:
        """Initialize cloud browser via AgentBay CDP connection.

        Flow:
        1. AgentBay(api_key) - create client
        2. agent_bay.create(CreateSessionParams(image_id=...)) - create cloud session
        3. session.browser.initialize(BrowserOption(...)) - init remote browser
        4. session.browser.get_endpoint_url() - get CDP endpoint
        5. playwright.chromium.connect_over_cdp(endpoint) - connect via CDP
        6. browser.contexts[0] - use existing context (avoid cloud profile issues)
        """
        try:
            from agentbay import (AgentBay, BrowserOption, BrowserViewport,
                                  CreateSessionParams)
        except ImportError as e:
            raise RuntimeError(
                'AgentBay SDK not installed. Run: pip install wuying-agentbay-sdk'
            ) from e

        # 1. Get API key from cloud_config or environment
        api_key = self._cloud_config.get('api_key') or os.getenv('AGENTBAY_API_KEY')
        if not api_key:
            raise ValueError(
                'AgentBay API key required. Set AGENTBAY_API_KEY env var or provide api_key in cloud_config.'
            )

        # 2. Create AgentBay client and session
        self._agentbay_client = AgentBay(api_key=api_key)
        image_id = self._cloud_config.get('image_id', 'browser_latest')
        result = self._agentbay_client.create(CreateSessionParams(image_id=image_id))
        if not result.success:
            raise RuntimeError(f'AgentBay session creation failed: {result.error_message}')
        self._cloud_session = result.session
        logging.info(f'[Cloud] AgentBay session created: {self._cloud_session.session_id}')

        # 3. Initialize remote browser with viewport from browser_config
        viewport = cfg.get('viewport', {'width': 1280, 'height': 720})
        browser_option = BrowserOption(
            viewport=BrowserViewport(
                width=viewport.get('width', 1280),
                height=viewport.get('height', 720),
            ),
        )
        # Note: initialize() is a synchronous method that returns bool
        ok = self._cloud_session.browser.initialize(browser_option)
        if not ok:
            await self._cleanup_cloud_resources()
            raise RuntimeError('AgentBay browser initialization failed')
        logging.info(f'[Cloud] Browser initialized with viewport {viewport["width"]}x{viewport["height"]}')

        # 4. Get CDP endpoint
        cdp_endpoint = self._cloud_session.browser.get_endpoint_url()
        logging.info(f'[Cloud] CDP endpoint: {cdp_endpoint}')

        # 5. Connect Playwright via CDP
        self._playwright = await async_playwright().start()
        timeout_ms = self._cloud_config.get('timeout', 30) * 1000

        try:
            self._browser = await asyncio.wait_for(
                self._playwright.chromium.connect_over_cdp(cdp_endpoint),
                timeout=timeout_ms / 1000
            )
        except asyncio.TimeoutError:
            await self._cleanup_cloud_resources()
            raise RuntimeError(f'CDP connection timeout after {timeout_ms}ms')

        # 6. Use existing context (preferred for cloud) or create new one
        if self._browser.contexts:
            self._context = self._browser.contexts[0]
            logging.debug('[Cloud] Using existing browser context')
        else:
            self._context = await self._browser.new_context(
                viewport=cfg['viewport'],
                device_scale_factor=1,
                locale=cfg.get('language', 'en-US'),
                accept_downloads=True,
            )
            logging.debug('[Cloud] Created new browser context')

        logging.info(f'[Cloud] Session {self.session_id} initialized successfully')

    async def _cleanup_cloud_resources(self) -> None:
        """Cleanup AgentBay cloud resources."""
        if self._cloud_session:
            try:
                self._cloud_session.release()
                logging.debug('[Cloud] AgentBay session released')
            except Exception as e:
                logging.warning(f'[Cloud] Failed to release AgentBay session: {e}')
            self._cloud_session = None
        self._agentbay_client = None

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
    """Pool is the ONLY owner/entry for browser lifecycle.

    Architecture: Semaphore + Idle List
    - Semaphore controls max concurrent sessions (resource slots)
    - Idle list enables session reuse by config
    - Cross-config eviction when needed
    """

    @staticmethod
    def _make_config_key(config: dict) -> tuple:
        """Create tuple key from browser config for session matching."""
        vp = config.get('viewport')
        if not vp or not isinstance(vp, dict):
            vp = {'width': 1280, 'height': 720}
        return (
            f"{vp.get('width', 1280)}x{vp.get('height', 720)}",
            config.get('language', 'en-US'),
            config.get('headless', True),
        )

    def __init__(self, pool_size: int = 2, browser_config: Optional[dict] = None):
        if pool_size <= 0:
            raise ValueError('pool_size must > 0')

        self.pool_size = pool_size
        self.browser_config = browser_config or {}
        self.disable_tab_interception = False

        self._semaphore = asyncio.Semaphore(pool_size)  # Resource slot control
        self._idle_sessions: Dict[tuple, List[_BrowserSession]] = {}  # config -> [idle sessions]
        self._lock = asyncio.Lock()  # Protects _idle_sessions
        self._session_counter = 0
        self._closed = False

    async def acquire(self, browser_config: Optional[dict] = None, timeout: Optional[float] = 60.0) -> _BrowserSession:
        """Acquire a session with the specified browser config."""
        if self._closed:
            raise RuntimeError('BrowserSessionPool has been closed')

        config = browser_config or self.browser_config
        config_key = self._make_config_key(config)

        # 1. Acquire resource slot (blocks if pool full)
        try:
            if timeout:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout)
            else:
                await self._semaphore.acquire()
        except asyncio.TimeoutError:
            raise asyncio.TimeoutError(f'Timeout acquiring session for config {config_key}')

        try:
            async with self._lock:
                # 2. Reuse idle session with same config
                if self._idle_sessions.get(config_key):
                    session = self._idle_sessions[config_key].pop()
                    logging.debug(f'[SessionPool] Reused session: {session.session_id}')
                    return session

                # 3. Evict idle session from other config (free browser memory)
                for key, sessions in self._idle_sessions.items():
                    if key != config_key and sessions:
                        old = sessions.pop()
                        logging.info(f'[SessionPool] Evicted session: {old.session_id} (config: {key})')
                        await old.close()
                        break

            # 4. Create new session
            return await self._create_session(config)

        except Exception:
            self._semaphore.release()  # Return slot on failure
            raise

    async def release(
        self,
        session: Optional[_BrowserSession],
        failed: bool = False,
        keep_alive: bool = True,
    ) -> None:
        """Release session back to idle pool or close it."""
        if self._closed or session is None:
            return

        if not keep_alive:
            await self._close_session_safe(session)
            self._semaphore.release()
            return

        config_key = self._make_config_key(session.browser_config)

        try:
            # Check if the page itself has crashed or closed (even if failed wasn't explicitly set)
            page_is_dead = False
            if hasattr(session, 'page') and session.page:
                try:
                    page_is_dead = session.page.is_closed()
                except Exception:
                    page_is_dead = True

            if failed or session.is_closed() or page_is_dead:
                logging.info(f'[SessionPool] Recovering failed/crashed session: {session.session_id}')
                await self._close_session_safe(session)
                session = await self._create_session(session.browser_config)
            else:
                await self._clean_session_state(session)
                # If clean_session_state failed due to a crash, the session will be closed
                if session.is_closed():
                    logging.info(f'[SessionPool] Session crashed during clean state, recovering: {session.session_id}')
                    session = await self._create_session(session.browser_config)

            async with self._lock:
                self._idle_sessions.setdefault(config_key, []).append(session)

        finally:
            self._semaphore.release()  # Always return slot

    async def _create_session(self, config: dict) -> _BrowserSession:
        """Create a new browser session."""
        async with self._lock:
            session_id = f'pool_session_{self._session_counter}'
            self._session_counter += 1

        session = _BrowserSession(
            session_id=session_id,
            browser_config=config,
            disable_tab_interception=self.disable_tab_interception,
            _token=_POOL_TOKEN,
        )
        await session.initialize()

        logging.info(f'[SessionPool] Created session: {session_id} (config: {self._make_config_key(config)})')
        return session

    async def _close_session_safe(self, session: _BrowserSession) -> None:
        """Close session with error handling."""
        try:
            await session.close()
        except Exception:
            logging.debug(f'[SessionPool] Failed to close session {session.session_id}', exc_info=True)

    async def _clean_session_state(self, session: _BrowserSession) -> None:
        """Clean session state to prevent pollution between cases.

        Uses reset_context to completely drop the previous Page and Context to
        avoid Chromium memory leak accumulations over multiple SPA navs.
        """
        try:
            # If the session is already closed (e.g. Target crashed), don't try to clean it
            if session.is_closed():
                logging.debug(f'[SessionPool] Skipping clean state for closed session: {session.session_id}')
                return

            await session.reset_context()
            logging.debug(f'[SessionPool] Reset context for memory release: {session.session_id}')

        except Exception as e:
            logging.warning(f'[SessionPool] Failed to reset context: {e}')

            # If cleaning state fails due to target crashed, the page is dead
            if 'Target crashed' in str(e) or 'Page crashed' in str(e):
                logging.error(f'[SessionPool] Marking session as closed due to crash during clean: {session.session_id}')
                await self._close_session_safe(session)

    async def close_all(self) -> None:
        """Close all browser sessions."""
        if self._closed:
            return
        self._closed = True

        async with self._lock:
            all_sessions = [s for sessions in self._idle_sessions.values() for s in sessions]
            self._idle_sessions.clear()

        await asyncio.gather(*[s.close() for s in all_sessions], return_exceptions=True)
        logging.info('[SessionPool] Closed')

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close_all()


BrowserSession = _BrowserSession  # Type alias for external type annotations
