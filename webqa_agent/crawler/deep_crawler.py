import asyncio
import datetime
import json
import time
import logging
import re
from pathlib import Path
from playwright.async_api import Page, async_playwright
from webqa_agent.crawler.dom_tree import DomTreeNode as dtree
from webqa_agent.crawler.dom_cacher import DomCacher
from typing import List, Dict, Optional, Any, Tuple, TypedDict, Union, Iterable
from pydantic import BaseModel, Field
from enum import Enum
from itertools import groupby


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_time() -> str:
    """Get the current time as a formatted string.
    
    Returns:
        Timestamp format: YYYYMMDD_HH_MM_SS
    """
    return datetime.datetime.now().strftime("%Y%m%d_%H_%M_%S")


def _normalize_keys(template: Optional[Iterable[Union[str, "ElementKey"]]]) -> Optional[List[str]]:
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
            normalized.append(key.value if hasattr(key, "value") else str(key))
        except Exception:
            normalized.append(str(key))
    return normalized


# ============================================================================
# ENUMS AND CONSTANTS
# ============================================================================

class ElementKey(Enum):
    """Enumeration for element attribute keys."""
    NODE = "node"
    TAG_NAME = "tagName"
    CLASS_NAME = "className"
    INNER_TEXT = "innerText"
    ATTRIBUTES = "attributes"
    VIEWPORT = "viewport"
    CENTER_X = "center_x"
    CENTER_Y = "center_y"
    IS_VISIBLE = "isVisible"
    IS_INTERACTIVE = "isInteractive"
    IS_VALID_TEXT = "isValidText"
    IS_TOP_ELEMENT = "isTopElement"
    IS_IN_VIEWPORT = "isInViewport"
    XPATH = "xpath"
    SELECTOR = "selector"
    STYLES = "styles"

    def __str__(self) -> str:
        """Return the string representation of the enum value."""
        return self.value


DEFAULT_OUTPUT_TEMPLATE = [
    ElementKey.TAG_NAME.value,
    ElementKey.INNER_TEXT.value,
    ElementKey.CENTER_X.value,
    ElementKey.CENTER_Y.value
]


# ============================================================================
# DATA MODELS
# ============================================================================

