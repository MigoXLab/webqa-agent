import argparse
import asyncio
import time
import datetime
import json

from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Any, Tuple

from playwright.async_api import Page, async_playwright
from webqa_agent.crawler.dom_tree import DomTreeNode as dtree
from typing import List, Dict, Optional, Any, Callable


def get_time() -> str:
    """
    Get the current time as a formatted string.
    Timestamp format: YYYYMMDD_HH_MM_SS
    """
    return datetime.datetime.now().strftime("%Y%m%d_%H_%M_%S")


class DeepCrawler:
    """
    A deep crawler for recursively extracting structured element data from a web page.

    This class injects a JavaScript payload (`element_detector.js`) into a Playwright
    page to build a hierarchical tree of DOM elements, capturing properties like
    visibility, interactivity, and position. It can also highlight elements on the
    page for debugging purposes.

    Key functionalities include:
    - Crawling a page to get a nested dictionary representing the DOM.
    - Identifying clickable elements and extracting text content.
    - Taking screenshots and saving crawl results to JSON files.
    - Removing visual markers added during highlighting.
    """
    default_dir = Path(__file__).parent
    # File paths
    DETECTOR_JS = default_dir / "js" / "element_detector.js"
    REMOVER_JS = default_dir / "js" / "marker_remover.js"

    # Directory paths
    RESULTS_DIR = default_dir / "results"
    SCREENSHOTS_DIR = default_dir / "screenshots"

    # Parameters
    MAX_DEPTH = 2

    # Configuration for filtering elements to be considered clickable.
    # An element is kept if it satisfies all conditions in `KeepNodeType`.
    # `href` is currently not used but reserved for future filtering logic.
    CRAWL_CONFIG = {
        "KeepNodeType": ["isVisible", "isInteractive", "isTopElement"],
    }

    def __init__(self, page: Page, depth: int = 0):
        """
        Initialize the DeepCrawler.

        Args:
            page: The Playwright Page object to crawl.
            depth: The current crawling depth.
        """
        if not isinstance(page, Page):
            raise ValueError("Crawler page MUST BE a Playwright Page object")
        self.page = page
        self.depth = depth
        self.crawled_result = None

    @staticmethod
    def read_js(file_path: Path) -> str:
        """Reads and returns the content of a JavaScript file."""
        with open(file_path, "r", encoding="utf-8") as file:
            return file.read()

    async def crawl(
            self,
            page: Optional[Page] = None,
            highlight: bool = False,
            highlight_text: bool = False,
            viewport_only: bool = False
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Injects JavaScript to crawl the page and returns a structured element tree.

        This method executes the `element_detector.js` script in the browser context,
        which builds and returns a hierarchical representation of the DOM. It can also
        pass parameters to control highlighting and viewport-only processing.

        Args:
            page: The Playwright Page to crawl. If None, uses the instance's page.
            highlight: If True, visually highlights detected elements on the page.
            highlight_text: If True, highlights text nodes. Requires `highlight` to be True.
            viewport_only: If True, restricts element detection to the current viewport.

        Returns:
            A tuple containing:
            - A dictionary representing the root of the crawled element tree.
            - A dictionary mapping highlight IDs to element information.
        """
        if page is None:
            page = self.page

        try:
            payload = (
                f"(() => {{"
                f"window._highlight = {str(highlight).lower()};"
                f"window._highlightText = {str(highlight_text).lower()};\n"
                f"window._viewportOnly = {str(viewport_only).lower()};\n"
                f"\n{self.read_js(self.DETECTOR_JS)}"
                f"\nreturn buildElementTree();"
                f"}})()"
            )
            self.crawled_result, highlight_id_map = await page.evaluate(payload)
            return self.crawled_result, highlight_id_map

        except Exception as e:
            print(f"Error during JavaScript(DeepCrawler.DETECTOR_JS) injection or evaluation: {e}")
            return {}, {}

    async def remove_marker(self, page: Optional[Page] = None) -> None:
        """Removes the highlight markers from the page."""
        if page is None:
            page = self.page
        try:
            script = self.read_js(self.REMOVER_JS)
            await page.evaluate(script)

        except Exception as e:
            print(f"Error while removing markers: {e}")

    @staticmethod
    def dump_json(node: Dict[str, Any], path: Path) -> None:
        """Saves a dictionary to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(node, f, ensure_ascii=False, indent=2)

    async def take_screenshot(
            self,
            page: Optional[Page] = None,
            screenshot_path: Optional[str] = None
    ) -> None:
        """Takes a screenshot of the page and saves it to a file."""
        if page is None:
            page = self.page

        if screenshot_path:
            path = Path(screenshot_path)
        else:
            path = self.SCREENSHOTS_DIR / f"{get_time()}_marker.png"

        path.parent.mkdir(parents=True, exist_ok=True)

        await page.screenshot(path=str(path), full_page=True)
        print(f"Saved screenshot to {path}")

    def get_clickable_elements(self) -> List[Dict[str, Any]]:
        """
        Filters and returns a list of clickable elements from the crawled data.

        This method traverses the DOM tree built from the crawled result and identifies
        elements that meet the criteria defined in `CRAWL_CONFIG`. It extracts key
        information such as element ID, tag, position, and selectors.

        Returns:
            A list of dictionaries, where each dictionary represents a clickable element.
        """
        if not self.crawled_result:
            return []

        _root = dtree.build_root(self.crawled_result)

        coords = []
        if _root:
            for n in _root.pre_iter():
                if not all(getattr(n, attr) for attr in DeepCrawler.CRAWL_CONFIG["KeepNodeType"]):
                    continue

                if n.center_x is not None and n.center_y is not None:
                    vp = n.viewport or {}
                    w = vp.get("width")
                    h = vp.get("height")
                    if w is not None and h is not None:
                        coords.append({
                            "id": n.id,
                            "tag": n.tag,
                            "center_x": n.center_x,
                            "center_y": n.center_y,
                            "width": w,
                            "height": h,
                            "selector": n.selector,
                            "xpath": n.xpath,
                            "text": n.inner_text[:200]
                        })
        return coords

    def get_text(self) -> str:
        """
        Extracts and concatenates the inner text of all nodes in the crawled DOM tree.

        Returns:
            A single string containing all the text from the page, with nodes separated by newlines.
        """
        if not self.crawled_result:
            return ""

        root = dtree.build_root(self.crawled_result)
        if root is None:
            return ""

        texts = (
            node.inner_text.strip()
            for node in root.pre_iter()
            if node.inner_text and node.inner_text.strip()
        )

        return "\n".join(texts)


async def main(url: str):
    """
    An example function to demonstrate the usage of the DeepCrawler.

    This function initializes a Playwright browser, navigates to a URL, and uses
    the DeepCrawler to extract element data. It then prints the extracted text
    and saves the raw data to a JSON file.

    Args:
        url: The URL to crawl.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_navigation_timeout(60000)
        await page.goto(url, wait_until="networkidle")

        dp = DeepCrawler(page)
        rawdata, highlight_id_map = await dp.crawl(page,
                                                   highlight=True,
                                                   highlight_text=False,
                                                   viewport_only=False)

        txt_info = dp.get_text()
        # print(txt_info)

        clickable_elements = dp.get_clickable_elements()
        # print(clickable_elements)

        # dp.dump_json(rawdata, dp.RESULTS_DIR / "dump_raw.json")

        await asyncio.Event().wait()


if __name__ == '__main__':
    url = f"https://www.google.com"
    asyncio.run(main(url))
