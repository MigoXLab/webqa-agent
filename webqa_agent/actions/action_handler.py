import base64
import json
import os
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from playwright.async_api import Page

from webqa_agent.browser.driver import *


# ===== Action Context Infrastructure for Error Propagation =====

action_context_var: ContextVar[Optional['ActionContext']] = ContextVar('action_context', default=None)


@dataclass
class ActionContext:
    """Stores detailed error context for action execution.

    This context is propagated through the execution chain using contextvars,
    allowing detailed error information to be passed without changing return types.
    """
    error_type: Optional[str] = None
    error_reason: Optional[str] = None
    attempted_strategies: List[str] = field(default_factory=list)
    element_info: Dict[str, Any] = field(default_factory=dict)
    scroll_attempts: int = 0
    max_scroll_attempts: int = 0
    playwright_error: Optional[str] = None

    def set_error(self, error_type: str, reason: str, **kwargs):
        """Set error information with optional additional fields."""
        self.error_type = error_type
        self.error_reason = reason
        for key, value in kwargs.items():
            setattr(self, key, value)

    def reset(self):
        """Reset context for a new action."""
        self.error_type = None
        self.error_reason = None
        self.attempted_strategies = []
        self.element_info = {}
        self.scroll_attempts = 0
        self.max_scroll_attempts = 0
        self.playwright_error = None


# Error type constants for consistent classification
ERROR_SCROLL_FAILED = "scroll_failed"
ERROR_SCROLL_TIMEOUT = "scroll_timeout_lazy_loading"
ERROR_ELEMENT_NOT_FOUND = "element_not_found"
ERROR_NOT_CLICKABLE = "element_not_clickable"
ERROR_NOT_TYPEABLE = "element_not_typeable"
ERROR_ELEMENT_OBSCURED = "element_obscured"
ERROR_DROPDOWN_NO_MATCH = "dropdown_no_match"
ERROR_DROPDOWN_NOT_FOUND = "dropdown_not_found"
ERROR_FILE_UPLOAD_FAILED = "file_upload_failed"
ERROR_ACTION_TIMEOUT = "action_timeout"
ERROR_PLAYWRIGHT = "playwright_error"