class ElementMap(BaseModel):
    """A wrapper for a dictionary of elements that provides a cleansing method."""
    data: Dict[str, Any] = Field(default_factory=dict)

    def clean(self, output_template: Optional[List[str]] = None) -> Dict[str, Any]:
        """Cleanses the element map, returning a new dictionary with filtered attributes.
    
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
            return k.value if hasattr(k, "value") else str(k)

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
    """Model for crawl results containing flattened and hierarchical element data."""
    element_tree: Dict[str, Any] = Field(default_factory=dict)
    flat_element_map: ElementMap = Field(default_factory=ElementMap)
    diff_element_map: ElementMap = Field(default_factory=ElementMap)

    def raw_dict(self) -> Dict[str, Any]:
        """Get raw flattened element data with all fields."""
        return self.flat_element_map.data

    def clean_dict(self, template: Optional[Iterable[Union[str, "ElementKey"]]] = None) -> Dict[str, Any]:
        """Get cleaned flattened element data with fields filtered by template."""
        return self.flat_element_map.clean(output_template=_normalize_keys(template))

    def diff_dict(self, template: Optional[Iterable[Union[str, "ElementKey"]]] = None) -> Dict[str, Any]:
        """Get DOM difference element data with specified template."""
        return self.diff_element_map.clean(output_template=_normalize_keys(template))

    def to_llm_json(self, template: Optional[Iterable[Union[str, "ElementKey"]]] = None) -> str:
        """Convert filtered elements to LLM-compatible JSON format."""
        return json.dumps(self.clean_dict(template=template), ensure_ascii=False, separators=(",", ":"))


# ============================================================================
# MAIN CRAWLER CLASS
# ============================================================================

class DeepCrawler:
    """A deep crawler for recursively extracting structured element data from web pages.

    This class injects JavaScript payloads into Playwright pages to build hierarchical
    DOM element trees, capturing properties such as visibility, interactivity, and
    positioning. It supports element highlighting for debugging and provides comprehensive
    DOM change detection capabilities.
    """

    # Class-level constants
    _default_dir = Path(__file__).parent
    DETECTOR_JS = _default_dir / "js" / "element_detector.js"
    REMOVER_JS = _default_dir / "js" / "marker_remover.js"
    RESULTS_DIR = _default_dir / "results"
    SCREENSHOTS_DIR = _default_dir / "screenshots"

    def __init__(self, page: Page, depth: int = 0):
        """Initialize the DeepCrawler instance.
    
        Args:
            page: The Playwright Page object to crawl.
            depth: The current crawling depth level.
            
        Raises:
            ValueError: If page is not a valid Playwright Page object.
        """
        if not isinstance(page, Page):
            raise ValueError("Crawler page must be a Playwright Page object")

        self.page = page
        self.depth = depth
        self.element_tree = None  # Hierarchical element tree structure
        self.dom_cacher = DomCacher()  # DOM change detection manager
        self._cached_element_tree = None  # Cached DOM tree for comparison
        self._last_crawl_time = None  # Timestamp of last crawl operation

    # ------------------------------------------------------------------------
    # CORE CRAWLING METHODS
    # ------------------------------------------------------------------------

    async def crawl(
            self,
            page: Optional[Page] = None,
            highlight: bool = False,
            highlight_text: bool = False,
            highlight_media: bool = False,
            viewport_only: bool = False,
            include_styles: bool = False,
            cache_dom: bool = False,
    ) -> CrawlResultModel:
        """Inject JavaScript to crawl the page and return structured element data.

        Args:
            page: The Playwright Page to crawl. Defaults to instance page.
            highlight: Whether to visually highlight detected elements.
            highlight_text: Whether to highlight text nodes.
            highlight_media: Whether to highlight media elements.
            viewport_only: Whether to restrict detection to current viewport.
            include_styles: Whether to include styles in the result.
            cache_dom: Whether to cache the DOM tree for change detection.

        Returns:
            CrawlResultModel containing the structured crawl data.
        """
        if page is None:
            page = self.page

        try:
            # Build JavaScript payload for element detection
            payload = (
                f"(() => {{"
                f"window._highlight = {str(highlight).lower()};"
                f"window._highlightText = {str(highlight_text).lower()};\n"
                f"window._highlightMedia = {str(highlight_media).lower()};\n"
                f"window._viewportOnly = {str(viewport_only).lower()};\n"
                f"window._includeStyles = {str(include_styles).lower()};\n"
                f"\n{self.read_js(self.DETECTOR_JS)}"
                f"\nreturn buildElementTree();"
                f"}})()"
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

                logging.debug(f"DOM change result: {diff_elements}")

                result.diff_element_map = ElementMap(data=self.extract_interactive_elements(get_new_elems=True))

            return result

        except Exception as e:
            logging.error(f"JavaScript injection failed during element detection: {e}")
            return CrawlResultModel()

    def extract_interactive_elements(self, get_new_elems: bool = False) -> Dict:
        """Extract interactive elements with comprehensive attribute information.

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
                if viewport.get("width") is None or viewport.get("height") is None:
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

    def get_text(self, fmt: str = "json") -> str:
        """
        Extract and concatenate all text content from the crawled DOM tree.
        
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
            return bool(getattr(n, "innerText", None) and n.innerText.strip())

        def _is_leaf_text_node(n) -> bool:
            """Determine if a node is a leaf text node (no children with text)."""
            children = getattr(n, "children", None) or []
            return not any(_has_text(c) for c in children)

        def _dedupe_consecutive(seq):
            """Remove consecutive duplicate items from sequence."""
            return [k for k, _ in groupby(seq)]

        # Early return if no element tree available
        if not self.element_tree:
            return ""

        # Build DOM tree from hierarchical data
        root = dtree.build_root(self.element_tree)
        if root is None:
            return ""

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
        return json.dumps(items, ensure_ascii=False, separators=(",", ":"))

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
        """
        Read and return the content of a JavaScript file.
        
        Args:
            file_path: Path to the JavaScript file.
            
        Returns:
            The content of the JavaScript file as a string.
        """
        with open(file_path, "r", encoding="utf-8") as file:
            return file.read()

    @staticmethod
    def dump_json(node: Dict[str, Any], path: Path) -> None:
        """
        Serialize a dictionary to a JSON file with proper formatting.
        
        Args:
            node: The dictionary to serialize.
            path: The output file path.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(node, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------------
    # VISUAL DEBUGGING METHODS
    # ------------------------------------------------------------------------

    async def remove_marker(self, page: Optional[Page] = None) -> None:
        """
        Remove visual highlight markers from the page.
        
        Args:
            page: The Playwright Page to clean. Defaults to instance page.
        """
        if page is None:
            page = self.page
        try:
            script = self.read_js(self.REMOVER_JS)
            await page.evaluate(script)
        except Exception as e:
            logging.error(f"Failed to remove highlight markers: {e}")

    async def take_screenshot(
            self,
            page: Optional[Page] = None,
            screenshot_path: Optional[str] = None
    ) -> None:
        """
        Capture a full-page screenshot and save it to disk.
        
        Args:
            page: The Playwright Page to screenshot. Defaults to instance page.
            screenshot_path: Custom path for the screenshot. Auto-generated if None.
        """
        if page is None:
            page = self.page

        if screenshot_path:
            path = Path(screenshot_path)
        else:
            path = self.SCREENSHOTS_DIR / f"{get_time()}_marker.png"

        path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(path), full_page=True)
        logging.debug(f"Screenshot saved to {path}")
