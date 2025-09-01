import logging
from typing import List
from urllib.parse import urljoin, urlparse

from playwright.async_api import Page

from webqa_agent.crawler.deep_crawler import DeepCrawler, ElementKey


class CrawlHandler:
    """Extract links and clickable elements from web pages."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.base_domain = urlparse(base_url).netloc

    async def extract_links(self, page: Page) -> List[str]:
        try:
            links = await page.eval_on_selector_all("a", "elements => elements.map(el => el.href)")
            script_links = await page.eval_on_selector_all("script[src]", "elements => elements.map(el => el.src)")
            link_tags = await page.eval_on_selector_all("link[href]", "elements => elements.map(el => el.href)")

            all_links = set(links + script_links + link_tags)

            filtered_links = [
                link
                for link in all_links
                if not (
                    link.endswith(".js")
                    or link.endswith(".css")
                    or link.endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg"))
                    or link.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"))
                    or link.startswith("#")
                    or link.startswith("mailto:")
                    or link.startswith("tel:")
                )
            ]

            absolute_links = [urljoin(self.base_url, link) for link in filtered_links]
            return absolute_links

        except Exception as e:
            logging.error(f"Error extracting links: {str(e)}")
            raise

    def _normalize_link(self, link: str) -> str:
        """Normalize a link URL."""
        if not link:
            return ""

        # Handle relative URLs
        if link.startswith("/"):
            return urljoin(self.base_url, link)
        elif link.startswith("#"):
            # Skip anchor links
            return ""
        elif link.startswith("javascript:") or link.startswith("mailto:") or link.startswith("tel:"):
            # Skip javascript, mailto and tel links
            return ""

        return link

    def _is_valid_link(self, link: str) -> bool:
        """Check if a link is valid for testing."""
        if not link:
            return False

        try:
            parsed = urlparse(link)

            # Must have a scheme (http/https)
            if parsed.scheme not in ["http", "https"]:
                return False

            # Skip file downloads
            if any(link.lower().endswith(ext) for ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar"]):
                return False

            # Only test links from the same domain (optional - can be configured)
            if parsed.netloc and parsed.netloc != self.base_domain:
                return False

            return True

        except Exception:
            return False

    async def clickable_elements_detection(self, page: Page):
        try:
            dp = DeepCrawler(page)
            result = await dp.crawl()
            clickable_elements = result.clean_dict([str(ElementKey.XPATH), str(ElementKey.SELECTOR)])
            return clickable_elements

        except Exception as e:
            logging.error(f"Error detecting clickable elements on {self.base_url}: {str(e)}")
            return []
