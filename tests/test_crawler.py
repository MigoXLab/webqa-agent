import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Add project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from playwright.async_api import async_playwright

from webqa_agent.crawler.crawl import CrawlHandler
from webqa_agent.crawler.deep_crawler import DeepCrawler

# pytest tests/test_crawler.py::TestCrawler::test_highlight_crawl -v -s --url https://google.com
# pytest tests/test_crawler.py -v -s --url https://google.com


class TestCrawler:
    """Test suite for web crawling functionality with different parameters."""

    # Default test URLs (can be overridden)
    DEFAULT_TEST_URLS = 'https://google.com'

    # Different crawl parameter combinations to test
    CRAWL_PARAMS = [
        {'name': 'highlight_crawl', 'highlight': True, 'filter_text': False, 'viewport_only': True},
        {'name': 'text_highlight_crawl', 'highlight': True, 'filter_text': True, 'viewport_only': True},
        {'name': 'viewport_highlight_crawl', 'highlight': True, 'filter_text': False, 'viewport_only': True},
    ]

    # Directories (class attributes; accessible via self)
    test_results_dir = Path(__file__).parent / 'crawler_test_results'
    screenshots_dir = test_results_dir / 'screenshots'
    id_maps_dir = test_results_dir / 'id_maps'
    crawl_data_dir = test_results_dir / 'crawl_data'
    clean_id_maps_dir = test_results_dir / 'clean_id_maps'

    async def setup_method(self):
        """Setup method called before each test."""
        # Ensure directories exist
        self.test_results_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.id_maps_dir.mkdir(parents=True, exist_ok=True)
        self.crawl_data_dir.mkdir(parents=True, exist_ok=True)
        self.clean_id_maps_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=False,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-gpu',
                '--force-device-scale-factor=1',
            ],
        )
        self.context = await self.browser.new_context(
            viewport={'width': 1280, 'height': 720},
        )
        self.page = await self.context.new_page()

        # Set default timeout
        self.page.set_default_navigation_timeout(30000)
        self.page.set_default_timeout(30000)

    async def teardown_method(self):
        """Teardown method called after each test."""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    def get_timestamp(self) -> str:
        """Get timestamp for file naming."""
        return datetime.now().strftime('%Y%m%d_%H%M%S')

    async def take_before_screenshot(self, url: str, param_name: str) -> str:
        """Take screenshot before crawling."""
        timestamp = self.get_timestamp()
        safe_url = url.replace('://', '_').replace('/', '_')
        screenshot_path = self.screenshots_dir / f'{param_name}_{safe_url}_before_{timestamp}.png'
        await self.page.screenshot(path=str(screenshot_path), full_page=True)
        return str(screenshot_path)

    async def take_after_screenshot(self, url: str, param_name: str) -> str:
        """Take screenshot after crawling (with possible highlights)"""
        timestamp = self.get_timestamp()
        screenshot_path = (
            self.screenshots_dir / f"{param_name}_{url.replace('://', '_').replace('/', '_')}_after_{timestamp}.png"
        )
        await self.page.screenshot(path=str(screenshot_path), full_page=True)
        return str(screenshot_path)

    def save_id_map(self, url: str, param_name: str, id_map: Dict[str, Any]) -> str:
        """Save ID map to JSON file."""
        timestamp = self.get_timestamp()
        id_map_path = (
            self.id_maps_dir / f"{param_name}_{url.replace('://', '_').replace('/', '_')}_id_map_{timestamp}.json"
        )

        with open(id_map_path, 'w', encoding='utf-8') as f:
            json.dump(id_map, f, ensure_ascii=False, indent=2)

        return str(id_map_path)

    def save_clean_id_map(self, url: str, param_name: str, clean_id_map: Dict[str, Any]) -> str:
        """Save clean ID map to JSON file."""
        timestamp = self.get_timestamp()
        clean_id_map_path = (
            self.clean_id_maps_dir / f"{param_name}_{url.replace('://', '_').replace('/', '_')}_clean_id_map_{timestamp}.json"
        )

        with open(clean_id_map_path, 'w', encoding='utf-8') as f:
            json.dump(clean_id_map, f, ensure_ascii=False, indent=2)

        return str(clean_id_map_path)

    def save_crawl_data(self, url: str, param_name: str, crawl_data: Dict[str, Any]) -> str:
        """Save crawl data to JSON file."""
        timestamp = self.get_timestamp()
        crawl_data_path = (
            self.crawl_data_dir
            / f"{param_name}_{url.replace('://', '_').replace('/', '_')}_crawl_data_{timestamp}.json"
        )

        with open(crawl_data_path, 'w', encoding='utf-8') as f:
            json.dump(crawl_data, f, ensure_ascii=False, indent=2)

        return str(crawl_data_path)

    def save_test_summary(self, test_results: List[Dict[str, Any]]) -> str:
        """Save test summary to JSON file."""
        timestamp = self.get_timestamp()
        summary_path = self.test_results_dir / f'test_summary_{timestamp}.json'

        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(test_results, f, ensure_ascii=False, indent=2)

        return str(summary_path)

    async def crawl_single_url(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Crawl a single URL with specified parameters using the current
        page/context."""
        await self.page.goto(url, wait_until='networkidle')

        # Take before screenshot
        before_screenshot = await self.take_before_screenshot(url, params['name'])

        # Initialize crawler and perform crawling
        crawler = DeepCrawler(self.page)
        crawl_result = await crawler.crawl(
            page=self.page,
            highlight=params['highlight'],
            filter_text=params['filter_text'],
            viewport_only=params['viewport_only'],
        )
        crawl_data = crawl_result.element_tree
        id_map = crawl_result.raw_dict()
        clean_id_map = crawl_result.clean_dict()

        # Take after screenshot
        after_screenshot = await self.take_after_screenshot(url, params['name'])

        # Save results
        id_map_path = self.save_id_map(url, params['name'], id_map)
        clean_id_map_path = self.save_clean_id_map(url, params['name'], clean_id_map)
        crawl_data_path = self.save_crawl_data(url, params['name'], crawl_data)

        # Remove markers if highlights were added
        if params['highlight']:
            await crawler.remove_marker(self.page)

        return {
            'url': url,
            'parameters': params,
            'results': {
                'before_screenshot': before_screenshot,
                'after_screenshot': after_screenshot,
                'id_map_path': id_map_path,
                'clean_id_map_path': clean_id_map_path,
                'crawl_data_path': crawl_data_path,
                'success': True,
            },
        }

    @pytest.mark.asyncio
    async def test_crawl_link(self, request):
        """Test integration with CrawlHandler for link extraction."""
        await self.setup_method()

        try:
            # Resolve URL from CLI/env or default
            test_url = request.config.getoption('--url') or self.DEFAULT_TEST_URLS

            # Navigate to the test URL
            await self.page.goto(test_url, wait_until='networkidle')

            # Take before screenshot
            before_screenshot = await self.take_before_screenshot(test_url, 'crawl_handler')

            # Initialize crawl handler
            crawl_handler = CrawlHandler(test_url)

            # Extract links
            links = await crawl_handler.extract_links(self.page)
            print(f'🔗 Found {len(links)} links')

            # Get clickable elements using crawl handler
            clickable_elements = await crawl_handler.clickable_elements_detection(self.page)
            print(f'🖱️ Found {len(clickable_elements)} clickable elements')

            # Take after screenshot
            after_screenshot = await self.take_after_screenshot(test_url, 'crawl_handler')

            # Save results
            results = {
                'url': test_url,
                'links': links,
                'clickable_elements': clickable_elements,
                'links_count': len(links),
                'clickable_elements_count': len(clickable_elements),
            }

            results_path = self.save_crawl_data(test_url, 'crawl_handler', results)

            # Assertions
            assert isinstance(links, list)
            assert isinstance(clickable_elements, list)
            assert os.path.exists(before_screenshot)
            assert os.path.exists(after_screenshot)
            assert os.path.exists(results_path)

            print('CrawlHandler integration test passed')

        finally:
            await self.teardown_method()

    @pytest.mark.asyncio
    async def test_highlight_crawl(self, request):
        """Test highlighted crawl parameters."""
        await self.setup_method()

        try:
            test_url = request.config.getoption('--url') or self.DEFAULT_TEST_URLS

            params = self.CRAWL_PARAMS[0]  # highlight_crawl
            result = await self.crawl_single_url(test_url, params)

            assert result['results']['success']
            assert os.path.exists(result['results']['before_screenshot'])
            assert os.path.exists(result['results']['after_screenshot'])
            assert os.path.exists(result['results']['id_map_path'])
            assert os.path.exists(result['results']['crawl_data_path'])
        finally:
            await self.teardown_method()

    @pytest.mark.asyncio
    async def test_text_highlight_crawl(self, request):
        """Test full highlight crawl parameters."""
        await self.setup_method()

        try:
            test_url = request.config.getoption('--url') or self.DEFAULT_TEST_URLS

            params = self.CRAWL_PARAMS[1]  # text_highlight_crawl
            result = await self.crawl_single_url(test_url, params)

            assert result['results']['success']
            assert os.path.exists(result['results']['before_screenshot'])
            assert os.path.exists(result['results']['after_screenshot'])
            assert os.path.exists(result['results']['id_map_path'])
            assert os.path.exists(result['results']['crawl_data_path'])

        finally:
            await self.teardown_method()

    @pytest.mark.asyncio
    async def test_viewport_highlight_crawl(self, request):
        """Test viewport highlight crawl parameters."""
        await self.setup_method()

        try:
            test_url = request.config.getoption('--url') or self.DEFAULT_TEST_URLS

            params = self.CRAWL_PARAMS[2]  # viewport_highlight_crawl
            result = await self.crawl_single_url(test_url, params)

            assert result['results']['success']
            assert os.path.exists(result['results']['before_screenshot'])
            assert os.path.exists(result['results']['after_screenshot'])
            assert os.path.exists(result['results']['id_map_path'])
            assert os.path.exists(result['results']['crawl_data_path'])

        finally:
            await self.teardown_method()
