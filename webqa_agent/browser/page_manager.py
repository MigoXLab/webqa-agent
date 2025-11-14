"""
Page Manager for Multi-Tab/Multi-Page Scenarios

This module provides stack-based page management to support complex multi-tab workflows
where the browser automation needs to:
1. Open new tabs (e.g., clicking external links)
2. Perform actions/verifications on the new tab
3. Return to the parent tab to continue the test flow

The PageManager uses a LIFO stack approach that matches user expectations:
- GetNewPage → Push new page to stack (switch to child tab)
- SwitchBackTab → Pop from stack (return to parent tab)

This is different from browser history navigation (GoBack), which navigates within
a single tab's history.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from playwright.async_api import BrowserContext, Page


@dataclass
class PageInfo:
    """Metadata for a managed page/tab.

    Attributes:
        page: Playwright Page instance
        page_id: Unique identifier for this page (UUID)
        parent_id: ID of the page that opened this page (for hierarchy tracking)
        url: Current URL of the page
        title: Page title
        opened_at: Timestamp when page was registered
        page_type: Type classification ('main', 'new_tab', 'popup', 'iframe')
        is_closed: Whether the page has been closed
    """
    page: Page
    page_id: str
    parent_id: Optional[str]
    url: str
    title: str
    opened_at: datetime
    page_type: str = 'new_tab'  # 'main', 'new_tab', 'popup', 'iframe'
    is_closed: bool = False

    def to_dict(self) -> Dict:
        """Convert PageInfo to dictionary for serialization."""
        return {
            'page_id': self.page_id,
            'parent_id': self.parent_id,
            'url': self.url,
            'title': self.title,
            'opened_at': self.opened_at.isoformat(),
            'page_type': self.page_type,
            'is_closed': self.is_closed
        }


class PageManager:
    """Stack-based page/tab manager for browser automation.

    This class manages multiple browser pages/tabs with parent-child relationships,
    enabling workflows like:
    - Open external link in new tab
    - Verify content on new tab
    - Return to parent tab
    - Continue testing on parent tab

    Uses a LIFO stack approach:
    - push_page(): Switch to new page (adds to stack)
    - pop_page(): Return to previous page (removes from stack)

    Also maintains a registry of all pages for:
    - Hierarchy tracking (parent-child relationships)
    - Page lookup by ID
    - Cleanup of closed pages
    """

    def __init__(self, context: BrowserContext, max_pages: int = 20):
        """Initialize the PageManager.

        Args:
            context: Playwright BrowserContext to manage pages from
            max_pages: Maximum number of pages to track (prevents memory leaks)
        """
        self._context = context
        self._max_pages = max_pages

        # LIFO stack for page navigation (most recent page on top)
        self._page_stack: List[PageInfo] = []

        # Registry of all managed pages by ID
        self._page_registry: Dict[str, PageInfo] = {}

        # Current active page ID
        self._current_page_id: Optional[str] = None

        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

        # Setup page close event listener
        self._setup_page_listeners()

        logging.debug("PageManager initialized")

    def _setup_page_listeners(self):
        """Setup event listeners for page lifecycle events."""
        try:
            # Listen for page close events
            self._context.on("page", self._on_page_created)
            logging.debug("Page event listeners registered")
        except Exception as e:
            logging.warning(f"Failed to setup page listeners: {e}")

    def _on_page_created(self, page: Page):
        """Handle page creation event.

        Note: This is automatically triggered by Playwright when a new page is created.
        We primarily rely on explicit register_page() calls, but this provides
        a safety net for pages opened by JavaScript or user actions.
        """
        try:
            # Setup close listener for this specific page
            page.on("close", lambda: self._on_page_closed(page))
            logging.debug(f"Close listener attached to page: {page.url}")
        except Exception as e:
            logging.warning(f"Failed to attach close listener: {e}")

    def _on_page_closed(self, page: Page):
        """Handle page close event.

        Args:
            page: The page that was closed
        """
        try:
            # Find and mark the page as closed in registry
            for page_id, page_info in self._page_registry.items():
                if page_info.page == page:
                    page_info.is_closed = True
                    logging.info(f"Page closed: {page_id} ({page_info.url})")

                    # Remove from stack if present
                    self._page_stack = [p for p in self._page_stack if p.page_id != page_id]

                    # If this was the current page, switch to top of stack
                    if self._current_page_id == page_id and self._page_stack:
                        self._current_page_id = self._page_stack[-1].page_id
                        logging.debug(f"Current page changed to: {self._current_page_id}")

                    break
        except Exception as e:
            logging.error(f"Error handling page close event: {e}")

    async def register_page(
        self,
        page: Page,
        parent_id: Optional[str] = None,
        page_type: str = 'new_tab'
    ) -> PageInfo:
        """Register a new page in the manager.

        Args:
            page: Playwright Page instance to register
            parent_id: ID of the parent page (if this is a child page)
            page_type: Type of page ('main', 'new_tab', 'popup')

        Returns:
            PageInfo object for the registered page

        Raises:
            RuntimeError: If max_pages limit is reached
        """
        async with self._lock:
            # Check page limit
            if len(self._page_registry) >= self._max_pages:
                logging.warning(f"Max pages ({self._max_pages}) reached, cleaning up oldest pages")
                await self._cleanup_oldest_pages()

            # Generate unique page ID
            page_id = str(uuid.uuid4())

            # Get page metadata
            try:
                url = page.url
                title = await page.title()
            except Exception as e:
                logging.warning(f"Failed to get page metadata: {e}")
                url = "unknown"
                title = "unknown"

            # Create PageInfo
            page_info = PageInfo(
                page=page,
                page_id=page_id,
                parent_id=parent_id,
                url=url,
                title=title,
                opened_at=datetime.now(),
                page_type=page_type,
                is_closed=False
            )

            # Add to registry
            self._page_registry[page_id] = page_info

            logging.info(
                f"Registered page: {page_id} (type={page_type}, url={url}, parent={parent_id})"
            )

            return page_info

    async def push_page(self, page_info: PageInfo) -> PageInfo:
        """Push a page onto the stack and make it current.

        This is typically called after opening a new tab to switch to it.

        Args:
            page_info: PageInfo object to push

        Returns:
            The pushed PageInfo
        """
        async with self._lock:
            self._page_stack.append(page_info)
            self._current_page_id = page_info.page_id

            # Ensure the new page has visual focus
            try:
                await page_info.page.bring_to_front()
            except Exception as e:
                logging.warning(f"Failed to bring page to front: {e}")

            logging.info(
                f"Pushed page to stack: {page_info.page_id} (depth={len(self._page_stack)})"
            )

            return page_info

    async def pop_page(self) -> Optional[PageInfo]:
        """Pop the current page from stack and return to the previous page.

        This is typically called when returning from a child tab to parent tab.
        Automatically skips over any closed pages in the stack.

        Returns:
            PageInfo of the previous page (now current), or None if stack is empty
        """
        async with self._lock:
            if not self._page_stack:
                logging.warning("Cannot pop: page stack is empty")
                return None

            # Pop current page
            current_page_info = self._page_stack.pop()
            logging.debug(f"Popped page: {current_page_info.page_id}")

            # Find the next valid (non-closed) page in the stack
            while self._page_stack:
                previous_page_info = self._page_stack[-1]

                # Check if page is closed
                if previous_page_info.is_closed:
                    logging.debug(
                        f"Skipping closed page: {previous_page_info.page_id}"
                    )
                    self._page_stack.pop()
                    continue

                # Found valid page
                self._current_page_id = previous_page_info.page_id

                # Ensure the previous page has visual focus
                try:
                    await previous_page_info.page.bring_to_front()
                except Exception as e:
                    logging.warning(f"Failed to bring previous page to front: {e}")

                logging.info(
                    f"Switched to previous page: {previous_page_info.page_id} "
                    f"(depth={len(self._page_stack)})"
                )
                return previous_page_info

            # Stack is empty (all pages were closed)
            logging.warning("All parent pages are closed, no page to return to")
            self._current_page_id = None
            return None

    def get_current_page(self) -> Optional[Page]:
        """Get the current active page.

        Returns:
            Current Page instance, or None if no page is active
        """
        if not self._current_page_id:
            return None

        page_info = self._page_registry.get(self._current_page_id)
        if not page_info or page_info.is_closed:
            logging.warning(f"Current page is closed or not found: {self._current_page_id}")
            return None

        return page_info.page

    def get_current_page_info(self) -> Optional[PageInfo]:
        """Get the current active page info.

        Returns:
            Current PageInfo, or None if no page is active
        """
        if not self._current_page_id:
            return None

        return self._page_registry.get(self._current_page_id)

    def get_page_by_id(self, page_id: str) -> Optional[Page]:
        """Get a specific page by ID.

        Args:
            page_id: Page ID to look up

        Returns:
            Page instance if found and not closed, None otherwise
        """
        page_info = self._page_registry.get(page_id)
        if not page_info or page_info.is_closed:
            return None
        return page_info.page

    def get_page_info_by_id(self, page_id: str) -> Optional[PageInfo]:
        """Get a specific page info by ID.

        Args:
            page_id: Page ID to look up

        Returns:
            PageInfo if found, None otherwise
        """
        return self._page_registry.get(page_id)

    def get_page_hierarchy(self) -> Dict:
        """Get the full page hierarchy tree.

        Returns:
            Dictionary representing parent-child relationships
        """
        hierarchy = {}
        for page_id, page_info in self._page_registry.items():
            if not page_info.is_closed:
                hierarchy[page_id] = {
                    'url': page_info.url,
                    'title': page_info.title,
                    'parent_id': page_info.parent_id,
                    'page_type': page_info.page_type,
                    'depth': self._get_page_depth(page_id)
                }
        return hierarchy

    def _get_page_depth(self, page_id: str) -> int:
        """Calculate depth of a page in the hierarchy tree.

        Args:
            page_id: Page ID to calculate depth for

        Returns:
            Depth (0 for root pages, 1 for their children, etc.)
        """
        depth = 0
        current_id = page_id
        visited = set()  # Prevent infinite loops

        while current_id and current_id not in visited:
            visited.add(current_id)
            page_info = self._page_registry.get(current_id)
            if not page_info or not page_info.parent_id:
                break
            current_id = page_info.parent_id
            depth += 1

        return depth

    def get_tab_depth(self, page_id: str) -> int:
        """Public method to get tab depth (alias for _get_page_depth)."""
        return self._get_page_depth(page_id)

    def get_stack_depth(self) -> int:
        """Get current stack depth.

        Returns:
            Number of pages in the navigation stack
        """
        return len(self._page_stack)

    def get_total_pages(self) -> int:
        """Get total number of registered pages (including closed ones).

        Returns:
            Total page count
        """
        return len(self._page_registry)

    def get_active_pages_count(self) -> int:
        """Get number of active (non-closed) pages.

        Returns:
            Active page count
        """
        return sum(1 for p in self._page_registry.values() if not p.is_closed)

    async def _cleanup_oldest_pages(self, keep_count: int = 10):
        """Clean up oldest pages when limit is reached.

        Keeps the most recent pages and main pages, removes oldest child pages.

        Args:
            keep_count: Number of pages to keep
        """
        # Get all pages sorted by opened_at timestamp (oldest first)
        all_pages = sorted(
            self._page_registry.values(),
            key=lambda p: p.opened_at
        )

        # Keep main pages and most recent pages
        to_remove = []
        kept = 0

        for page_info in reversed(all_pages):  # Start from newest
            if kept >= keep_count:
                # Don't remove main pages or pages in current stack
                if page_info.page_type != 'main' and page_info.page_id not in [p.page_id for p in self._page_stack]:
                    to_remove.append(page_info.page_id)
            else:
                kept += 1

        # Remove pages from registry
        for page_id in to_remove:
            page_info = self._page_registry.pop(page_id, None)
            if page_info:
                logging.info(f"Cleaned up old page: {page_id} ({page_info.url})")
                try:
                    if not page_info.is_closed:
                        await page_info.page.close()
                except Exception as e:
                    logging.debug(f"Failed to close page during cleanup: {e}")

    async def close_page(self, page_id: str) -> bool:
        """Explicitly close a page.

        Args:
            page_id: ID of the page to close

        Returns:
            True if page was closed, False otherwise
        """
        async with self._lock:
            page_info = self._page_registry.get(page_id)
            if not page_info:
                logging.warning(f"Cannot close page: {page_id} not found")
                return False

            if page_info.is_closed:
                logging.debug(f"Page already closed: {page_id}")
                return True

            try:
                await page_info.page.close()
                page_info.is_closed = True

                # Remove from stack
                self._page_stack = [p for p in self._page_stack if p.page_id != page_id]

                # Update current page if needed
                if self._current_page_id == page_id:
                    if self._page_stack:
                        self._current_page_id = self._page_stack[-1].page_id
                    else:
                        self._current_page_id = None

                logging.info(f"Closed page: {page_id}")
                return True

            except Exception as e:
                logging.error(f"Failed to close page {page_id}: {e}")
                return False

    def get_page_context_info(self) -> Dict:
        """Get context information about current page state for AI agent.

        This provides the LLM with awareness of the current tab context.

        Returns:
            Dictionary with tab context information
        """
        current_info = self.get_current_page_info()
        if not current_info:
            return {
                'has_active_page': False,
                'total_open_tabs': 0,
                'stack_depth': 0
            }

        return {
            'has_active_page': True,
            'current_tab_id': current_info.page_id,
            'current_tab_url': current_info.url,
            'current_tab_title': current_info.title,
            'current_tab_type': current_info.page_type,
            'parent_tab_id': current_info.parent_id,
            'tab_depth': self._get_page_depth(current_info.page_id),
            'total_open_tabs': self.get_active_pages_count(),
            'stack_depth': self.get_stack_depth(),
            'can_go_back': len(self._page_stack) > 1,  # Can use SwitchBackTab
        }

    async def cleanup(self):
        """Cleanup all resources and close all pages."""
        async with self._lock:
            logging.info(f"Cleaning up PageManager ({len(self._page_registry)} pages)")

            # Close all pages
            for page_info in self._page_registry.values():
                if not page_info.is_closed:
                    try:
                        await page_info.page.close()
                    except Exception as e:
                        logging.debug(f"Error closing page during cleanup: {e}")

            # Clear all data structures
            self._page_stack.clear()
            self._page_registry.clear()
            self._current_page_id = None

            logging.info("PageManager cleanup complete")
