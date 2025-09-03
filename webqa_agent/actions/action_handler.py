import asyncio
import base64
import json
import os
import re
from typing import Any, Dict, List, Optional, Union

from playwright.async_api import Page

from webqa_agent.browser.driver import *


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

    async def smart_navigate_to_page(self, page: Page, url: str, cookies=None) -> bool:
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
                return False

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

    async def click(self, id) -> bool:
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
                return False

            logging.debug(
                f"Attempting to click element: id={id}, tagName='{element.get('tagName')}', innerText='{element.get('innerText', '').strip()[:50]}', selector='{element.get('selector')}'"
            )

        except Exception as e:
            logging.error(f'failed to get element {id}, element: {self.page_element_buffer.get(id)}, error: {e}')
            return False

        return await self.click_using_coordinates(element, id)

    async def click_using_coordinates(self, element, id) -> bool:
        """Helper function to click using coordinates."""
        x = element.get('center_x')
        y = element.get('center_y')
        try:
            if x is not None and y is not None:
                logging.debug(f'mouse click at element {id}, coordinate=({x}, {y})')
                try:
                    await self.page.mouse.click(x, y)
                except Exception as e:
                    logging.error(f'mouse click error: {e}\nwith coordinates:  ({x}, {y})')
                return True
            else:
                logging.error('Coordinates not found in element data')
                return False
        except Exception as e:
            logging.error(f'Error clicking using coordinates: {e}')
            return False

    async def hover(self, id) -> bool:
        element = self.page_element_buffer.get(str(id))
        if not element:
            logging.error(f'Element with id {id} not found in buffer for hover action.')
            return False

        logging.debug(
            f"Attempting to hover over element: id={id}, tagName='{element.get('tagName')}', innerText='{element.get('innerText', '').strip()[:50]}', selector='{element.get('selector')}'"
        )

        scroll_y = await self.page.evaluate('() => window.scrollY')

        x = element.get('center_x')
        y = element.get('center_y')
        if x is not None and y is not None:
            y = y - scroll_y
            logging.debug(f'mouse hover at ({x}, {y})')
            await self.page.mouse.move(x, y)
            await asyncio.sleep(0.5)
            return True
        else:
            logging.error('Coordinates not found in element data')
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
        try:
            element = self.page_element_buffer.get(str(id))
            if not element:
                logging.error(f'Element with id {id} not found in buffer for type action.')
                return False

            logging.debug(
                f"Attempting to type into element: id={id}, tagName='{element.get('tagName')}', innerText='{element.get('innerText', '').strip()[:50]}', selector='{element.get('selector')}', clear_before_type={clear_before_type}"
            )

            if clear_before_type:
                if not await self.clear(id):
                    logging.warning(f'Failed to clear element {id} before typing, but will attempt to type anyway.')

            # click element to get focus
            try:
                if not await self.click(str(id)):
                    return False
            except Exception as e:
                logging.error(f"Error 'type' clicking using coordinates: {e}")
                logging.error(f'id type {type(id)}, id: {id}')
                return False

            await asyncio.sleep(1)
            # Type text with CSS validation and XPath fallback
            selector = element['selector']

            # First validate CSS selector format
            if self._is_valid_css_selector(selector):
                try:
                    # Try using CSS selector
                    await self.page.locator(selector).fill(text)
                    logging.debug(f"Typed '{text}' into element {id} using CSS selector: {selector}")
                except Exception as css_error:
                    logging.warning(f'CSS selector type failed for element {id}: {css_error}')
                    # CSS selector failed, try XPath
                    xpath = element.get('xpath')
                    if xpath:
                        try:
                            await self.page.locator(f'xpath={xpath}').fill(text)
                            logging.debug(f"Typed '{text}' into element {id} using XPath fallback: {xpath}")
                        except Exception as xpath_error:
                            logging.error(
                                f'Both CSS and XPath type failed for element {id}. CSS error: {css_error}, XPath error: {xpath_error}'
                            )
                            return False
                    else:
                        logging.error(f'CSS selector type failed and no XPath available for element {id}')
                        return False
            else:
                logging.warning(f'Invalid CSS selector format for element {id}: {selector}')
                # CSS selector format invalid, use XPath directly
                xpath = element.get('xpath')
                if xpath:
                    try:
                        await self.page.locator(f'xpath={xpath}').fill(text)
                        logging.debug(f"Typed '{text}' into element {id} using XPath: {xpath}")
                    except Exception as xpath_error:
                        logging.error(f'XPath type failed for element {id}: {xpath_error}')
                        return False
                else:
                    logging.error(f'Invalid CSS selector and no XPath available for element {id}')
                    return False

            await asyncio.sleep(1)
            return True
        except Exception as e:
            logging.error(f'Failed to type into element {id}: {e}')
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

    async def clear(self, id) -> bool:
        """Clears the text in the specified input element."""
        try:
            element_to_clear = self.page_element_buffer.get(str(id))
            if not element_to_clear:
                logging.error(f'Element with id {id} not found in buffer for clear action.')
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

            # Clear input with CSS validation and XPath fallback
            # First validate CSS selector format
            if self._is_valid_css_selector(selector):
                try:
                    # Try using CSS selector
                    await self.page.locator(selector).fill('')
                    logging.debug(f'Cleared input for element {id} using CSS selector: {selector}')
                except Exception as css_error:
                    logging.warning(f'CSS selector clear failed for element {id}: {css_error}')
                    # CSS selector failed, try XPath
                    xpath = element_to_clear.get('xpath')
                    if xpath:
                        try:
                            await self.page.locator(f'xpath={xpath}').fill('')
                            logging.debug(f'Cleared input for element {id} using XPath fallback: {xpath}')
                        except Exception as xpath_error:
                            logging.error(
                                f'Both CSS and XPath clear failed for element {id}. CSS error: {css_error}, XPath error: {xpath_error}'
                            )
                            return False
                    else:
                        logging.error(f'CSS selector clear failed and no XPath available for element {id}')
                        return False
            else:
                logging.warning(f'Invalid CSS selector format for element {id}: {selector}')
                # CSS selector format invalid, use XPath directly
                xpath = element_to_clear.get('xpath')
                if xpath:
                    try:
                        await self.page.locator(f'xpath={xpath}').fill('')
                        logging.debug(f'Cleared input for element {id} using XPath: {xpath}')
                    except Exception as xpath_error:
                        logging.error(f'XPath clear failed for element {id}: {xpath_error}')
                        return False
                else:
                    logging.error(f'Invalid CSS selector and no XPath available for element {id}')
                    return False

            await asyncio.sleep(0.5)
            return True
        except Exception as e:
            logging.error(f'Failed to clear element {id}: {e}')
            return False

    async def keyboard_press(self, key) -> bool:
        """Press keyboard key.

        Args:
            key: key name

        Returns:
            bool: True if success, False if failed
        """
        await self.page.keyboard.press(key)
        await asyncio.sleep(1)
        return True

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
        try:
            # Support single file and multiple files
            if isinstance(file_path, str):
                file_paths = [file_path]
            elif isinstance(file_path, list):
                file_paths = file_path
            else:
                logging.error(f'file_path must be str or list, got {type(file_path)}')
                return False

            valid_file_paths = []
            for fp in file_paths:
                if not fp or not isinstance(fp, str):
                    continue
                if not os.path.exists(fp):
                    logging.error(f'File not found: {fp}')
                    continue
                valid_file_paths.append(fp)

            if not valid_file_paths:
                logging.error('No valid files to upload.')
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
                x = element.get('center_x')
                y = element.get('center_y')
                await self.page.mouse.click(x, y)
                logging.debug(f'Clicked option_id {option_id} ({option_text}) directly.')
                return {
                    'success': True,
                    'message': f"Clicked dropdown option '{option_text}' directly.",
                    'selected_value': element.get('innerText'),
                    'selector_type': 'ant_select_option',
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
        """Execute drag action."""

        source_x = source_coords.get('x')
        source_y = source_coords.get('y')
        target_x = target_coords.get('x')
        target_y = target_coords.get('y')

        try:

            # move to start position
            await self.page.mouse.move(source_x, source_y)
            await asyncio.sleep(0.1)

            # press mouse
            await self.page.mouse.down()
            await asyncio.sleep(0.1)

            # drag to target position
            await self.page.mouse.move(target_x, target_y)
            await asyncio.sleep(0.1)

            # release mouse
            await self.page.mouse.up()
            await asyncio.sleep(0.2)

            logging.debug(f'Drag completed from ({source_x}, {source_y}) to ({target_x}, {target_y})')
            return True

        except Exception as e:
            logging.error(f'Drag action failed: {str(e)}')
            return False
