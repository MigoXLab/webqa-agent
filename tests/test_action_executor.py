import sys
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import json
import os
import pathlib
from datetime import datetime

import pytest
from playwright.async_api import async_playwright

from webqa_agent.actions.action_executor import ActionExecutor
from webqa_agent.actions.action_handler import ActionHandler

# pytest tests/test_action_executor.py::TestActionExecutor::test_click_action -v -s
# pytest tests/test_action_executor.py::TestActionExecutor -v -s


# Local test pages directory and placeholder map for extensibility
LOCAL_PAGES_DIR = pathlib.Path(__file__).parent / 'test_pages'
PLACEHOLDER_LOCAL_PAGES = {
    '__LOCAL_DROPDOWN_PAGE__': 'dropdown_components.html',
}

MOCKS_PATH = pathlib.Path(__file__).parent / 'mocks' / 'action_mocks.json'
MOCKS_PATH_NEGATIVE = pathlib.Path(__file__).parent / 'mocks' / 'actions_negative_mocks.json'


class TestActionExecutor:
    # Results directories for action tests
    results_dir = pathlib.Path(__file__).parent / 'actions_test_results'
    screenshots_dir = results_dir / 'screenshots'

    # Global navigation settings
    GOTO_WAIT_UNTIL = 'networkidle'
    GOTO_TIMEOUT_MS = 30000

    async def setup_method(self):
        """Setup method called before each test."""
        # Ensure directories exist
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=False)
        self.context = await self.browser.new_context(
            viewport={'width': 1280, 'height': 720},
        )
        self.page = await self.context.new_page()

        # Initialize action handler and executor
        self.action_handler = ActionHandler()
        await self.action_handler.initialize(self.page)
        self.action_executor = ActionExecutor(self.action_handler)
        await self.action_executor.initialize()

    async def teardown_method(self):
        """Teardown method called after each test."""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    def resolve_url(self, url: str) -> str:
        if url in PLACEHOLDER_LOCAL_PAGES:
            target = LOCAL_PAGES_DIR / PLACEHOLDER_LOCAL_PAGES[url]
            return target.resolve().as_uri()

        generic_prefix = '__LOCAL_PAGE__:'
        if url.startswith(generic_prefix):
            rel = url[len(generic_prefix) :].strip()
            rel_path = pathlib.Path(rel)
            if rel_path.is_absolute() or '..' in rel_path.parts:
                raise ValueError(f'Invalid local page path: {rel}')
            target = LOCAL_PAGES_DIR / rel_path
            return target.resolve().as_uri()

        return url

    async def navigate(self, url: str) -> None:
        """Navigate to a resolved URL using global navigation settings."""
        await self.page.goto(
            self.resolve_url(url),
            wait_until=self.GOTO_WAIT_UNTIL,
            timeout=self.GOTO_TIMEOUT_MS,
        )

    def get_timestamp(self) -> str:
        return datetime.now().strftime('%Y%m%d_%H%M%S')

    async def take_before_screenshot(self, url: str, param_name: str) -> str:
        """Take screenshot before action."""
        timestamp = self.get_timestamp()
        safe_url = url.replace('://', '_').replace('/', '_')
        screenshot_path = self.screenshots_dir / f'{param_name}_{safe_url}_before_{timestamp}.png'
        await self.page.screenshot(path=str(screenshot_path), full_page=False)
        return str(screenshot_path)

    async def take_after_screenshot(self, url: str, param_name: str) -> str:
        """Take screenshot after action."""
        timestamp = self.get_timestamp()
        safe_url = url.replace('://', '_').replace('/', '_')
        screenshot_path = self.screenshots_dir / f'{param_name}_{safe_url}_after_{timestamp}.png'
        await self.page.screenshot(path=str(screenshot_path), full_page=False)
        return str(screenshot_path)

    @pytest.mark.asyncio
    async def test_click_action(self):
        """Test click action."""
        await self.setup_method()
        try:
            # Load mocks and iterate
            with open(MOCKS_PATH, 'r', encoding='utf-8') as f:
                mocks = json.load(f)
            tap_cases = mocks.get('Tap', [])
            assert len(tap_cases) > 0
            for i, case in enumerate(tap_cases):
                await self.navigate(case['url'])
                self.action_handler.set_page_element_buffer(case['id_map'])
                before_path = await self.take_before_screenshot(case['url'], 'click')

                # Execute click action
                for action in case['actions']:
                    result = await self.action_executor.execute(action)
                    await asyncio.sleep(2)
                    elementid = action['locate']['id']
                    after_path = await self.take_after_screenshot(case['url'], f'click_{elementid}')

                # Verify results
                assert result['success'] is True
                assert os.path.exists(before_path)
                assert os.path.exists(after_path)

        finally:
            await self.teardown_method()

    @pytest.mark.asyncio
    async def test_hover_action(self):
        """Test hover action."""
        await self.setup_method()
        try:
            with open(MOCKS_PATH, 'r', encoding='utf-8') as f:
                mocks = json.load(f)
            hover_cases = mocks.get('Hover', [])
            assert len(hover_cases) > 0
            for i, case in enumerate(hover_cases):
                await self.navigate(case['url'])
                self.action_handler.set_page_element_buffer(case['id_map'])
                before_path = await self.take_before_screenshot(case['url'], 'hover')

                for action in case['actions']:
                    result = await self.action_executor.execute(action)
                    await asyncio.sleep(2)
                    elementid = action['locate']['id']
                    after_path = await self.take_after_screenshot(case['url'], f'hover_{elementid}')

                # Verify results
                assert result['success'] is True
                assert os.path.exists(before_path)
                assert os.path.exists(after_path)

        finally:
            await self.teardown_method()

    @pytest.mark.asyncio
    async def test_input_action(self):
        """Test input action."""
        await self.setup_method()
        try:
            with open(MOCKS_PATH, 'r', encoding='utf-8') as f:
                mocks = json.load(f)
            input_cases = mocks.get('Input', [])
            assert len(input_cases) > 0
            for i, case in enumerate(input_cases):
                await self.navigate(case['url'])
                self.action_handler.set_page_element_buffer(case['id_map'])
                before_path = await self.take_before_screenshot(case['url'], 'input')

                for action in case['actions']:
                    result = await self.action_executor.execute(action)
                    await asyncio.sleep(2)
                    elementid = action['locate']['id']
                    after_path = await self.take_after_screenshot(case['url'], f'input_{elementid}')

                # Verify results
                assert result['success'] is True
                assert os.path.exists(before_path)
                assert os.path.exists(after_path)

        finally:
            await self.teardown_method()

    @pytest.mark.asyncio
    async def test_scroll_action(self):
        """Test scroll action."""
        await self.setup_method()
        try:
            with open(MOCKS_PATH, 'r', encoding='utf-8') as f:
                mocks = json.load(f)
            scroll_cases = mocks.get('Scroll', [])
            assert len(scroll_cases) > 0
            for i, case in enumerate(scroll_cases):
                await self.navigate(case['url'])
                self.action_handler.set_page_element_buffer(case['id_map'])
                before_path = await self.take_before_screenshot(case['url'], f'scroll_{i}')

                for j, action in enumerate(case['actions']):
                    result = await self.action_executor.execute(action)
                    await asyncio.sleep(2)
                    after_path = await self.take_after_screenshot(case['url'], f'scroll_{i}_{j}')

                assert result['success'] is True
                assert os.path.exists(before_path)
                assert os.path.exists(after_path)

        finally:
            await self.teardown_method()

    @pytest.mark.asyncio
    async def test_select_dropdown_action(self):
        """Test select dropdown action."""
        await self.setup_method()
        try:
            with open(MOCKS_PATH, 'r', encoding='utf-8') as f:
                mocks = json.load(f)
            select_dropdown_cases = mocks.get('SelectDropdown', [])
            assert len(select_dropdown_cases) > 0
            for i, case in enumerate(select_dropdown_cases):
                await self.navigate(case['url'])
                self.action_handler.set_page_element_buffer(case['id_map'])
                before_path = await self.take_before_screenshot(case['url'], f'select_dropdown_{i}')

                for j, action in enumerate(case['actions']):
                    result = await self.action_executor.execute(action)
                    print(f"[SelectDropdown][{case.get('name','case')}]: {result.get('message','')}\n")
                    await asyncio.sleep(5)
                    after_path = await self.take_after_screenshot(case['url'], f'select_dropdown_{j}')

                assert result['success'] is True
                assert os.path.exists(before_path)
                assert os.path.exists(after_path)

        finally:
            await self.teardown_method()

    @pytest.mark.asyncio
    async def test_select_dropdown_action_negative(self):
        """Negative tests for select dropdown action: expect success == False and print message"""
        await self.setup_method()
        try:
            with open(MOCKS_PATH_NEGATIVE, 'r', encoding='utf-8') as f:
                mocks = json.load(f)
            neg_cases = mocks.get('SelectDropdown_Negative', [])
            assert len(neg_cases) > 0

            for i, case in enumerate(neg_cases):
                # about:blank is fine without networkidle wait
                await self.navigate(case['url'])
                self.action_handler.set_page_element_buffer(case.get('id_map', {}))

                for action in case['actions']:
                    result = await self.action_executor.execute(action)
                    print(f"[SelectDropdown_Negative][{case.get('name','case')}]: {result.get('message','')}\n")
                    assert result.get('success') is False

        finally:
            await self.teardown_method()

    @pytest.mark.asyncio
    async def test_scroll_action_negative(self):
        """Negative tests for scroll action: expect success == False and print message"""
        await self.setup_method()
        try:
            with open(MOCKS_PATH_NEGATIVE, 'r', encoding='utf-8') as f:
                mocks = json.load(f)
            scroll_neg_cases = mocks.get('Scroll_Negative', [])
            assert len(scroll_neg_cases) > 0

            for i, case in enumerate(scroll_neg_cases):
                await self.page.goto(self.resolve_url(case['url']), wait_until='networkidle', timeout=30000)
                self.action_handler.set_page_element_buffer(case['id_map'])
                before_path = await self.take_before_screenshot(case['url'], f'scroll_{i}')

                for j, action in enumerate(case['actions']):
                    result = await self.action_executor.execute(action)
                    print(f"[Scroll_Negative][{case.get('name','case')}]: {result.get('message','')}\n")
                    await asyncio.sleep(2)
                    after_path = await self.take_after_screenshot(case['url'], f'scroll_{i}_{j}')

                assert result['success'] is False
                assert os.path.exists(before_path)
                assert os.path.exists(after_path)

        finally:
            await self.teardown_method()
