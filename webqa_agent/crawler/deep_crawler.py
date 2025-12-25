import datetime
import json
import logging
import re
import time
from enum import Enum
from itertools import groupby
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from playwright.async_api import Page
from pydantic import BaseModel, Field

from webqa_agent.crawler.dom_cacher import DomCacher
from webqa_agent.crawler.dom_tree import DomTreeNode as dtree

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_time() -> str:
    """Get the current time as a formatted string.

    Returns:
        Timestamp format: YYYYMMDD_HH_MM_SS
    """
    return datetime.datetime.now().strftime('%Y%m%d_%H_%M_%S')


def _normalize_keys(template: Optional[Iterable[Union[str, 'ElementKey']]]) -> Optional[List[str]]:
    """Normalize template keys to string format.

    Args:
        template: Template containing ElementKey enums or strings.

    Returns:
        List of normalized string keys, or None if template is None.
    """
    if template is None:
        return None

    normalized = []
    for key in template:
        try:
            normalized.append(key.value if hasattr(key, 'value') else str(key))
        except Exception:
            normalized.append(str(key))
    return normalized


# ============================================================================
# ENUMS AND CONSTANTS
# ============================================================================

class ElementKey(Enum):
    """Enumeration for element attribute keys."""
    NODE = 'node'
    TAG_NAME = 'tagName'
    CLASS_NAME = 'className'
    INNER_TEXT = 'innerText'
    ATTRIBUTES = 'attributes'
    VIEWPORT = 'viewport'
    CENTER_X = 'center_x'
    CENTER_Y = 'center_y'
    IS_VISIBLE = 'isVisible'
    IS_INTERACTIVE = 'isInteractive'
    IS_VALID_TEXT = 'isValidText'
    IS_TOP_ELEMENT = 'isTopElement'
    IS_IN_VIEWPORT = 'isInViewport'
    XPATH = 'xpath'
    SELECTOR = 'selector'
    STYLES = 'styles'

    def __str__(self) -> str:
        """Return the string representation of the enum value."""
        return self.value


DEFAULT_OUTPUT_TEMPLATE = [
    ElementKey.TAG_NAME.value,
    ElementKey.INNER_TEXT.value,
    ElementKey.ATTRIBUTES.value,  # Include attributes to prevent LLM hallucinations about target="_blank"
    ElementKey.CENTER_X.value,
    ElementKey.CENTER_Y.value
]


# ============================================================================
# DATA MODELS
# ============================================================================

class ElementMap(BaseModel):
    """A wrapper for a dictionary of elements that provides a cleansing
    method."""
    data: Dict[str, Any] = Field(default_factory=dict)

    def clean(self, output_template: Optional[List[str]] = None) -> Dict[str, Any]:
        """Cleanses the element map, returning a new dictionary with filtered
        attributes.

        Args:
            output_template: A list of keys to include in the cleansed output.
                             If None, DEFAULT_OUTPUT_TEMPLATE is used.

        Returns:
            A dictionary with the cleansed element data.
        """
        if output_template is None:
            output_template = DEFAULT_OUTPUT_TEMPLATE

        def to_key(k):
            """Convert key to string format."""
            return k.value if hasattr(k, 'value') else str(k)

        keys = [to_key(k) for k in output_template]
        result = {}

        for e_id, element_data in self.data.items():
            cleaned_element = {}

            for key in keys:
                value = element_data.get(key)
                if value is not None:
                    cleaned_element[key] = value

            # Only include elements that have at least one valid field
            if cleaned_element:
                result[e_id] = cleaned_element

        return result


class CrawlResultModel(BaseModel):
    """Model for crawl results containing flattened and hierarchical element
    data."""
    element_tree: Dict[str, Any] = Field(default_factory=dict)
    flat_element_map: ElementMap = Field(default_factory=ElementMap)
    diff_element_map: ElementMap = Field(default_factory=ElementMap)

    # Page status fields for unsupported page detection (backward compatible)
    page_status: str = Field(default='NORMAL', description='NORMAL or UNSUPPORTED_PAGE')
    page_type: Optional[str] = Field(default=None, description='pdf, plugin, download, etc.')

    def raw_dict(self) -> Dict[str, Any]:
        """Get raw flattened element data with all fields."""
        return self.flat_element_map.data

    def clean_dict(self, template: Optional[Iterable[Union[str, 'ElementKey']]] = None) -> Dict[str, Any]:
        """Get cleaned flattened element data with fields filtered by
        template."""
        return self.flat_element_map.clean(output_template=_normalize_keys(template))

    def diff_dict(self, template: Optional[Iterable[Union[str, 'ElementKey']]] = None) -> Dict[str, Any]:
        """Get DOM difference element data with specified template."""
        return self.diff_element_map.clean(output_template=_normalize_keys(template))

    def to_llm_json(self, template: Optional[Iterable[Union[str, 'ElementKey']]] = None) -> str:
        """Convert filtered elements to LLM-compatible JSON format."""
        return json.dumps(self.clean_dict(template=template), ensure_ascii=False, separators=(',', ':'))


