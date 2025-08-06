import asyncio
import datetime
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from playwright.async_api import Page, async_playwright

from webqa_agent.crawler.dom_tree import DomTreeNode as dtree


def get_time() -> str:
    """
    Time stamp: YYYYMMDD_HHMMSS
    """
    return datetime.datetime.fromtimestamp(time.time()).strftime("%Y%m%d_%H_%M_%S")


class DeepCrawler:
    """Crawl page elements."""

    default_dir = Path(__file__).parent
    # File paths
    DETECTOR_JS = default_dir / "js" / "element_detector.js"
    REMOVER_JS = default_dir / "js" / "marker_remover.js"

    # Directory paths
    RESULTS_DIR = default_dir / "results"
    SCREENSHOTS_DIR = default_dir / "screenshots"

    # Parameters
    MAX_DEPTH = 2

    CRAWL_CONFIG = {"KeepNodeType": ["isVisible", "isInteractive", "isTopElement"], "href": "https"}

    def __init__(self, page: Page, depth: int = 0):
        self.page = page if isinstance(page, Page) else False
        if not self.page:
            raise ValueError("FormatError: Crawler page MUST BE Playwright Page")

        self.depth = depth
        self.crawled_result = None

    @staticmethod
    def read_js(file_dir):
        """Read JavaScript file content."""
        with open(file_dir, "r", encoding="utf-8") as file:
            return file.read()

    @staticmethod
    def load_js(file_dir):
        with open(file_dir, "r", encoding="utf-8") as file:
            return json.load(file)

    async def crawl(
        self, page=None, highlight=False, highlight_text=False, viewport_only=False, dump_json=False
    ) -> Dict[str, Any]:
        """Crawl current page elements and return nested dictionary with
        hierarchical structure."""
        if not page:
            page = self.page

        try:
            payload = (
                f"window._highlight = {str(highlight).lower()};"
                f"window._highlightText = {str(highlight_text).lower()};\n"
                f"window._viewportOnly = {str(viewport_only).lower()};\n"
                f"\n{self.read_js(self.DETECTOR_JS)}"
            )
            await page.evaluate(payload)
            self.crawled_result, highlight_id_map = await page.evaluate("buildElementTree()")
            return self.crawled_result, highlight_id_map

        except Exception as e:
            print(f"Inject JS Exception: {e}")

    async def deep_crawl(self, page=None, is_clean_mode=True, highlight=True, timeout=60000):
        """Deep crawl page elements within max depth 2, add subtree to original
        dom tree."""
        if not page:
            page = self.page
        ctx = page.context
        seen = set()  # Only crawl same link once
        sub_link = defaultdict(list)  # {url: [id_list]} for storing links and their IDs
        temp_nodes = await self.crawl(page, highlight=highlight)  # Temporary nodes

        async def _traverse(node: Dict[str, Any]):
            """Add subtree node to dom tree."""
            node_info = node.get("node")
            if node_info:
                if all(node_info.get(n) for n in self.CRAWL_CONFIG["KeepNodeType"]):
                    for attr in node_info.get("attributes", []):
                        attr_val = attr.get("value")
                        if attr["name"].lower() == "href" and attr_val.startswith(self.CRAWL_CONFIG["href"]):
                            sub_link[attr_val].append(node_info["id"])

                            if attr_val not in seen:
                                seen.add(attr_val)
                                p = await ctx.new_page()
                                await p.goto(attr_val, timeout=timeout, wait_until="domcontentloaded")

                                subtree_nodes = await self.crawl(p, highlight=highlight)

                                if is_clean_mode:
                                    await p.close()

                                node["subtree"] = subtree_nodes

                            else:  # Record repeated link
                                node["subtree"] = attr_val

            for child in node.get("children", []):
                await _traverse(child)

        try:
            await _traverse(temp_nodes)
            return temp_nodes, sub_link
        except Exception as e:
            print(f"DeepCrawlFailure: {e}")

    async def remove_marker(self, page=None):
        if not page:
            page = self.page

        try:
            script = self.read_js(str(self.REMOVER_JS))
            await page.evaluate(script)

        except Exception as e:
            print(e)

    @staticmethod
    def dump_json(node: Dict[str, Any], path: Path) -> None:
        """Save tree dictionary to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(node, f, ensure_ascii=False, indent=2)

    async def take_screenshot(self, page=None, screenshot_path=None):
        if not screenshot_path:
            path = self.SCREENSHOTS_DIR / f"{get_time()}_marker.png"
        else:
            path = Path(screenshot_path)

        path.parent.mkdir(parents=True, exist_ok=True)

        await page.screenshot(path=str(path), full_page=True)
        print(f"Saved screenshot --> {path}")

    def get_clickable_elements(self) -> List[Any]:
        _root = None
        if self.crawled_result:
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
                        coords.append(
                            {
                                "id": n.id,
                                "tag": n.tag,
                                "center_x": n.center_x,
                                "center_y": n.center_y,
                                "width": w,
                                "height": h,
                                "selector": n.selector,
                                "xpath": n.xpath,
                                "text": n.inner_text[:200],
                            }
                        )
        return coords

    def get_text(self):
        _root = None
        if self.crawled_result:
            _root = dtree.build_root(self.crawled_result)

        if _root:
            text = []
            for n in _root.pre_iter():
                text.append(n.inner_text)

            return "\n".join(text)

        return ""

    @staticmethod
    def is_clickable(node: dtree) -> bool:
        """
        Only keep elements that satisfy both conditions:
          1. isInteractive == True
          2. center_x, center_y, viewport.width, viewport.height are all not None
        """
        if not node.isInteractive:
            return False

        # Check center coordinates
        if node.center_x is None or node.center_y is None:
            return False

        vp = node.viewport or {}
        w = vp.get("width")
        h = vp.get("height")
        if w is None or h is None:
            return False

        return True


async def python_main(url, depth=0):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_navigation_timeout(60000)
        await page.goto(url, wait_until="networkidle")

        dp = DeepCrawler(page)
        # ts = time.time()
        # rawdata = await dp.crawl(page, enable_highlight=True)  # dict(dict)
        rawdata, highlight_id_map = await dp.crawl(
            page, highlight=False, highlight_text=True, viewport_only=False
        )  # dict(dict)

        txt_info = dp.get_text()
        print(txt_info)

        # print(highlight_id_map)
        # highlight_id_map_json_str = json.dumps(highlight_id_map, separators=(',', ':'), ensure_ascii=False)
        # print(highlight_id_map_json_str)
        # rt = dtree.build_root(rawdata)
        # pruned_elems = dtree.cutting(rt)['children']

        # print(pruned_elems)
        # print(type(pruned_elems))
        # json_str = json.dumps(rawdata, separators=(',', ':'), ensure_ascii=False)
        # print(json_str)

        # rawdata, href = await dp.deep_crawl(page, enable_highlight=True, is_clean_mode=False)  # dict(dict)
        # print(rawdata, href)
        dp.dump_json(rawdata, dp.RESULTS_DIR / "dump_raw_test_2.json")
        # r = dp.get_clickable_elements()
        # print(r)

        # elapsed = time.time() - ts
        # print(f"total time: {elapsed:.2f}s")
        await asyncio.Event().wait()


if __name__ == "__main__":
    url = "https://www.google.com"

    asyncio.run(python_main(url))
    # asyncio.run(ts_debug(url))
    # main()