class ActionHandler:
    def __init__(self):
        self.page_data = {}
        self.page_element_buffer = {}  # page element buffer
        self.driver = None
        self.page = None

    async def initialize(self, page: Page | None = None, driver=None):
        if page is not None:
            self.page = page
            if driver is not None:
                self.driver = driver
            return self
        return self

    async def update_element_buffer(self, new_element):
        """Update page_element_buffer :param new_buffer: CrawlerHandler fetched
        latest element buffer."""
        self.page_element_buffer = new_element

    async def go_to_page(self, page: Page, url: str, cookies=None):
        # if not self.driver:
        #     self.driver = await Driver.getInstance()
        self.page = page
        if cookies:
            try:
                cookies = json.loads(cookies)
                await self.page.context.add_cookies(cookies)
            except Exception as e:
                raise Exception(f'add context cookies error: {e}')

        await self.page.goto(url=url, wait_until='domcontentloaded')
        await self.page.wait_for_load_state('networkidle', timeout=60000)

    async def smart_navigate_to_page(self, page: Page, url: str, cookies=None) -> bool | None:
        """Smart navigation to target page, avoiding redundant navigation.

        Args:
            page: Playwright page object
            url: Target URL
            cookies: Optional cookies

        Returns:
            bool: Whether navigation operation was performed
        """
        try:
            # Get current page URL
            current_url = page.url
            logging.debug(f'Smart navigation check - Current URL: {current_url}, Target URL: {url}')

            # Enhanced URL normalization function to handle various domain variations
            def normalize_url(u):
                from urllib.parse import urlparse

                try:
                    parsed = urlparse(u)
                    # Handle domain variations: remove www prefix, unify lowercase
                    netloc = parsed.netloc.lower()
                    if netloc.startswith('www.'):
                        netloc = netloc[4:]  # Remove www.

                    # Standardize path: remove trailing slash
                    path = parsed.path.rstrip('/')

                    # Build normalized URL
                    normalized = f'{parsed.scheme}://{netloc}{path}'
                    return normalized
                except Exception:
                    # If parsing fails, return lowercase version of original URL
                    return u.lower()

            current_normalized = normalize_url(current_url)
            target_normalized = normalize_url(url)

            logging.debug(f'Normalized URLs - Current: {current_normalized}, Target: {target_normalized}')

            if current_normalized == target_normalized:
                logging.debug('Already on target page (normalized match), skipping navigation')
                return None  # Return None to indicate "already on page, no navigation needed"

            # More flexible URL matching: if domain is same and path is similar, also consider as match
            def extract_domain(u):
                try:
                    from urllib.parse import urlparse

                    parsed = urlparse(u)
                    domain = parsed.netloc.lower()
                    if domain.startswith('www.'):
                        domain = domain[4:]
                    return domain
                except Exception:
                    return ''

            def extract_path(u):
                try:
                    from urllib.parse import urlparse

                    parsed = urlparse(u)
                    return parsed.path.rstrip('/')
                except Exception:
                    return ''

            current_domain = extract_domain(current_url)
            target_domain = extract_domain(url)
            current_path = extract_path(current_url)
            target_path = extract_path(url)

            # If domain is same and path is exactly same, or homepage variant
            if current_domain == target_domain and (
                current_path == target_path
                or current_path == ''
                and target_path == ''
                or current_path == '/'
                and target_path == ''
                or current_path == ''
                and target_path == '/'
            ):
                logging.debug(f'Domain and path match detected ({current_domain}{current_path}), skipping navigation')
                return False

            # Check if page is still valid
            try:
                await page.title()  # Simple check if page responds
                logging.debug(f'Page is responsive, proceeding with navigation from {current_url} to {url}')
            except Exception as e:
                logging.warning(f'Page check failed: {e}, forcing navigation')

            # Need to perform navigation
            await self.go_to_page(page, url, cookies)
            logging.debug(f'Successfully navigated to {url}')
            return True

        except Exception as e:
            logging.error(f'Smart navigation failed: {e}, falling back to regular navigation')
            # Perform regular navigation on error
            await self.go_to_page(page, url, cookies)
            return True

    async def set_overflow_hidden(self):
        await self.page.evaluate("document.body.style.overflow = 'hidden'")

    async def close_page(self) -> None:
        """Close the current page."""
        if self.page:
            try:
                await self.page.close()
                logging.debug('Page closed successfully')
            except Exception as e:
                logging.error(f'Error closing page: {e}')

    def set_page_element_buffer(self, element_buffer: Dict[int, Dict]) -> None:
        """Set the page element buffer for action execution."""
        self.page_element_buffer = element_buffer

    async def scroll(self, direction: str = 'down', scrollType: str = 'once', distance: Optional[int] = None) -> bool:
        """Scroll page.
        Args:
            direction: 'up' or 'down'
            scrollType: 'once' or 'untilBottom' or 'untilTop'
            distance: None or Number

        Returns:
            bool: Whether scroll operation was performed
        """
        logging.debug('Start scrolling page')

        # Validate inputs to avoid silent no-ops
        allowed_directions = {'up', 'down'}
        allowed_scroll_types = {'once', 'untilBottom', 'untilTop'}

        if direction not in allowed_directions:
            logging.error(f"Invalid direction '{direction}'. Allowed: {sorted(list(allowed_directions))}")
            return False

        if scrollType not in allowed_scroll_types:
            logging.error(f"Invalid scrollType '{scrollType}'. Allowed: {sorted(list(allowed_scroll_types))}")
            return False

        if distance is not None:
            try:
                distance = int(distance)
            except (TypeError, ValueError):
                logging.error(f"Invalid distance '{distance}'. Must be an integer or None")
                return False
            if distance < 0:
                logging.error(f"Invalid distance '{distance}'. Must be >= 0")
                return False

        async def perform_scroll():  # Execute scroll operation
            if direction == 'up':
                await self.page.evaluate(f'(document.scrollingElement || document.body).scrollTop -= {distance};')
            elif direction == 'down':
                await self.page.evaluate(f'(document.scrollingElement || document.body).scrollTop += {distance};')

        if not distance:
            distance = int(await self.page.evaluate('window.innerHeight') / 2)
            logging.debug(f'Scrolling distance: {distance}')

        if scrollType == 'once':
            await perform_scroll()
            return True

        elif scrollType == 'untilBottom':
            prev_scroll = -1  # Record last scroll position, avoid stuck

            while True:
                # Get current scroll position and page total height
                current_scroll = await self.page.evaluate('window.scrollY')
                current_scroll_height = await self.page.evaluate('document.body.scrollHeight')

                # Check if page is scrolled to the bottom
                if current_scroll == prev_scroll:
                    logging.debug('No further scroll possible, reached the bottom.')
                    break

                # Until bottom
                if current_scroll + distance >= current_scroll_height:
                    distance = current_scroll_height - current_scroll
                    logging.debug(f'Adjusting last scroll distance to {distance}')

                prev_scroll = current_scroll
                await perform_scroll()
                await asyncio.sleep(1)

            return True

        elif scrollType == 'untilTop':
            prev_scroll = -1

            while True:
                current_scroll = await self.page.evaluate('window.scrollY')

                # If already at top or no progress, stop
                if current_scroll <= 0 or current_scroll == prev_scroll:
                    logging.debug('No further scroll possible, reached the top.')
                    break

                # Adjust last scroll to not go past top
                if current_scroll - distance <= 0:
                    distance = current_scroll
                    logging.debug(f'Adjusting last scroll distance to {distance}')

                prev_scroll = current_scroll
                await perform_scroll()
                await asyncio.sleep(1)

            return True

    async def ensure_element_in_viewport(self, element_id: str, max_retries: int = 3, base_wait_time: float = 0.5) -> bool:
        """Ensure element is in viewport by scrolling if needed with enhanced edge case handling.

        This method enables full-page planning mode where elements can be planned
        from a full-page screenshot but may be outside the viewport during execution.

        Handles edge cases:
        - Lazy-loaded content that appears after scrolling
        - Infinite scroll pages with dynamic content
        - Slow-loading pages with delayed element rendering

        Args:
            element_id: Element ID to scroll to
            max_retries: Maximum retry attempts for lazy-loaded content (default: 3)
            base_wait_time: Base wait time in seconds, will be adaptive (default: 0.5)

        Returns:
            bool: True if element is in viewport (or successfully scrolled to), False otherwise
        """
        # Initialize action context for error propagation
        ctx = ActionContext()
        action_context_var.set(ctx)
        ctx.max_scroll_attempts = max_retries
        ctx.element_info = {"element_id": element_id, "action": "ensure_viewport"}

        element = self.page_element_buffer.get(str(element_id))
        if not element:
            logging.warning(f'Element {element_id} not found in buffer for viewport check')
            ctx.set_error(
                ERROR_ELEMENT_NOT_FOUND,
                f"Element {element_id} not found in page element buffer",
                element_id=element_id
            )
            return False

        # Check if element is already in viewport
        is_in_viewport = element.get('isInViewport', True)
        if is_in_viewport:
            logging.debug(f'Element {element_id} already in viewport, no scroll needed')
            return True

        logging.info(f'Element {element_id} is outside viewport, scrolling to make it visible')

        # Get element selectors
        selector = element.get('selector')
        xpath = element.get('xpath')

        # Retry loop for handling lazy-loaded content
        for attempt in range(max_retries):
            try:
                ctx.scroll_attempts = attempt + 1
                # Adaptive wait time increases with retries for slow-loading content
                current_wait_time = base_wait_time * (1 + attempt * 0.5)

                # Strategy 1: Use Playwright's scroll_into_view_if_needed (most reliable)
                if self._is_valid_css_selector(selector):
                    try:
                        ctx.attempted_strategies.append(f"css_selector_attempt_{attempt + 1}")
                        await self.page.locator(selector).scroll_into_view_if_needed(timeout=5000)
                        logging.debug(f'Scrolled to element {element_id} using CSS selector (attempt {attempt + 1})')

                        # Wait for scroll animation + potential lazy-loading
                        await asyncio.sleep(current_wait_time)

                        # Verify page stability after scroll (for dynamic content)
                        await self._wait_for_page_stability()

                        # Verify element is actually in viewport using bounding_box
                        try:
                            rect = await self.page.locator(selector).bounding_box()
                            if rect:
                                viewport_height = await self.page.evaluate('window.innerHeight')
                                viewport_width = await self.page.evaluate('window.innerWidth')
                                is_in_viewport = (rect['y'] >= 0 and rect['y'] < viewport_height and
                                                rect['x'] >= 0 and rect['x'] < viewport_width)
                                if is_in_viewport:
                                    logging.debug(f'Element {element_id} verified in viewport at ({rect["x"]:.1f}, {rect["y"]:.1f})')
                                else:
                                    logging.warning(f'Element {element_id} scrolled but still outside viewport: y={rect["y"]:.1f}, viewport_height={viewport_height}')
                        except Exception as verify_error:
                            logging.debug(f'Could not verify viewport position for element {element_id}: {verify_error}')

                        return True
                    except Exception as css_error:
                        ctx.playwright_error = str(css_error)
                        if attempt < max_retries - 1:
                            logging.debug(f'CSS selector scroll failed on attempt {attempt + 1}: {css_error}, retrying...')
                            await asyncio.sleep(current_wait_time)
                            continue
                        else:
                            logging.debug(f'CSS selector scroll failed after {max_retries} attempts: {css_error}, trying XPath')

                # Strategy 2: Try XPath if CSS fails
                if xpath:
                    try:
                        ctx.attempted_strategies.append(f"xpath_attempt_{attempt + 1}")
                        await self.page.locator(f'xpath={xpath}').scroll_into_view_if_needed(timeout=5000)
                        logging.debug(f'Scrolled to element {element_id} using XPath (attempt {attempt + 1})')

                        # Wait for scroll animation + potential lazy-loading
                        await asyncio.sleep(current_wait_time)

                        # Verify page stability after scroll
                        await self._wait_for_page_stability()

                        # Verify element is actually in viewport using bounding_box
                        try:
                            rect = await self.page.locator(f'xpath={xpath}').bounding_box()
                            if rect:
                                viewport_height = await self.page.evaluate('window.innerHeight')
                                viewport_width = await self.page.evaluate('window.innerWidth')
                                is_in_viewport = (rect['y'] >= 0 and rect['y'] < viewport_height and
                                                rect['x'] >= 0 and rect['x'] < viewport_width)
                                if is_in_viewport:
                                    logging.debug(f'Element {element_id} verified in viewport at ({rect["x"]:.1f}, {rect["y"]:.1f})')
                                else:
                                    logging.warning(f'Element {element_id} scrolled but still outside viewport: y={rect["y"]:.1f}, viewport_height={viewport_height}')
                        except Exception as verify_error:
                            logging.debug(f'Could not verify viewport position for element {element_id}: {verify_error}')

                        return True
                    except Exception as xpath_error:
                        ctx.playwright_error = str(xpath_error)
                        if attempt < max_retries - 1:
                            logging.debug(f'XPath scroll failed on attempt {attempt + 1}: {xpath_error}, retrying...')
                            await asyncio.sleep(current_wait_time)
                            continue
                        else:
                            logging.debug(f'XPath scroll failed after {max_retries} attempts: {xpath_error}, trying coordinate-based scroll')

                # Strategy 3: Fallback to coordinate-based scrolling with retry support
                center_y = element.get('center_y')
                if center_y is not None:
                    ctx.attempted_strategies.append(f"coordinates_attempt_{attempt + 1}")
                    viewport_height = await self.page.evaluate('window.innerHeight')
                    current_scroll_y = await self.page.evaluate('window.scrollY')

                    # Calculate target scroll position (center element in viewport)
                    target_scroll_y = center_y - viewport_height / 2
                    target_scroll_y = max(0, target_scroll_y)  # Don't scroll above page top

                    # Log scroll operation for debugging
                    logging.debug(f'Scrolling element {element_id}: current scroll position={current_scroll_y}, target scroll position={target_scroll_y}')

                    # Perform scroll with smooth behavior
                    await self.page.evaluate(f'window.scrollTo({{top: {target_scroll_y}, behavior: "smooth"}})')
                    logging.debug(f'Scrolled to element {element_id} using coordinates (y={target_scroll_y}, attempt {attempt + 1})')

                    # Adaptive wait time for smooth scroll + lazy loading
                    await asyncio.sleep(current_wait_time + 0.3)  # Extra time for smooth scroll

                    # Verify page stability after scroll
                    page_stable = await self._wait_for_page_stability()
                    if not page_stable:
                        # Page not stable, likely lazy-loading
                        if attempt == max_retries - 1:
                            ctx.set_error(
                                ERROR_SCROLL_TIMEOUT,
                                f"Element {element_id} viewport positioning succeeded but page content unstable after {max_retries} attempts, possible lazy-loading or infinite scroll",
                                selector=selector,
                                xpath=xpath,
                                center_y=center_y
                            )

                    # Verify scroll position (coordinate-based scroll may not work with scroll containers)
                    actual_scroll_y = await self.page.evaluate('window.scrollY')
                    if abs(actual_scroll_y - target_scroll_y) > 10:
                        logging.warning(
                            f'Coordinate-based scroll for element {element_id} may have failed: '
                            f'target={target_scroll_y:.1f}, actual={actual_scroll_y:.1f}. '
                            f'This may indicate scroll containers.'
                        )

                    return True

                # If all strategies failed but we have more retries, wait and continue
                if attempt < max_retries - 1:
                    logging.debug(f'All scroll strategies failed on attempt {attempt + 1}, waiting before retry...')
                    await asyncio.sleep(current_wait_time * 2)  # Longer wait between full retry cycles
                    continue

            except Exception as e:
                ctx.playwright_error = str(e)
                if attempt < max_retries - 1:
                    logging.warning(f'Error scrolling to element {element_id} on attempt {attempt + 1}: {e}, retrying...')
                    await asyncio.sleep(current_wait_time)
                    continue
                else:
                    logging.error(f'Error scrolling to element {element_id} after {max_retries} attempts: {e}')
                    ctx.set_error(
                        ERROR_SCROLL_FAILED,
                        f"All scroll strategies failed after {max_retries} attempts with exception: {str(e)}",
                        selector=selector,
                        xpath=xpath
                    )
                    return False

        # Final failure: all retries exhausted
        logging.warning(f'Could not scroll to element {element_id} after {max_retries} attempts: no valid selectors or all strategies failed')
        ctx.set_error(
            ERROR_SCROLL_FAILED,
            f"Could not scroll to element after {max_retries} attempts: no valid selectors or all scroll strategies (CSS, XPath, coordinates) failed",
            selector=selector,
            xpath=xpath,
            has_valid_selector=self._is_valid_css_selector(selector) if selector else False,
            has_xpath=xpath is not None,
            has_coordinates=element.get('center_y') is not None
        )
        return False

    async def _wait_for_page_stability(self, timeout: float = 2.0, check_interval: float = 0.5) -> bool:
        """Wait for page to stabilize after scroll (handles lazy-loading and dynamic content).

        Args:
            timeout: Maximum time to wait for stability (default: 2.0 seconds)
            check_interval: Interval between stability checks (default: 0.5 seconds)

        Returns:
            bool: True if page stabilized, False if timeout reached
        """
        try:
            elapsed = 0.0
            last_height = await self.page.evaluate('document.body.scrollHeight')

            while elapsed < timeout:
                await asyncio.sleep(check_interval)
                elapsed += check_interval

                current_height = await self.page.evaluate('document.body.scrollHeight')

                # If page height hasn't changed, consider it stable
                if current_height == last_height:
                    logging.debug(f'Page stabilized after {elapsed:.1f}s')
                    return True

                last_height = current_height

            logging.debug(f'Page stability timeout after {timeout}s (content may still be loading)')
            return False

        except Exception as e:
            logging.warning(f'Error checking page stability: {e}')
            return False

    async def _convert_document_to_viewport_coords(self, x: float, y: float) -> tuple[float, float]:
        """Convert document coordinates to viewport coordinates.

        Document coordinates are relative to the entire page (top-left of document).
        Viewport coordinates are relative to the visible area (top-left of viewport).

        Playwright's mouse operations use viewport coordinates, while our crawler
        captures document coordinates. This method performs the necessary conversion.

        **IMPORTANT NOTE**: This method only works correctly with window-level scrolling.
        For pages using scroll containers (elements with overflow: auto/scroll), the
        window.pageYOffset will be 0 even after scrolling, causing incorrect conversion.
        In such cases, use element.bounding_box() to get fresh viewport coordinates instead.

        Args:
            x: Document X coordinate (from element center_x)
            y: Document Y coordinate (from element center_y)

        Returns:
            Tuple of (viewport_x, viewport_y)

        Example:
            # Element at document position (500, 1200) with scroll at (0, 800)
            # viewport_y = 1200 - 800 = 400 (element is 400px from top of viewport)
        """
        # Get window scroll offset (only reflects window-level scrolling, not scroll containers)
        scroll_x = await self.page.evaluate('window.pageXOffset || document.documentElement.scrollLeft')
        scroll_y = await self.page.evaluate('window.pageYOffset || document.documentElement.scrollTop')

        # Detect potential scroll container issues
        # If coordinates are large but scroll offset is 0, likely using scroll containers
        if (abs(x) > 100 or abs(y) > 100) and scroll_x == 0 and scroll_y == 0:
            # Check if page has scroll containers
            has_scroll_containers = await self.page.evaluate('''() => {
                const scrollContainers = document.querySelectorAll('[style*="overflow"]');
                const computedScrollContainers = Array.from(document.querySelectorAll('*')).filter(el => {
                    const style = window.getComputedStyle(el);
                    return (style.overflow === 'auto' || style.overflow === 'scroll' ||
                            style.overflowY === 'auto' || style.overflowY === 'scroll');
                });
                return scrollContainers.length > 0 || computedScrollContainers.length > 0;
            }''')

            if has_scroll_containers:
                logging.warning(
                    f'Coordinate conversion may be inaccurate: document coords=({x}, {y}), '
                    f'but window scroll offset=(0, 0) with scroll containers detected. '
                    f'This indicates overflow scrolling. Consider using bounding_box() instead.'
                )

        viewport_x = x - scroll_x
        viewport_y = y - scroll_y

        logging.debug(
            f'Coordinate conversion: document=({x:.1f}, {y:.1f}), '
            f'scroll_offset=({scroll_x:.1f}, {scroll_y:.1f}), '
            f'viewport=({viewport_x:.1f}, {viewport_y:.1f})'
        )

        return (viewport_x, viewport_y)

    async def _get_element_viewport_coordinates(
        self,
        element_id: str,
        selector: Optional[str] = None,
        xpath: Optional[str] = None,
        stored_x: Optional[float] = None,
        stored_y: Optional[float] = None,
        validate_against_stored: bool = True,
        action_name: str = "action"
    ) -> Optional[tuple[float, float]]:
        """Get viewport coordinates for an element using multiple strategies.

        This method provides a unified approach for obtaining viewport coordinates,
        handling scroll containers correctly by using Playwright's bounding_box() API.

        Tries strategies in order:
        1. Fresh bounding_box() via CSS selector (most reliable)
        2. Fresh bounding_box() via XPath (fallback if CSS fails)
        3. Coordinate conversion from stored document coords (backward compatibility)

        Args:
            element_id: Element identifier for logging
            selector: CSS selector
            xpath: XPath selector
            stored_x: Stored document X coordinate
            stored_y: Stored document Y coordinate
            validate_against_stored: Whether to validate fresh coords against stored
            action_name: Name of the action for logging context (e.g., "click", "hover")

        Returns:
            Tuple of (viewport_x, viewport_y) if successful, None otherwise
        """
        rect = None

        # Strategy 1: Try CSS selector for bounding_box()
        if self._is_valid_css_selector(selector):
            try:
                rect = await self.page.locator(selector).bounding_box()
            except Exception as e:
                logging.debug(f'bounding_box() via CSS selector failed for element {element_id} ({action_name}): {e}')

        # Strategy 2: Try XPath if CSS fails or returns None
        if not rect and xpath:
            try:
                rect = await self.page.locator(f'xpath={xpath}').bounding_box()
            except Exception as e:
                logging.debug(f'bounding_box() via XPath failed for element {element_id} ({action_name}): {e}')

        # Use fresh viewport coordinates if available
        if rect:
            viewport_x = rect['x'] + rect['width'] / 2
            viewport_y = rect['y'] + rect['height'] / 2

            # Optionally validate against stored coordinates to detect scroll container issues
            if validate_against_stored and stored_x is not None and stored_y is not None:
                calc_viewport_x, calc_viewport_y = await self._convert_document_to_viewport_coords(stored_x, stored_y)
                diff_x = abs(viewport_x - calc_viewport_x)
                diff_y = abs(viewport_y - calc_viewport_y)

                if diff_x > 10 or diff_y > 10:
                    logging.warning(
                        f'Coordinate mismatch detected for element {element_id} ({action_name}): '
                        f'fresh bounding_box=({viewport_x:.1f}, {viewport_y:.1f}), '
                        f'calculated from stored=({calc_viewport_x:.1f}, {calc_viewport_y:.1f}), '
                        f'diff=({diff_x:.1f}, {diff_y:.1f}). '
                        f'Likely scroll container or CSS transform. Using fresh coordinates.'
                    )

            logging.debug(f'{action_name.capitalize()} at element {element_id}, fresh viewport coordinates=({viewport_x:.1f}, {viewport_y:.1f})')
            return (viewport_x, viewport_y)

        # Strategy 3: Fallback to stored coordinates with conversion
        elif stored_x is not None and stored_y is not None:
            logging.warning(f'bounding_box() returned None for element {element_id} ({action_name}), falling back to stored coordinates')
            viewport_x, viewport_y = await self._convert_document_to_viewport_coords(stored_x, stored_y)
            logging.debug(f'{action_name.capitalize()} at element {element_id}, document coordinates=({stored_x}, {stored_y}), calculated viewport=({viewport_x}, {viewport_y})')
            return (viewport_x, viewport_y)

        else:
            logging.error(f'Element {element_id} has no valid coordinates for {action_name}: bounding_box=None, stored coordinates missing')
            return None

    async def click(self, id) -> bool:
        # Initialize action context for error propagation
        # Note: If ensure_element_in_viewport is called, it will set its own context
        # We only need to initialize context for click-specific failures
        ctx = ActionContext()
        action_context_var.set(ctx)
        ctx.element_info = {"element_id": str(id), "action": "click"}

        # Inject JavaScript into the page to remove the target attribute from all links
        js = """
        links = document.getElementsByTagName("a");
        for (var i = 0; i < links.length; i++) {
            links[i].removeAttribute("target");
        }
        """
        await self.page.evaluate(js)

        try:
            id = str(id)
            element = self.page_element_buffer.get(id)
            if not element:
                logging.error(f'Element with id {id} not found in buffer for click action.')
                ctx.set_error(
                    ERROR_ELEMENT_NOT_FOUND,
                    f"Element {id} not found in page element buffer for click action",
                    element_id=id
                )
                return False

            logging.debug(
                f"Attempting to click element: id={id}, tagName='{element.get('tagName')}', innerText='{element.get('innerText', '').strip()[:50]}', selector='{element.get('selector')}'"
            )

        except Exception as e:
            logging.error(f'failed to get element {id}, element: {self.page_element_buffer.get(id)}, error: {e}')
            ctx.set_error(
                ERROR_PLAYWRIGHT,
                f"Exception while retrieving element {id} from buffer: {str(e)}",
                element_id=id,
                playwright_error=str(e)
            )
            return False

        # Ensure element is in viewport before clicking (for full-page planning mode)
        if not await self.ensure_element_in_viewport(id):
            logging.error(f'Cannot click element {id}: failed to scroll element into viewport after multiple attempts')
            # Context already populated by ensure_element_in_viewport, preserve it
            return False

        # Attempt click - if it fails, populate context with click-specific error
        click_result = await self.click_using_coordinates(element, id)
        if not click_result:
            # Get current context to check if error already set by click_using_coordinates
            current_ctx = action_context_var.get()
            if current_ctx and not current_ctx.error_type:
                current_ctx.set_error(
                    ERROR_NOT_CLICKABLE,
                    f"Element {id} found and in viewport, but click action failed",
                    element_id=id,
                    tag_name=element.get('tagName'),
                    selector=element.get('selector')
                )
        return click_result

    async def click_using_coordinates(self, element, id) -> bool:
        """Helper function to click using coordinates with scroll container handling.

        Uses Playwright's bounding_box() to get fresh viewport coordinates,
        which correctly handles scroll containers, CSS transforms, and fixed positioning.
        Falls back to stored coordinates if bounding_box() fails.
        """
        selector = element.get('selector')
        xpath = element.get('xpath')
        stored_x = element.get('center_x')
        stored_y = element.get('center_y')

        try:
            # Use unified coordinate retrieval method
            coords = await self._get_element_viewport_coordinates(
                element_id=id,
                selector=selector,
                xpath=xpath,
                stored_x=stored_x,
                stored_y=stored_y,
                validate_against_stored=True,
                action_name="mouse click"
            )

            if coords:
                viewport_x, viewport_y = coords
                await self.page.mouse.click(viewport_x, viewport_y)
                return True
            else:
                return False

        except Exception as e:
            logging.error(f'Error clicking element {id}: {e}')
            return False

    async def hover(self, id) -> bool:
        """Hover over element using fresh viewport coordinates.

        Uses Playwright's bounding_box() to get fresh viewport coordinates,
        which correctly handles scroll containers, CSS transforms, and fixed positioning.
        """
        # Initialize action context for error propagation
        ctx = ActionContext()
        action_context_var.set(ctx)
        ctx.element_info = {"element_id": str(id), "action": "hover"}

        element = self.page_element_buffer.get(str(id))
        if not element:
            logging.error(f'Element with id {id} not found in buffer for hover action.')
            ctx.set_error(
                ERROR_ELEMENT_NOT_FOUND,
                f"Element {id} not found in page element buffer for hover action",
                element_id=id
            )
            return False

        logging.debug(
            f"Attempting to hover over element: id={id}, tagName='{element.get('tagName')}', innerText='{element.get('innerText', '').strip()[:50]}', selector='{element.get('selector')}'"
        )

        # Ensure element is in viewport before hovering (for full-page planning mode)
        if not await self.ensure_element_in_viewport(str(id)):
            logging.error(f'Cannot hover over element {id}: failed to scroll element into viewport after multiple attempts')
            # Context already populated by ensure_element_in_viewport, preserve it
            return False

        try:
            selector = element.get('selector')
            xpath = element.get('xpath')
            stored_x = element.get('center_x')
            stored_y = element.get('center_y')

            # Use unified coordinate retrieval method
            coords = await self._get_element_viewport_coordinates(
                element_id=str(id),
                selector=selector,
                xpath=xpath,
                stored_x=stored_x,
                stored_y=stored_y,
                validate_against_stored=False,  # Skip validation for hover (less critical)
                action_name="hover"
            )

            if coords:
                viewport_x, viewport_y = coords
                await self.page.mouse.move(viewport_x, viewport_y)
                await asyncio.sleep(0.5)
                return True
            else:
                ctx.set_error(
                    ERROR_ELEMENT_NOT_FOUND,
                    f"Element {id} missing coordinate information (bounding_box and stored coordinates unavailable)",
                    element_id=id,
                    has_center_x=stored_x is not None,
                    has_center_y=stored_y is not None
                )
                return False

        except Exception as e:
            logging.error(f'Hover action failed for element {id}: {e}')
            ctx.set_error(
                ERROR_PLAYWRIGHT,
                f"Hover action failed with exception: {str(e)}",
                element_id=id,
                playwright_error=str(e)
            )
            return False

    async def wait(self, timeMs) -> bool:
        """Wait for specified time.

        Args:
            timeMs: wait time (milliseconds)

        Returns:
            bool: True if success, False if failed
        """
        logging.debug(f'wait for {timeMs} milliseconds')
        await asyncio.sleep(timeMs / 1000)
        logging.debug(f'wait for {timeMs} milliseconds done')
        return True

    async def type(self, id, text, clear_before_type: bool = False) -> bool:
        """Types text into the specified element, optionally clearing it
        first."""
        # Initialize action context for error propagation
        ctx = ActionContext()
        action_context_var.set(ctx)
        ctx.element_info = {"element_id": str(id), "action": "type", "text_length": len(text), "clear_before_type": clear_before_type}

        try:
            element = self.page_element_buffer.get(str(id))
            if not element:
                logging.error(f'Element with id {id} not found in buffer for type action.')
                ctx.set_error(
                    ERROR_ELEMENT_NOT_FOUND,
                    f"Element {id} not found in page element buffer for type action",
                    element_id=id
                )
                return False

            logging.debug(
                f"Attempting to type into element: id={id}, tagName='{element.get('tagName')}', innerText='{element.get('innerText', '').strip()[:50]}', selector='{element.get('selector')}', clear_before_type={clear_before_type}"
            )

            # Ensure element is in viewport before typing (for full-page planning mode)
            if not await self.ensure_element_in_viewport(str(id)):
                logging.error(f'Cannot type into element {id}: failed to scroll element into viewport after multiple attempts')
                # Context already populated by ensure_element_in_viewport, preserve it
                return False

            if clear_before_type:
                if not await self.clear(id):
                    logging.warning(f'Failed to clear element {id} before typing, but will attempt to type anyway.')

            # click element to get focus
            try:
                if not await self.click(str(id)):
                    # Context already populated by click(), check and enhance if needed
                    current_ctx = action_context_var.get()
                    if current_ctx and not current_ctx.error_type:
                        current_ctx.set_error(
                            ERROR_NOT_CLICKABLE,
                            f"Cannot type into element {id}: failed to click element for focus",
                            element_id=id
                        )
                    return False
            except Exception as e:
                logging.error(f"Error 'type' clicking using coordinates: {e}")
                logging.error(f'id type {type(id)}, id: {id}')
                ctx.set_error(
                    ERROR_PLAYWRIGHT,
                    f"Exception while clicking element {id} to focus for typing: {str(e)}",
                    element_id=id,
                    playwright_error=str(e)
                )
                return False

            await asyncio.sleep(1)
            # Type text using unified fill method
            selector = element['selector']
            xpath = element.get('xpath')

            if not await self._fill_element_text(
                element_id=str(id),
                selector=selector,
                xpath=xpath,
                text=text,
                action_name="type"
            ):
                return False

            await asyncio.sleep(1)
            return True
        except Exception as e:
            logging.error(f'Failed to type into element {id}: {e}')
            ctx.set_error(
                ERROR_PLAYWRIGHT,
                f"Unexpected exception during type action: {str(e)}",
                element_id=id,
                playwright_error=str(e)
            )
            return False

    @staticmethod
    def _is_valid_css_selector(selector: str) -> bool:
        """Validate if CSS selector format is valid.

        Args:
            selector: CSS selector string

        Returns:
            bool: True if selector format is valid, False otherwise
        """
        if not selector or not isinstance(selector, str):
            return False

        # Basic CSS selector format validation
        # Check for invalid characters or format
        try:
            # Remove whitespace
            selector = selector.strip()
            if not selector:
                return False

            # Basic CSS selector syntax check
            # Cannot start with a number (unless it's a pseudo-selector)
            if re.match(r'^[0-9]', selector) and not selector.startswith(':'):
                return False

            # Check basic CSS selector pattern
            # Allow: tag names, class names, IDs, attributes, pseudo-classes, pseudo-elements, combinators, etc.
            css_pattern = r'^[a-zA-Z_\-\[\]().,:#*>+~\s="\'0-9]+$'
            if not re.match(css_pattern, selector):
                return False

            # Check bracket matching
            if selector.count('[') != selector.count(']'):
                return False
            if selector.count('(') != selector.count(')'):
                return False

            return True

        except Exception:
            return False

    async def _fill_element_text(
        self,
        element_id: str,
        selector: str,
        xpath: Optional[str],
        text: str,
        action_name: str = "fill"
    ) -> bool:
        """Fill element text using CSS selector with XPath fallback.

        This method provides a unified approach for filling input elements,
        handling both valid and invalid CSS selectors with automatic XPath fallback.

        Args:
            element_id: Element ID for logging
            selector: CSS selector
            xpath: Optional XPath selector for fallback
            text: Text to fill (empty string for clear operation)
            action_name: Name of action for logging/errors (e.g., "type", "clear")

        Returns:
            True if successful, False otherwise (with error context set)
        """
        ctx = action_context_var.get()

        # Strategy 1: Try CSS selector if format is valid
        if self._is_valid_css_selector(selector):
            try:
                await self.page.locator(selector).fill(text)
                logging.debug(f"{action_name.capitalize()}ed element {element_id} using CSS selector: {selector}")
                return True
            except Exception as css_error:
                logging.warning(f'CSS selector {action_name} failed for element {element_id}: {css_error}')
                if ctx:
                    ctx.playwright_error = str(css_error)

                # Strategy 2: Try XPath fallback if CSS fails
                if xpath:
                    try:
                        await self.page.locator(f'xpath={xpath}').fill(text)
                        logging.debug(f"{action_name.capitalize()}ed element {element_id} using XPath fallback: {xpath}")
                        return True
                    except Exception as xpath_error:
                        logging.error(
                            f'Both CSS and XPath {action_name} failed for element {element_id}. '
                            f'CSS error: {css_error}, XPath error: {xpath_error}'
                        )
                        if ctx:
                            ctx.set_error(
                                ERROR_NOT_TYPEABLE,
                                f"Both CSS selector and XPath strategies failed to {action_name} element {element_id}",
                                element_id=element_id,
                                selector=selector,
                                xpath=xpath,
                                css_error=str(css_error),
                                xpath_error=str(xpath_error)
                            )
                        return False
                else:
                    logging.error(f'CSS selector {action_name} failed and no XPath available for element {element_id}')
                    if ctx:
                        ctx.set_error(
                            ERROR_NOT_TYPEABLE,
                            f"CSS selector failed to {action_name} element {element_id} and no XPath fallback available",
                            element_id=element_id,
                            selector=selector,
                            has_xpath=False,
                            playwright_error=str(css_error)
                        )
                    return False

        # Strategy 3: CSS selector format invalid, use XPath directly
        else:
            logging.warning(f'Invalid CSS selector format for element {element_id}: {selector}')
            if xpath:
                try:
                    await self.page.locator(f'xpath={xpath}').fill(text)
                    logging.debug(f"{action_name.capitalize()}ed element {element_id} using XPath: {xpath}")
                    return True
                except Exception as xpath_error:
                    logging.error(f'XPath {action_name} failed for element {element_id}: {xpath_error}')
                    if ctx:
                        ctx.set_error(
                            ERROR_NOT_TYPEABLE,
                            f"XPath strategy failed to {action_name} element {element_id} (invalid CSS selector)",
                            element_id=element_id,
                            selector=selector,
                            xpath=xpath,
                            playwright_error=str(xpath_error)
                        )
                    return False
            else:
                logging.error(f'Invalid CSS selector and no XPath available for element {element_id}')
                if ctx:
                    ctx.set_error(
                        ERROR_NOT_TYPEABLE,
                        f"Invalid CSS selector format and no XPath available for element {element_id}",
                        element_id=element_id,
                        selector=selector,
                        has_xpath=False
                    )
                return False

    async def clear(self, id) -> bool:
        """Clears the text in the specified input element."""
        # Initialize action context for error propagation
        ctx = ActionContext()
        action_context_var.set(ctx)
        ctx.element_info = {"element_id": str(id), "action": "clear"}

        try:
            element_to_clear = self.page_element_buffer.get(str(id))
            if not element_to_clear:
                logging.error(f'Element with id {id} not found in buffer for clear action.')
                ctx.set_error(
                    ERROR_ELEMENT_NOT_FOUND,
                    f"Element {id} not found in page element buffer for clear action",
                    element_id=id
                )
                return False

            logging.debug(
                f"Attempting to clear element: id={id}, tagName='{element_to_clear.get('tagName')}', innerText='{element_to_clear.get('innerText', '').strip()[:50]}', selector='{element_to_clear.get('selector')}'"
            )

            # First, click the element to ensure it has focus
            if not await self.click(str(id)):
                logging.warning(f'Could not focus element {id} before clearing, but proceeding anyway.')

            # Get the selector for the element
            if 'selector' not in element_to_clear:
                logging.error(f'Element {id} has no selector for clearing.')
                return False

            selector = element_to_clear['selector']
            xpath = element_to_clear.get('xpath')

            # Clear input using unified fill method
            if not await self._fill_element_text(
                element_id=str(id),
                selector=selector,
                xpath=xpath,
                text='',  # Empty string for clear
                action_name="clear"
            ):
                return False

            await asyncio.sleep(0.5)
            return True
        except Exception as e:
            logging.error(f'Failed to clear element {id}: {e}')
            ctx.set_error(
                ERROR_PLAYWRIGHT,
                f"Unexpected exception during clear action: {str(e)}",
                element_id=id,
                playwright_error=str(e)
            )
            return False

    async def keyboard_press(self, key) -> bool:
        """Press keyboard key.

        Args:
            key: key name

        Returns:
            bool: True if success, False if failed
        """
        # Initialize action context for error propagation
        ctx = ActionContext()
        action_context_var.set(ctx)
        ctx.element_info = {"action": "keyboard_press", "key": key}

        try:
            await self.page.keyboard.press(key)
            await asyncio.sleep(1)
            return True
        except Exception as e:
            logging.error(f"Keyboard press failed for key '{key}': {e}")
            ctx.set_error(
                ERROR_PLAYWRIGHT,
                f"Keyboard press action failed for key '{key}'",
                key=key,
                playwright_error=str(e)
            )
            return False

    async def b64_page_screenshot(self, full_page=False, file_path=None, file_name=None, save_to_log=True):
        """Get page screenshot (Base64 encoded)

        Args:
            full_page: whether to capture the whole page
            file_path: screenshot save path (optional)
            file_name: screenshot file name (optional)
            save_to_log: whether to save to log system (default True)

        Returns:
            tuple: (screenshot base64 encoded, screenshot file path)
        """
        # get screenshot
        screenshot_bytes = await self.take_screenshot(self.page, full_page=full_page, timeout=30000)

        # convert to Base64
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
        base64_data = f'data:image/png;base64,{screenshot_base64}'
        return base64_data

    async def take_screenshot(
        self,
        page: Page,
        full_page: bool = False,
        file_path: str | None = None,
        timeout: float = 120000,
    ) -> bytes:
        """Get page screenshot (binary)

        Args:
            page: page object
            full_page: whether to capture the whole page
            file_path: screenshot save path (only used for direct saving, not recommended in test flow)
            timeout: timeout

        Returns:
            bytes: screenshot binary data
        """
        try:
            try:
                await page.wait_for_load_state(timeout=60000)
            except Exception as e:
                logging.warning(f'wait_for_load_state before screenshot failed: {e}; attempting screenshot anyway')
            logging.debug('Page is fully loaded or skipped wait; taking screenshot')

            # Directly capture screenshot as binary data
            if file_path:
                screenshot: bytes = await page.screenshot(
                    path=file_path,
                    full_page=full_page,
                    timeout=timeout,
                )
            else:
                screenshot: bytes = await page.screenshot(
                    full_page=full_page,
                    timeout=timeout,
                )

            return screenshot

        except Exception as e:
            logging.warning(f'Page screenshot attempt failed: {e}; trying fallback capture')
            raise

    async def go_back(self) -> bool:
        """Navigate back to the previous page."""
        try:
            await self.page.go_back()
            logging.debug('Navigated back to the previous page.')
            return True
        except Exception as e:
            logging.error(f'Failed to navigate back: {e}')
            return False

    async def get_new_page(self):
        try:
            if self.driver:
                self.page = await self.driver.get_new_page()
            else:
                # If no driver, check current context page list
                pages = self.page.context.pages if self.page else []
                if len(pages) > 1:
                    self.page = pages[-1]
            return True
        except Exception as e:
            logging.error(f'Failed to get new page: {e}')
            return False

    async def upload_file(self, id, file_path: Union[str, List[str]]) -> bool:
        """File upload function.

        Args:
            id (str): element ID (not used for matching)
            file_path (str or list): file path or path list to upload

        Returns:
            bool: True if success, False if failed
        """
        # Initialize action context for error propagation
        ctx = ActionContext()
        action_context_var.set(ctx)
        ctx.element_info = {"element_id": str(id), "action": "upload", "file_path": str(file_path)}

        try:
            # Support single file and multiple files
            if isinstance(file_path, str):
                file_paths = [file_path]
            elif isinstance(file_path, list):
                file_paths = file_path
            else:
                logging.error(f'file_path must be str or list, got {type(file_path)}')
                ctx.set_error(
                    ERROR_FILE_UPLOAD_FAILED,
                    f"Invalid file_path type: expected str or list, got {type(file_path)}",
                    file_path_type=str(type(file_path))
                )
                return False

            valid_file_paths = []
            missing_files = []
            for fp in file_paths:
                if not fp or not isinstance(fp, str):
                    continue
                if not os.path.exists(fp):
                    logging.error(f'File not found: {fp}')
                    missing_files.append(fp)
                    continue
                valid_file_paths.append(fp)

            if not valid_file_paths:
                logging.error('No valid files to upload.')
                ctx.set_error(
                    ERROR_FILE_UPLOAD_FAILED,
                    f"No valid files to upload. Missing files: {', '.join(missing_files) if missing_files else 'None'}",
                    missing_files=missing_files,
                    provided_paths=file_paths
                )
                return False

            # Get file extension for accept check
            file_extension = os.path.splitext(valid_file_paths[0])[1].lower() if valid_file_paths else ''

            # Find all file input elements and get more detailed selector
            file_inputs = await self.page.evaluate(
                """(fileExt) => {
                return Array.from(document.querySelectorAll('input[type=\"file\"]'))
                    .map(input => {
                        const accept = input.getAttribute('accept') || '';
                        let selector = `input[type=\"file\"]`;

                        if (input.name) {
                            selector += `[name=\"${input.name}\"]`;
                        }

                        if (accept) {
                            selector += `[accept=\"${accept}\"]`;
                        }

                        return {
                            selector: selector,
                            accept: accept,
                            acceptsFile: accept ? accept.toLowerCase().includes(fileExt) : true
                        };
                    });
            }""",
                file_extension,
            )

            if not file_inputs:
                logging.error('No file input elements found')
                ctx.set_error(
                    ERROR_ELEMENT_NOT_FOUND,
                    "No file input elements found on page for upload action",
                    element_id=id
                )
                return False

            # Find compatible input elements
            logging.debug(f'file_inputs: {file_inputs}')
            compatible_inputs = [input_elem for input_elem in file_inputs if input_elem.get('acceptsFile')]

            # If compatible input elements are found, use the first one, otherwise fallback to the first available
            logging.debug(f'compatible_inputs: {compatible_inputs}')
            selected_input = compatible_inputs[0] if compatible_inputs else file_inputs[0]
            logging.debug(f'selected_input: {selected_input}')

            # Upload files (support batch)
            selector = selected_input.get('selector')
            logging.debug(f'Uploading files {valid_file_paths} to: {selector}')
            await self.page.set_input_files(selector, valid_file_paths)

            await asyncio.sleep(1)
            return True

        except Exception as e:
            logging.error(f'Upload failed: {str(e)}')
            ctx.set_error(
                ERROR_FILE_UPLOAD_FAILED,
                f"File upload failed with exception: {str(e)}",
                playwright_error=str(e)
            )
            return False

    async def get_dropdown_options(self, id) -> Dict[str, Any]:
        """Get all options of various type selectors.

        supported selector types:
        - native <select> element
        - Ant Design Select (.ant-select)
        - Ant Design Cascader (.ant-cascader)
        - other custom dropdown components

        Args:
            id: element ID

        Returns:
            Dict: dictionary containing option information, format:
                {
                    'success': bool,
                    'options': List[Dict] or None,
                    'message': str,
                    'selector_type': str  # selector type
                }
        """
        element = self.page_element_buffer.get(str(id))
        if not element:
            return {
                'success': False,
                'options': None,
                'message': f'Element with id {id} not found in buffer',
                'selector_type': 'unknown',
            }

        try:
            # use JavaScript to detect selector type and get options
            js_code = """
            (elementData) => {
                // find element by coordinates
                const centerX = elementData.center_x;
                const centerY = elementData.center_y;
                const element = document.elementFromPoint(centerX, centerY);

                if (!element) {
                    return { success: false, message: 'Element not found at coordinates', selector_type: 'unknown' };
                }

                let selectElement = element.closest('select');
                if (selectElement) {
                    const options = Array.from(selectElement.options).map((opt, index) => ({
                        text: opt.text,
                        value: opt.value,
                        index: index,
                        selected: opt.selected
                    }));

                    return {
                        success: true,
                        options: options,
                        selector_type: 'native_select',
                        selectInfo: {
                            id: selectElement.id,
                            name: selectElement.name,
                            multiple: selectElement.multiple,
                            selectedIndex: selectElement.selectedIndex,
                            optionCount: selectElement.options.length
                        }
                    };
                }

                let antSelect = element.closest('.ant-select');
                if (antSelect && !antSelect.classList.contains('ant-cascader')) {
                    // click to expand options
                    const selector = antSelect.querySelector('.ant-select-selector');
                    if (selector) {
                        selector.click();

                        // wait for options to appear
                        return new Promise((resolve) => {
                            setTimeout(() => {
                                const dropdown = document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden)');
                                if (dropdown) {
                                    const options = Array.from(dropdown.querySelectorAll('.ant-select-item-option')).map((opt, index) => {
                                        const textEl = opt.querySelector('.ant-select-item-option-content');
                                        return {
                                            text: textEl ? textEl.textContent.trim() : opt.textContent.trim(),
                                            value: opt.getAttribute('data-value') || opt.textContent.trim(),
                                            index: index,
                                            selected: opt.classList.contains('ant-select-item-option-selected'),
                                            disabled: opt.classList.contains('ant-select-item-option-disabled')
                                        };
                                    });

                                    resolve({
                                        success: true,
                                        options: options,
                                        selector_type: 'ant_select',
                                        selectInfo: {
                                            multiple: antSelect.classList.contains('ant-select-multiple'),
                                            allowClear: antSelect.classList.contains('ant-select-allow-clear'),
                                            optionCount: options.length
                                        }
                                    });
                                } else {
                                    resolve({
                                        success: false,
                                        message: 'Could not find dropdown options after clicking',
                                        selector_type: 'ant_select'
                                    });
                                }
                            }, 500);
                        });
                    }
                }

                // check if it is Ant Design Cascader
                let antCascader = element.closest('.ant-cascader');
                if (antCascader) {
                    // click to expand options
                    const selector = antCascader.querySelector('.ant-select-selector');
                    if (selector) {
                        selector.click();

                        // wait for cascader options to appear
                        return new Promise((resolve) => {
                            setTimeout(() => {
                                const dropdown = document.querySelector('.ant-cascader-dropdown:not(.ant-cascader-dropdown-hidden)');
                                if (dropdown) {
                                    // get first level options
                                    const firstLevelOptions = Array.from(dropdown.querySelectorAll('.ant-cascader-menu:first-child .ant-cascader-menu-item')).map((opt, index) => {
                                        return {
                                            text: opt.textContent.trim(),
                                            value: opt.getAttribute('data-path-key') || opt.textContent.trim(),
                                            index: index,
                                            selected: opt.classList.contains('ant-cascader-menu-item-active'),
                                            hasChildren: opt.classList.contains('ant-cascader-menu-item-expand'),
                                            level: 0
                                        };
                                    });

                                    resolve({
                                        success: true,
                                        options: firstLevelOptions,
                                        selector_type: 'ant_cascader',
                                        selectInfo: {
                                            multiple: antCascader.classList.contains('ant-select-multiple'),
                                            allowClear: antCascader.classList.contains('ant-select-allow-clear'),
                                            optionCount: firstLevelOptions.length,
                                            isExpanded: true
                                        }
                                    });
                                } else {
                                    resolve({
                                        success: false,
                                        message: 'Could not find cascader dropdown after clicking',
                                        selector_type: 'ant_cascader'
                                    });
                                }
                            }, 500);
                        });
                    }
                }

                // check other possible dropdown components
                let customDropdown = element.closest('[role="combobox"], [role="listbox"], .dropdown, .select');
                if (customDropdown) {
                    // try generic method to get options
                    const options = Array.from(customDropdown.querySelectorAll('option, [role="option"], .option, .item')).map((opt, index) => ({
                        text: opt.textContent.trim(),
                        value: opt.getAttribute('value') || opt.getAttribute('data-value') || opt.textContent.trim(),
                        index: index,
                        selected: opt.hasAttribute('selected') || opt.classList.contains('selected') || opt.getAttribute('aria-selected') === 'true'
                    }));

                    if (options.length > 0) {
                        return {
                            success: true,
                            options: options,
                            selector_type: 'custom_dropdown',
                            selectInfo: {
                                optionCount: options.length
                            }
                        };
                    }
                }

                // if no match, return failure
                return {
                    success: false,
                    message: 'No supported dropdown type found. Element classes: ' + element.className,
                    selector_type: 'unsupported'
                };
            }
            """

            result = await self.page.evaluate(js_code, element)

            if result.get('success'):
                logging.debug(f"Found {len(result['options'])} options in {result.get('selector_type')} dropdown")
                return {
                    'success': True,
                    'options': result['options'],
                    'selector_type': result.get('selector_type'),
                    'selectInfo': result.get('selectInfo'),
                    'message': f"Successfully retrieved {len(result['options'])} options from {result.get('selector_type')}",
                }
            else:
                logging.error(f"Failed to get dropdown options: {result.get('message')}")
                return {
                    'success': False,
                    'options': None,
                    'selector_type': result.get('selector_type', 'unknown'),
                    'message': result.get('message', 'Unknown error'),
                }

        except Exception as e:
            logging.error(f'Error getting dropdown options: {str(e)}')
            return {'success': False, 'options': None, 'selector_type': 'error', 'message': f'Error: {str(e)}'}

    async def select_dropdown_option(self, dropdown_id, option_text, option_id=None):
        """Priority option_id, otherwise use dropdown_id to expand and
        select."""
        # priority option_id
        if option_id is not None:
            element = self.page_element_buffer.get(str(option_id))
            if element:
                selector = element.get('selector')
                xpath = element.get('xpath')
                stored_x = element.get('center_x')
                stored_y = element.get('center_y')

                try:
                    # Use unified coordinate retrieval method
                    coords = await self._get_element_viewport_coordinates(
                        element_id=str(option_id),
                        selector=selector,
                        xpath=xpath,
                        stored_x=stored_x,
                        stored_y=stored_y,
                        validate_against_stored=True,
                        action_name="dropdown option click"
                    )

                    if coords:
                        viewport_x, viewport_y = coords
                        await self.page.mouse.click(viewport_x, viewport_y)

                        logging.debug(f'Clicked option_id {option_id} ({option_text}) directly.')
                        return {
                            'success': True,
                            'message': f"Clicked dropdown option '{option_text}' directly.",
                            'selected_value': element.get('innerText'),
                            'selector_type': 'ant_select_option',
                        }
                    else:
                        return {
                            'success': False,
                            'message': f'Option element {option_id} missing coordinate information',
                            'selected_value': None,
                            'selector_type': 'unknown',
                        }

                except Exception as e:
                    logging.error(f'Error clicking dropdown option {option_id}: {e}')
                    return {
                        'success': False,
                        'message': f'Error clicking dropdown option: {str(e)}',
                        'selected_value': None,
                        'selector_type': 'unknown',
                    }
            else:
                logging.warning(f'option_id {option_id} not found in buffer, fallback to dropdown_id.')

        # fallback: use dropdown_id to expand and select
        element = self.page_element_buffer.get(str(dropdown_id))
        if not element:
            return {
                'success': False,
                'message': f'dropdown_id {dropdown_id} not found in buffer',
                'selected_value': None,
                'selector_type': 'unknown',
            }

        try:
            # use JavaScript to detect selector type and select option
            js_code = """
            (params) => {
                const elementData = params.elementData;
                const targetText = params.targetText;

                // find element by coordinates
                const centerX = elementData.center_x;
                const centerY = elementData.center_y;
                const element = document.elementFromPoint(centerX, centerY);

                if (!element) {
                    return { success: false, message: 'Element not found at coordinates', selector_type: 'unknown' };
                }

                // 1. handle native select element
                let selectElement = element.closest('select');
                if (selectElement) {
                    // find matching options
                    let targetOption = null;
                    for (let i = 0; i < selectElement.options.length; i++) {
                        const option = selectElement.options[i];
                        if (option.text === targetText || option.text.includes(targetText) || targetText.includes(option.text)) {
                            targetOption = option;
                            break;
                        }
                    }

                    if (!targetOption) {
                        const availableOptions = Array.from(selectElement.options).map(opt => opt.text);
                        return {
                            success: false,
                            message: `Option "${targetText}" not found in native select. Available: ${availableOptions.join(', ')}`,
                            selector_type: 'native_select',
                            availableOptions: availableOptions
                        };
                    }

                    // select option
                    selectElement.selectedIndex = targetOption.index;
                    targetOption.selected = true;

                    // trigger event
                    selectElement.dispatchEvent(new Event('change', { bubbles: true }));
                    selectElement.dispatchEvent(new Event('input', { bubbles: true }));

                    return {
                        success: true,
                        message: `Successfully selected option: "${targetOption.text}"`,
                        selectedValue: targetOption.value,
                        selectedText: targetOption.text,
                        selector_type: 'native_select'
                    };
                }

                // 2. handle Ant Design Select
                let antSelect = element.closest('.ant-select');
                if (antSelect && !antSelect.classList.contains('ant-cascader')) {
                    // ensure dropdown is expanded (idempotent)
                    const selector = antSelect.querySelector('.ant-select-selector');
                    if (selector) {
                        const ensureExpanded = () => {
                            const visible = document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden)');
                            if (visible) return Promise.resolve(visible);
                            selector.click();
                            return new Promise(res => setTimeout(() => {
                                res(document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden)'));
                            }, 300));
                        };

                        return new Promise((resolve) => {
                            ensureExpanded().then((dropdown) => {
                                if (dropdown) {
                                    // find matching options
                                    const options = Array.from(dropdown.querySelectorAll('.ant-select-item-option'));
                                    let targetOption = null;

                                    for (let option of options) {
                                        const textEl = option.querySelector('.ant-select-item-option-content');
                                        const optionText = textEl ? textEl.textContent.trim() : option.textContent.trim();

                                        if (optionText === targetText ||
                                            optionText.includes(targetText) ||
                                            targetText.includes(optionText)) {
                                            targetOption = option;
                                            break;
                                        }
                                    }

                                    if (!targetOption) {
                                        const availableOptions = options.map(opt => {
                                            const textEl = opt.querySelector('.ant-select-item-option-content');
                                            return textEl ? textEl.textContent.trim() : opt.textContent.trim();
                                        });
                                        resolve({
                                            success: false,
                                            message: `Option "${targetText}" not found in ant-select. Available: ${availableOptions.join(', ')}`,
                                            selector_type: 'ant_select',
                                            availableOptions: availableOptions
                                        });
                                        return;
                                    }

                                    // click option
                                    targetOption.click();

                                    // trigger event
                                    antSelect.dispatchEvent(new Event('change', { bubbles: true }));

                                    const selectedText = targetOption.querySelector('.ant-select-item-option-content')?.textContent.trim() || targetOption.textContent.trim();
                                    const selectedValue = targetOption.getAttribute('data-value') || selectedText;

                                    resolve({
                                        success: true,
                                        message: `Successfully selected ant-select option: "${selectedText}"`,
                                        selectedValue: selectedValue,
                                        selectedText: selectedText,
                                        selector_type: 'ant_select'
                                    });
                                } else {
                                    resolve({
                                        success: false,
                                        message: 'Could not find ant-select dropdown after clicking',
                                        selector_type: 'ant_select'
                                    });
                                }
                            });
                        });
                    }
                }

                // 3. handle Ant Design Cascader
                let antCascader = element.closest('.ant-cascader');
                if (antCascader) {
                    // ensure cascader is expanded (idempotent)
                    const selector = antCascader.querySelector('.ant-select-selector');
                    if (selector) {
                        const ensureExpanded = () => {
                            const visible = document.querySelector('.ant-cascader-dropdown:not(.ant-cascader-dropdown-hidden)');
                            if (visible) return Promise.resolve(visible);
                            selector.click();
                            return new Promise(res => setTimeout(() => {
                                res(document.querySelector('.ant-cascader-dropdown:not(.ant-cascader-dropdown-hidden)'));
                            }, 300));
                        };

                        return new Promise((resolve) => {
                            ensureExpanded().then((dropdown) => {
                                if (dropdown) {
                                    // find matching options in first level
                                    const firstLevelOptions = Array.from(dropdown.querySelectorAll('.ant-cascader-menu:first-child .ant-cascader-menu-item'));
                                    let targetOption = null;

                                    for (let option of firstLevelOptions) {
                                        const optionText = option.textContent.trim();
                                        if (optionText === targetText ||
                                            optionText.includes(targetText) ||
                                            targetText.includes(optionText)) {
                                            targetOption = option;
                                            break;
                                        }
                                    }

                                    if (!targetOption) {
                                        const availableOptions = firstLevelOptions.map(opt => opt.textContent.trim());
                                        resolve({
                                            success: false,
                                            message: `Option "${targetText}" not found in cascader first level. Available: ${availableOptions.join(', ')}`,
                                            selector_type: 'ant_cascader',
                                            availableOptions: availableOptions
                                        });
                                        return;
                                    }

                                    // click option
                                    targetOption.click();

                                    // if it is leaf node (no sub options), trigger select event and close dropdown
                                    if (!targetOption.classList.contains('ant-cascader-menu-item-expand')) {
                                        antCascader.dispatchEvent(new Event('change', { bubbles: true }));

                                        // close dropdown
                                        setTimeout(() => {
                                            document.body.click();
                                        }, 100);
                                    }

                                    const selectedText = targetOption.textContent.trim();
                                    const selectedValue = targetOption.getAttribute('data-path-key') || selectedText;

                                    resolve({
                                        success: true,
                                        message: `Successfully selected cascader option: "${selectedText}"`,
                                        selectedValue: selectedValue,
                                        selectedText: selectedText,
                                        selector_type: 'ant_cascader'
                                    });
                                } else {
                                    resolve({
                                        success: false,
                                        message: 'Could not find cascader dropdown after clicking',
                                        selector_type: 'ant_cascader'
                                    });
                                }
                            });
                        });
                    }
                }

                // 4. handle other custom dropdown components
                let customDropdown = element.closest('[role="combobox"], [role="listbox"], .dropdown, .select');
                if (customDropdown) {
                    // try to click to expand
                    customDropdown.click();

                    setTimeout(() => {
                        const options = Array.from(document.querySelectorAll('[role="option"], .option, .item'));
                        let targetOption = null;

                        for (let option of options) {
                            const optionText = option.textContent.trim();
                            if (optionText === targetText ||
                                optionText.includes(targetText) ||
                                targetText.includes(optionText)) {
                                targetOption = option;
                                break;
                            }
                        }

                        if (targetOption) {
                            targetOption.click();
                            customDropdown.dispatchEvent(new Event('change', { bubbles: true }));

                            return {
                                success: true,
                                message: `Successfully selected custom dropdown option: "${targetOption.textContent.trim()}"`,
                                selectedValue: targetOption.getAttribute('value') || targetOption.textContent.trim(),
                                selectedText: targetOption.textContent.trim(),
                                selector_type: 'custom_dropdown'
                            };
                        }
                    }, 300);
                }

                // if no match, return failure
                return {
                    success: false,
                    message: 'No supported dropdown type found for selection. Element classes: ' + element.className,
                    selector_type: 'unsupported'
                };
            }
            """

            result = await self.page.evaluate(js_code, {'elementData': element, 'targetText': option_text})

            if result.get('success'):
                logging.debug(f"Successfully selected {result.get('selector_type')} option: {option_text}")
                return {
                    'success': True,
                    'message': result['message'],
                    'selected_value': result.get('selectedValue'),
                    'selected_text': result.get('selectedText'),
                    'selector_type': result.get('selector_type'),
                }
            else:
                logging.error(f"Failed to select dropdown option: {result.get('message')}")
                return {
                    'success': False,
                    'message': result.get('message', 'Unknown error'),
                    'selected_value': None,
                    'selector_type': result.get('selector_type', 'unknown'),
                    'available_options': result.get('availableOptions'),
                }

        except Exception as e:
            logging.error(f'Error selecting dropdown option: {str(e)}')
            return {'success': False, 'message': f'Error: {str(e)}', 'selected_value': None, 'selector_type': 'error'}

    async def select_cascade_level(self, id, option_text: str, level: int = 0) -> Dict[str, Any]:
        """Select cascade selector specific level option.

        Args:
            id: element ID
            option_text: option text to select
            level: cascade level (0 for first level, 1 for second level, etc.)

        Returns:
            Dict: operation result
        """
        element = self.page_element_buffer.get(str(id))
        if not element:
            return {
                'success': False,
                'message': f'Element with id {id} not found in buffer',
                'selector_type': 'unknown',
            }

        try:
            # use JavaScript to perform cascade selection
            js_code = """
            (params) => {
                const elementData = params.elementData;
                const targetText = params.targetText;
                const level = params.level;

                // find element by coordinates
                const centerX = elementData.center_x;
                const centerY = elementData.center_y;
                const element = document.elementFromPoint(centerX, centerY);

                if (!element) {
                    return { success: false, message: 'Element not found at coordinates', selector_type: 'unknown' };
                }

                // check if it is Ant Design Cascader
                let antCascader = element.closest('.ant-cascader');
                if (antCascader) {
                    return new Promise((resolve) => {
                        // if it is first level, need to click to open dropdown
                        if (level === 0) {
                            const selector = antCascader.querySelector('.ant-select-selector');
                            if (selector) {
                                selector.click();
                            }
                        }

                        setTimeout(() => {
                            const dropdown = document.querySelector('.ant-cascader-dropdown:not(.ant-cascader-dropdown-hidden)');
                            if (!dropdown) {
                                resolve({
                                    success: false,
                                    message: `Could not find cascader dropdown for level ${level}`,
                                    selector_type: 'ant_cascader'
                                });
                                return;
                            }

                            // select corresponding menu by level
                            const menus = dropdown.querySelectorAll('.ant-cascader-menu');
                            if (level >= menus.length) {
                                resolve({
                                    success: false,
                                    message: `Level ${level} not available, only ${menus.length} levels found`,
                                    selector_type: 'ant_cascader'
                                });
                                return;
                            }

                            const targetMenu = menus[level];
                            const options = Array.from(targetMenu.querySelectorAll('.ant-cascader-menu-item'));
                            let targetOption = null;

                            // find matching options
                            for (let option of options) {
                                const optionText = option.textContent.trim();
                                if (optionText === targetText ||
                                    optionText.includes(targetText) ||
                                    targetText.includes(optionText)) {
                                    targetOption = option;
                                    break;
                                }
                            }

                            if (!targetOption) {
                                const availableOptions = options.map(opt => opt.textContent.trim());
                                resolve({
                                    success: false,
                                    message: `Option "${targetText}" not found in level ${level}. Available: ${availableOptions.join(', ')}`,
                                    selector_type: 'ant_cascader',
                                    availableOptions: availableOptions
                                });
                                return;
                            }

                            // click option
                            targetOption.click();

                            const selectedText = targetOption.textContent.trim();
                            const selectedValue = targetOption.getAttribute('data-path-key') || selectedText;

                            // if it is last level or no sub options, trigger select event and close dropdown
                            if (!targetOption.classList.contains('ant-cascader-menu-item-expand')) {
                                setTimeout(() => {
                                    antCascader.dispatchEvent(new Event('change', { bubbles: true }));
                                    // close dropdown
                                    document.body.click();
                                }, 100);
                            }

                            resolve({
                                success: true,
                                message: `Successfully selected level ${level} option: "${selectedText}"`,
                                selectedValue: selectedValue,
                                selectedText: selectedText,
                                selector_type: 'ant_cascader',
                                level: level
                            });
                        }, level === 0 ? 500 : 300); // first level needs more time to wait for dropdown to open
                    });
                }

                // handle other types of cascade selectors
                return {
                    success: false,
                    message: 'Only Ant Design Cascader is supported for cascade selection',
                    selector_type: 'unsupported'
                };
            }
            """

            result = await self.page.evaluate(
                js_code, {'elementData': element, 'targetText': option_text, 'level': level}
            )

            if result.get('success'):
                logging.debug(f'Successfully selected level {level} option: {option_text}')
                return {
                    'success': True,
                    'message': result['message'],
                    'selected_value': result.get('selectedValue'),
                    'selected_text': result.get('selectedText'),
                    'selector_type': result.get('selector_type'),
                    'level': level,
                }
            else:
                logging.error(f"Failed to select level {level} option: {result.get('message')}")
                return {
                    'success': False,
                    'message': result.get('message', 'Unknown error'),
                    'selector_type': result.get('selector_type', 'unknown'),
                    'available_options': result.get('availableOptions'),
                    'level': level,
                }

        except Exception as e:
            logging.error(f'Error selecting cascade level {level} option: {str(e)}')
            return {'success': False, 'message': f'Error: {str(e)}', 'selector_type': 'error', 'level': level}

    async def drag(self, source_coords, target_coords):
        """Execute drag action with scroll container awareness.

        Note: This method uses coordinate conversion which may not work correctly
        with scroll containers. Consider using element-based drag if available.
        """

        source_x = source_coords.get('x')
        source_y = source_coords.get('y')
        target_x = target_coords.get('x')
        target_y = target_coords.get('y')

        try:
            # Convert document coordinates to viewport coordinates
            # Note: This assumes window-level scrolling and may not work with scroll containers
            viewport_source_x, viewport_source_y = await self._convert_document_to_viewport_coords(source_x, source_y)
            viewport_target_x, viewport_target_y = await self._convert_document_to_viewport_coords(target_x, target_y)

            # Check for potential scroll container issues
            scroll_state = await self.page.evaluate('''() => ({
                windowScrollX: window.pageXOffset || document.documentElement.scrollLeft,
                windowScrollY: window.pageYOffset || document.documentElement.scrollTop,
                hasScrollContainers: document.querySelectorAll('[style*="overflow"]').length > 0
            })''')

            if scroll_state.get('hasScrollContainers') and (scroll_state.get('windowScrollY') == 0 or scroll_state.get('windowScrollX') == 0):
                logging.warning(
                    f'Drag operation may be affected by scroll containers. '
                    f'Window scroll offset: ({scroll_state.get("windowScrollX")}, {scroll_state.get("windowScrollY")}), '
                    f'Scroll containers detected: {scroll_state.get("hasScrollContainers")}'
                )

            logging.debug(f'Drag action: source document=({source_x}, {source_y}) -> viewport=({viewport_source_x}, {viewport_source_y}), target document=({target_x}, {target_y}) -> viewport=({viewport_target_x}, {viewport_target_y})')

            # move to start position
            await self.page.mouse.move(viewport_source_x, viewport_source_y)
            await asyncio.sleep(0.1)

            # press mouse
            await self.page.mouse.down()
            await asyncio.sleep(0.1)

            # drag to target position
            await self.page.mouse.move(viewport_target_x, viewport_target_y)
            await asyncio.sleep(0.1)

            # release mouse
            await self.page.mouse.up()
            await asyncio.sleep(0.2)

            logging.debug(f'Drag completed from viewport ({viewport_source_x}, {viewport_source_y}) to ({viewport_target_x}, {viewport_target_y})')
            return True

        except Exception as e:
            logging.error(f'Drag action failed: {str(e)}')
            return False
    
    async def mouse_move(self, x: int | float, y: int | float) -> bool:
        """Move mouse to absolute coordinates (x, y).

        Note: This method assumes window-level scrolling. For pages using scroll containers,
        the coordinate conversion may be inaccurate. Consider using element-based hover instead.
        """
        # Initialize action context for error propagation
        ctx = ActionContext()
        action_context_var.set(ctx)
        ctx.element_info = {"action": "mouse_move", "x": x, "y": y}

        try:
            # Coerce to numbers in case strings are provided
            target_x = float(x)
            target_y = float(y)

            # Convert document coordinates to viewport coordinates
            # Note: This assumes window-level scrolling and may not work with scroll containers
            viewport_x, viewport_y = await self._convert_document_to_viewport_coords(target_x, target_y)

            # Detect potential scroll container issues (similar to drag method)
            if abs(target_x) > 100 or abs(target_y) > 100:
                scroll_state = await self.page.evaluate('''() => ({
                    windowScrollX: window.pageXOffset || document.documentElement.scrollLeft,
                    windowScrollY: window.pageYOffset || document.documentElement.scrollTop,
                    hasScrollContainers: document.querySelectorAll('[style*="overflow"]').length > 0
                })''')

                if scroll_state.get('hasScrollContainers') and (scroll_state.get('windowScrollY') == 0 or scroll_state.get('windowScrollX') == 0):
                    logging.warning(
                        f'Mouse move to ({target_x}, {target_y}) may be affected by scroll containers. '
                        f'Window scroll offset: ({scroll_state.get("windowScrollX")}, {scroll_state.get("windowScrollY")}), '
                        f'Scroll containers detected. Consider using hover on element instead.'
                    )

            logging.info(f"Mouse move: document=({target_x}, {target_y}) -> viewport=({viewport_x}, {viewport_y})")
            await self.page.mouse.move(viewport_x, viewport_y)
            await asyncio.sleep(0.1)
            return True
        except Exception as e:
            logging.error(f"Mouse move failed: {str(e)}")
            ctx.set_error(
                ERROR_PLAYWRIGHT,
                f"Mouse move action failed to position ({x}, {y})",
                target_x=target_x if 'target_x' in locals() else x,
                target_y=target_y if 'target_y' in locals() else y,
                playwright_error=str(e)
            )
            return False

    async def mouse_wheel(self, delta_x: int | float = 0, delta_y: int | float = 0) -> bool:
        """Scroll the mouse wheel by delta values."""
        # Initialize action context for error propagation
        ctx = ActionContext()
        action_context_var.set(ctx)
        ctx.element_info = {"action": "mouse_wheel", "deltaX": delta_x, "deltaY": delta_y}

        try:
            dx = float(delta_x) if delta_x is not None else 0.0
            dy = float(delta_y) if delta_y is not None else 0.0
            await self.page.mouse.wheel(dx, dy)
            logging.info(f"mouse wheel by (deltaX={dx}, deltaY={dy})")
            await asyncio.sleep(0.1)
            return True
        except Exception as e:
            logging.error(f"Mouse wheel failed: {str(e)}")
            ctx.set_error(
                ERROR_PLAYWRIGHT,
                f"Mouse wheel action failed with delta ({delta_x}, {delta_y})",
                deltaX=dx if 'dx' in locals() else delta_x,
                deltaY=dy if 'dy' in locals() else delta_y,
                playwright_error=str(e)
            )
            return False