# ============================================================================
# MAIN CRAWLER CLASS
# ============================================================================

class DeepCrawler:
    """A deep crawler for recursively extracting structured element data from
    web pages.

    This class injects JavaScript payloads into Playwright pages to build
    hierarchical DOM element trees, capturing properties such as visibility,
    interactivity, and positioning. It supports element highlighting for
    debugging and provides comprehensive DOM change detection capabilities.
    """

    # Class-level constants
    _default_dir = Path(__file__).parent
    DETECTOR_JS = _default_dir / 'js' / 'element_detector.js'
    REMOVER_JS = _default_dir / 'js' / 'marker_remover.js'
    RESULTS_DIR = _default_dir / 'results'
    SCREENSHOTS_DIR = _default_dir / 'screenshots'

    def __init__(self, page: Page, depth: int = 0):
        """Initialize the DeepCrawler instance.

        Args:
            page: The Playwright Page object to crawl.
            depth: The current crawling depth level.

        Raises:
            ValueError: If page is not a valid Playwright Page object.
        """
        if not isinstance(page, Page):
            raise ValueError('Crawler page must be a Playwright Page object')

        self.page = page
        self.depth = depth
        self.element_tree = None  # Hierarchical element tree structure
        self.dom_cacher = DomCacher()  # DOM change detection manager
        self._cached_element_tree = None  # Cached DOM tree for comparison
        self._last_crawl_time = None  # Timestamp of last crawl operation

    # ------------------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------------------

    async def _detect_page_type(self, page: Page) -> Tuple[str, Optional[str]]:
        """Detect if the page is an unsupported type (PDF, plugin, etc.) using
        multi-layered detection.

        Uses a 3-layer detection strategy for high reliability:
        1. URL extension check (fast, reliable)
        2. PDF embed element detection (catches Chromium PDF viewer)
        3. document.contentType check (backup)

        Args:
            page: The Playwright Page object to check.

        Returns:
            Tuple of (status, page_type):
                - ("NORMAL", None) for regular HTML pages
                - ("UNSUPPORTED_PAGE", "pdf") for PDF documents
                - ("UNSUPPORTED_PAGE", "plugin") for plugin content
                - ("UNSUPPORTED_PAGE", "download") for download files
        """
        try:
            # === Layer 1: URL Extension Check (Fastest, Most Reliable) ===
            url = page.url.lower()

            # PDF detection via URL
            if url.endswith('.pdf'):
                logging.info(f'Detected PDF via URL suffix: {url}')
                return ('UNSUPPORTED_PAGE', 'pdf')

            # Download file detection via URL
            download_extensions = ['.zip', '.rar', '.exe', '.dmg', '.pkg', '.deb', '.tar', '.gz']
            for ext in download_extensions:
                if url.endswith(ext):
                    logging.info(f'Detected download file via URL: {url}')
                    return ('UNSUPPORTED_PAGE', 'download')

            # === Layer 2: PDF Embed Element Detection (Catches Chromium PDF Viewer) ===
            has_pdf_embed = await page.evaluate("""() => {
                return document.querySelector('embed[type="application/pdf"]') !== null ||
                       document.querySelector('object[type="application/pdf"]') !== null ||
                       document.querySelector('iframe[src*=".pdf"]') !== null;
            }""")

            if has_pdf_embed:
                logging.info(f'Detected embedded PDF viewer on page: {url}')
                return ('UNSUPPORTED_PAGE', 'pdf')

            # === Layer 3: document.contentType Check (Backup Method) ===
            content_type = await page.evaluate("() => document.contentType || ''")

            # PDF detection via content type
            if content_type == 'application/pdf':
                logging.info(f'Detected PDF via document.contentType: {url}')
                return ('UNSUPPORTED_PAGE', 'pdf')

            # Plugin detection (Flash, Silverlight, etc.)
            plugin_patterns = [
                'application/x-shockwave-flash',
                'application/x-silverlight',
                'application/x-java-applet'
            ]
            for pattern in plugin_patterns:
                if pattern in content_type:
                    logging.info(f'Detected plugin content ({pattern}): {url}')
                    return ('UNSUPPORTED_PAGE', 'plugin')

            # Regular HTML page
            return ('NORMAL', None)

        except Exception as e:
            # On any error, fail safely to NORMAL to avoid false positives
            logging.warning(f'Page type detection failed (assuming NORMAL page): {e}')
            return ('NORMAL', None)

    # ------------------------------------------------------------------------
    # CORE CRAWLING METHODS
    # ------------------------------------------------------------------------

    async def crawl(
            self,
            page: Optional[Page] = None,
            highlight: bool = False,
            filter_text: bool = False,
            filter_media: bool = False,
            viewport_only: bool = False,
            include_styles: bool = False,
            cache_dom: bool = False,
    ) -> CrawlResultModel:
        """Inject JavaScript to crawl the page and return structured element
        data.

        Args:
            page: The Playwright Page to crawl. Defaults to instance page.
            highlight: Whether to visually highlight detected elements (master switch).
            filter_text: Whether to include text nodes in highlighting when highlight is enabled.
            filter_media: Whether to include media elements in highlighting when highlight is enabled.
            viewport_only: Whether to restrict detection to current viewport.
            include_styles: Whether to include styles in the result.
            cache_dom: Whether to cache the DOM tree for change detection.

        Returns:
            CrawlResultModel containing the structured crawl data.
        """
        if page is None:
            page = self.page

        # Multi-layer detection of unsupported page types (PDF, plugins, etc.)
        page_status, page_type = await self._detect_page_type(page)
        if page_status == 'UNSUPPORTED_PAGE':
            logging.warning(f'Detected unsupported page type: {page_type}, skipping crawl')
            return CrawlResultModel(
                flat_element_map=ElementMap(data={}),
                element_tree={},
                page_status=page_status,
                page_type=page_type
            )

        try:

            try:
                if hasattr(page, 'frames') and len(page.frames) > 1:
                    _, merged_id_map = await self.crawl_all_frames(page=page, enable_highlight=highlight)
                    return CrawlResultModel(
                        flat_element_map=ElementMap(data=merged_id_map or {}),
                        element_tree={}
                    )
            except Exception:
                pass

            # Build JavaScript payload for element detection
            payload = (
                f'(() => {{'
                f'window._highlight = {str(highlight).lower()};'
                f'window._filterText = {str(filter_text).lower()};\n'
                f'window._filterMedia = {str(filter_media).lower()};\n'
                f'window._viewportOnly = {str(viewport_only).lower()};\n'
                f'window._includeStyles = {str(include_styles).lower()};\n'
                f'\n{self.read_js(self.DETECTOR_JS)}'
                f'\nreturn buildElementTree();'
                f'}})()'
            )

            # Execute JavaScript and extract results
            self.element_tree, flat_elements = await page.evaluate(payload)

            result = CrawlResultModel(
                flat_element_map=ElementMap(data=flat_elements or {}),
                element_tree=self.element_tree or {}
            )

            if cache_dom and self.element_tree:
                dom_tree = dtree.build_root(self.element_tree)
                self._cached_element_tree = dom_tree
                self._last_crawl_time = time.time()

                diff_elements = self.dom_cacher.detect_dom_diff(
                    current_tree=dom_tree,
                    current_url=page.url
                )

                if diff_elements['has_changes']:
                    logging.debug(f'DOM change result: {diff_elements}')

                result.diff_element_map = ElementMap(data=self.extract_interactive_elements(get_new_elems=True))

            return result

        except Exception as e:
            logging.error(f'JavaScript injection failed during element detection: {e}')
            return CrawlResultModel()

    def extract_interactive_elements(self, get_new_elems: bool = False) -> Dict:
        """Extract interactive elements with comprehensive attribute
        information.

        Args:
            get_new_elems: Whether to return only newly detected elements.

        Returns:
            Dictionary mapping element IDs to their attribute dictionaries.
        """
        # Determine data source based on operation mode
        if get_new_elems:
            if not self._cached_element_tree:
                return {}
            root = self._cached_element_tree
        else:
            if not self.element_tree:
                return {}
            root = dtree.build_root(self.element_tree)

        elements = {}

        if root:
            for node in root.pre_iter():
                if not all([
                    node.isInteractive,
                    node.isVisible,
                    node.isTopElement,
                    node.center_x is not None,
                    node.center_y is not None
                ]):
                    continue

                # Filter for new elements when requested
                if get_new_elems and not node.is_new:
                    continue

                # Validate viewport dimensions
                viewport = node.viewport or {}
                if viewport.get('width') is None or viewport.get('height') is None:
                    continue

                # Build comprehensive element attribute dictionary
                elements[str(node.highlightIndex)] = {
                    str(ElementKey.TAG_NAME): node.tagName,
                    str(ElementKey.CLASS_NAME): node.className,
                    str(ElementKey.INNER_TEXT): node.innerText[:200],
                    str(ElementKey.ATTRIBUTES): node.attributes,
                    str(ElementKey.VIEWPORT): node.viewport,
                    str(ElementKey.CENTER_X): node.center_x,
                    str(ElementKey.CENTER_Y): node.center_y,
                    str(ElementKey.IS_VISIBLE): node.isVisible,
                    str(ElementKey.IS_INTERACTIVE): node.isInteractive,
                    str(ElementKey.IS_TOP_ELEMENT): node.isTopElement,
                    str(ElementKey.IS_IN_VIEWPORT): node.isInViewport,
                    str(ElementKey.XPATH): node.xpath,
                    str(ElementKey.SELECTOR): node.selector
                }

        return elements

    def get_text(self, fmt: str = 'json') -> str:
        """Extract and concatenate all text content from the crawled DOM tree.

        This method intelligently filters text content to avoid duplicates and wrapper nodes,
        collecting only meaningful leaf text nodes and deduplicating consecutive identical texts.

        Args:
            fmt: Output format, currently supports "json" (default).

        Returns:
            JSON string containing array of extracted text content.
        """

        def _normalize_text(s: str) -> str:
            """Normalize text by collapsing whitespace and trimming."""
            s = re.sub(r'\s+', ' ', s).strip()
            return s

        def _has_text(n) -> bool:
            """Check if a node has meaningful text content."""
            return bool(getattr(n, 'innerText', None) and n.innerText.strip())

        def _is_leaf_text_node(n) -> bool:
            """Determine if a node is a leaf text node (no children with
            text)."""
            children = getattr(n, 'children', None) or []
            return not any(_has_text(c) for c in children)

        def _dedupe_consecutive(seq):
            """Remove consecutive duplicate items from sequence."""
            return [k for k, _ in groupby(seq)]

        # Early return if no element tree available
        if not self.element_tree:
            return ''

        # Build DOM tree from hierarchical data
        root = dtree.build_root(self.element_tree)
        if root is None:
            return ''

        # Collect only leaf text nodes and skip wrapper nodes
        items = []
        for n in root.pre_iter():
            # Skip nodes without meaningful text
            if not _has_text(n):
                continue

            # For non-leaf nodes, check if they're wrapper nodes
            if not _is_leaf_text_node(n):
                # Skip "wrapper" nodes: parent text identical to any direct child text
                normalized_text = _normalize_text(n.innerText)
                child_texts = [
                    _normalize_text(c.innerText)
                    for c in (n.children or [])
                    if _has_text(c)
                ]
                # Skip if parent text matches any child text (wrapper node)
                if normalized_text in child_texts:
                    continue

            # Add normalized text to collection
            items.append(_normalize_text(n.innerText))

        # Final deduplication: collapse adjacent duplicates
        items = _dedupe_consecutive(items)

        # Return as compact JSON array
        return json.dumps(items, ensure_ascii=False, separators=(',', ':'))

    async def crawl_all_frames(self, page=None, enable_highlight=False):
        """爬取主页面及所有 iframe 的元素（支持跨域与嵌套），并返回统一的 id 列表与映射。

        返回值:
            (ids, id_map)
                - ids: List[str] 高亮编号（全局唯一）
                - id_map: Dict[str, Dict] 元素信息，包含 tagName/className/innerText/center_x/center_y
                  其中 center_x/center_y 为“主页面视口坐标”，可直接用于 page.mouse.click
        """
        if not page:
            page = self.page

        import logging

        ids = []
        merged_id_map: Dict[str, Dict[str, Any]] = {}

        # helper: frame scroll
        async def _get_frame_scroll(f):
            try:
                return await f.evaluate('() => ({x: window.scrollX, y: window.scrollY})')
            except Exception:
                return {'x': 0, 'y': 0}

        # helper: accumulate iframe offsets to top-page viewport
        async def _accumulate_iframe_offsets(f):
            total_left, total_top = 0, 0
            cur = f
            while True:
                parent = cur.parent_frame
                if not parent:
                    break
                try:
                    el = await cur.frame_element()
                    rect = await el.evaluate('(el) => el.getBoundingClientRect()')
                    total_left += rect.get('left', 0) or 0
                    total_top  += rect.get('top', 0) or 0
                except Exception:
                    pass
                cur = parent
            return total_left, total_top

        # 1) main frame first (base = 0)
        try:
            payload_main = f'window.__highlightBase__ = 0; window._highlight = {str(enable_highlight).lower()};\n{self.read_js(self.DETECTOR_JS)}'
            await page.evaluate(payload_main)
            main_tree, main_id_map = await page.evaluate('buildElementTree()')
            # 保持与单 frame 逻辑一致：直接使用 detector 返回的文档坐标（含主页面滚动）
            for k, v in (main_id_map or {}).items():
                key = str(k)
                ids.append(key)
                # Keep all fields from the detector, ensuring we have selector/xpath for actions
                # Mark as main frame (frame_url=None means main frame)
                v['frame_url'] = None
                merged_id_map[key] = v
        except Exception as e:
            logging.warning(f'Main frame crawl failed: {e}')

        # 2) sub frames
        frames = page.frames
        for idx, frame in enumerate(frames):
            if frame == page.main_frame:
                continue
            try:
                highlight_base = (idx + 1) * 1000
                payload = f'window.__highlightBase__ = {highlight_base}; window._highlight = {str(enable_highlight).lower()};\n{self.read_js(self.DETECTOR_JS)}'
                await frame.evaluate(payload)
                iframe_tree, iframe_id_map = await frame.evaluate('buildElementTree()')
                frame_scroll = await _get_frame_scroll(frame)
                total_left, total_top = await _accumulate_iframe_offsets(frame)
                top_scroll = await _get_frame_scroll(page)

                # Get frame URL for later action execution in correct frame context
                frame_url = frame.url
                
                for k, v in (iframe_id_map or {}).items():
                    try:
                        # frame document -> frame viewport
                        vx = (v.get('center_x') or 0) - (frame_scroll.get('x') or 0)
                        vy = (v.get('center_y') or 0) - (frame_scroll.get('y') or 0)
                        # frame viewport -> top-page viewport
                        gvx = total_left + vx
                        gvy = total_top + vy
                        # top-page viewport -> top-page document
                        gx = gvx + (top_scroll.get('x') or 0)
                        gy = gvy + (top_scroll.get('y') or 0)
                        v['center_x'] = gx
                        v['center_y'] = gy
                    except Exception:
                        pass
                    key = str(k)
                    ids.append(key)
                    # Keep all fields from the detector, ensuring we have selector/xpath for actions
                    # Store frame URL so ActionHandler can execute actions in the correct frame context
                    v['frame_url'] = frame_url
                    merged_id_map[key] = v
            except Exception as e:
                logging.warning(f'Sub frame crawl failed: {e}')

        return ids, merged_id_map

    # ------------------------------------------------------------------------
    # DOM CACHE MANAGEMENT
    # ------------------------------------------------------------------------

    def clear_dom_cache(self) -> None:
        """Clear the DOM change detection cache and reset internal state."""
        self.dom_cacher.clear_cache()
        self._cached_element_tree = None
        self._last_crawl_time = None

    # ------------------------------------------------------------------------
    # UTILITY METHODS
    # ------------------------------------------------------------------------

    @staticmethod
    def read_js(file_path: Path) -> str:
        """Read and return the content of a JavaScript file.

        Args:
            file_path: Path to the JavaScript file.

        Returns:
            The content of the JavaScript file as a string.
        """
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()

    @staticmethod
    def dump_json(node: Dict[str, Any], path: Path) -> None:
        """Serialize a dictionary to a JSON file with proper formatting.

        Args:
            node: The dictionary to serialize.
            path: The output file path.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(node, f, ensure_ascii=False, indent=2)

    @staticmethod
    def smart_truncate_page_text(
        text_array: List[str],
        max_tokens: int = 3000,
        strategy: str = 'head_tail_sample'
    ) -> Dict[str, Any]:
        """Intelligently truncate page text while preserving semantic
        completeness.

        Based on 2024 research on semantic chunking and context preservation:
        - Avoids "lost-in-the-middle" problem
        - Preserves page structure (head, middle sample, tail)
        - Maintains overall context and flow

        Args:
            text_array: Original text array from get_text()
            max_tokens: Maximum token budget (default: 3000)
            strategy: Truncation strategy (currently supports "head_tail_sample")

        Returns:
            Dict containing:
                - summary: Overview of the truncation
                - text_content: Sampled text segments
                - coverage: Coverage ratio (selected/total)
                - estimated_tokens: Estimated token count
        """
        if not text_array:
            return {
                'summary': 'No text content found',
                'text_content': [],
                'coverage': '0/0 (0%)',
                'estimated_tokens': 0,
                'strategy_used': strategy
            }

        total_items = len(text_array)
        # Conservative estimate: 1 token ≈ 2 chars (mixed Chinese/English)
        char_budget = max_tokens * 2

        if strategy == 'head_tail_sample':
            result_parts = []
            current_chars = 0

            # Keep head 30% (navigation, titles, important info)
            keep_head = int(total_items * 0.3)
            for item in text_array[:keep_head]:
                if current_chars + len(item) > char_budget * 0.5:
                    break
                result_parts.append(item)
                current_chars += len(item)

            # Middle sampling (max 20 samples to maintain page flow)
            middle_start = keep_head
            middle_end = max(keep_head, total_items - int(total_items * 0.1))
            middle_section = text_array[middle_start:middle_end]

            if middle_section:
                sample_rate = max(1, len(middle_section) // 20)
                for item in middle_section[::sample_rate]:
                    if current_chars + len(item) > char_budget * 0.8:
                        break
                    result_parts.append(item)
                    current_chars += len(item)

            # Keep tail 10% (footer, contact, legal info)
            keep_tail = int(total_items * 0.1)
            for item in text_array[-keep_tail:] if keep_tail > 0 else []:
                if current_chars + len(item) > char_budget:
                    break
                result_parts.append(item)
                current_chars += len(item)

            return {
                'summary': f'Intelligently sampled {len(result_parts)} from {total_items} text segments',
                'text_content': result_parts,
                'coverage': f'{len(result_parts)}/{total_items} ({len(result_parts)/total_items*100:.1f}%)',
                'estimated_tokens': current_chars // 2,
                'strategy_used': strategy
            }

        else:
            # Fallback: simple truncation
            result = []
            chars = 0
            for item in text_array:
                if chars + len(item) > char_budget:
                    break
                result.append(item)
                chars += len(item)

            return {
                'summary': f'Simple truncation: {len(result)}/{total_items} items',
                'text_content': result,
                'coverage': f'{len(result)}/{total_items} ({len(result)/total_items*100:.1f}%)',
                'estimated_tokens': chars // 2,
                'strategy_used': 'simple_truncate'
            }

    # ------------------------------------------------------------------------
    # VISUAL DEBUGGING METHODS
    # ------------------------------------------------------------------------

    async def remove_marker(self, page: Optional[Page] = None) -> None:
        """Remove visual highlight markers from the page and all frames.

        Args:
            page: The Playwright Page to clean. Defaults to instance page.
        """
        if page is None:
            page = self.page
        try:
            script = self.read_js(self.REMOVER_JS)
            # Execute in main page
            await page.evaluate(script)

            # Execute in all frames
            if hasattr(page, 'frames'):
                for frame in page.frames:
                    try:
                        await frame.evaluate(script)
                    except Exception:
                        # Ignore errors for individual frames (e.g., cross-origin)
                        pass
        except Exception as e:
            logging.error(f'Failed to remove highlight markers: {e}')

    async def take_screenshot(
            self,
            page: Optional[Page] = None,
            screenshot_path: Optional[str] = None
    ) -> None:
        """Capture a full-page screenshot and save it to disk.

        Args:
            page: The Playwright Page to screenshot. Defaults to instance page.
            screenshot_path: Custom path for the screenshot. Auto-generated if None.
        """
        if page is None:
            page = self.page

        if screenshot_path:
            path = Path(screenshot_path)
        else:
            path = self.SCREENSHOTS_DIR / f'{get_time()}_marker.png'

        path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(path), full_page=True)
        logging.debug(f'Screenshot saved to {path}')
