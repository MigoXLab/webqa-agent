"""Browser Session Pool for Parallel Test Case Execution.

This module provides a pool of browser sessions that can be shared across
parallel test case executions, optimizing resource usage while maintaining
isolation between test cases.
"""

import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime

from playwright.async_api import Error as PlaywrightError

from webqa_agent.browser.session import BrowserSession


class BrowserSessionPool:
    """Manages a pool of browser sessions for parallel test execution.

    Features:
    - Pre-creates a configurable number of browser sessions
    - Async acquire/release with semaphore-based concurrency control
    - Session health checking and auto-recovery
    - Graceful cleanup on shutdown
    """

    def __init__(self, pool_size: int = 2, browser_config: Dict = None):
        """Initialize the session pool.

        Args:
            pool_size: Number of browser sessions to maintain in the pool
            browser_config: Browser configuration dict (viewport, headless, etc.)
        """
        self.pool_size = pool_size
        self.browser_config = browser_config or {}

        # Pool management
        self._available_sessions: asyncio.Queue = asyncio.Queue()
        self._all_sessions: List[BrowserSession] = []
        self._session_status: Dict[str, Dict] = {}  # session_id -> {in_use, created_at, use_count}

        # Concurrency control
        self._semaphore = asyncio.Semaphore(pool_size)
        self._lock = asyncio.Lock()

        # State
        self._initialized = False
        self._closed = False

        logging.info(f"Initializing BrowserSessionPool with size={pool_size}")

    async def initialize(self) -> 'BrowserSessionPool':
        """Pre-create all browser sessions in the pool.

        Returns:
            Self for method chaining
        """
        if self._initialized:
            logging.warning("BrowserSessionPool already initialized")
            return self

        logging.info(f"Creating {self.pool_size} browser sessions...")

        try:
            for i in range(self.pool_size):
                session = BrowserSession(browser_config=self.browser_config)
                await session.initialize()

                session_id = f"pool_session_{i}"
                session.session_id = session_id

                self._all_sessions.append(session)
                await self._available_sessions.put(session)

                self._session_status[session_id] = {
                    'in_use': False,
                    'created_at': datetime.now().isoformat(),
                    'use_count': 0,
                    'last_acquired_at': None,
                    'last_released_at': None
                }

                logging.info(f"Created session {i+1}/{self.pool_size}: {session_id}")

            self._initialized = True
            logging.info(f"BrowserSessionPool initialized successfully with {self.pool_size} sessions")
            return self

        except Exception as e:
            logging.error(f"Failed to initialize BrowserSessionPool: {e}")
            # Clean up any sessions that were created
            await self.close_all()
            raise

    async def acquire(self, timeout: Optional[float] = 60.0) -> BrowserSession:
        """Acquire a browser session from the pool.

        Args:
            timeout: Maximum time to wait for a session (seconds)

        Returns:
            Available BrowserSession instance

        Raises:
            asyncio.TimeoutError: If no session available within timeout
            RuntimeError: If pool not initialized or already closed
        """
        if not self._initialized:
            raise RuntimeError("BrowserSessionPool not initialized. Call initialize() first.")

        if self._closed:
            raise RuntimeError("BrowserSessionPool has been closed")

        # Wait for semaphore (limits concurrent acquisitions)
        await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout)

        try:
            # Get session from queue (with timeout)
            session = await asyncio.wait_for(
                self._available_sessions.get(),
                timeout=timeout
            )

            # Check session health
            is_healthy = await self._check_session_health(session)
            if not is_healthy:
                logging.warning(f"Session {session.session_id} unhealthy, attempting recovery...")
                session = await self._recover_session(session)

            # Update status
            async with self._lock:
                if session.session_id in self._session_status:
                    status = self._session_status[session.session_id]
                    status['in_use'] = True
                    status['use_count'] += 1
                    status['last_acquired_at'] = datetime.now().isoformat()

            logging.debug(f"Acquired session: {session.session_id} (use_count={status['use_count']})")
            return session

        except asyncio.TimeoutError:
            self._semaphore.release()
            logging.error(f"Timeout acquiring session from pool (waited {timeout}s)")
            raise
        except Exception as e:
            self._semaphore.release()
            logging.error(f"Error acquiring session from pool: {e}")
            raise

    async def release(self, session: BrowserSession):
        """Release a browser session back to the pool.

        Args:
            session: The session to release
        """
        if not session or session.session_id not in self._session_status:
            logging.warning(f"Attempting to release unknown session: {session.session_id if session else 'None'}")
            return

        try:
            # Update status
            async with self._lock:
                status = self._session_status[session.session_id]
                status['in_use'] = False
                status['last_released_at'] = datetime.now().isoformat()

            # Return to pool
            await self._available_sessions.put(session)
            self._semaphore.release()

            logging.debug(f"Released session: {session.session_id}")

        except Exception as e:
            logging.error(f"Error releasing session {session.session_id}: {e}")
            # Still release semaphore to prevent deadlock
            self._semaphore.release()

    async def _check_session_health(self, session: BrowserSession) -> bool:
        """Check if a browser session is healthy and usable.

        Args:
            session: The session to check

        Returns:
            True if session is healthy, False otherwise
        """
        try:
            if not session:
                return False

            # Try to get page reference
            page = session.get_page()
            if not page:
                return False

            # Check if page is still responsive (simple check)
            url = page.url
            if not url:
                return False

            return True

        except (PlaywrightError, AttributeError, Exception) as e:
            logging.warning(f"Session health check failed: {e}")
            return False

    async def _recover_session(self, failed_session: BrowserSession) -> BrowserSession:
        """Attempt to recover a failed session by recreating it.

        Args:
            failed_session: The session that failed health check

        Returns:
            New healthy session (or raises exception if recovery fails)
        """
        session_id = failed_session.session_id
        logging.info(f"Recovering session: {session_id}")

        try:
            # Close the failed session
            await failed_session.close()
        except Exception as e:
            logging.warning(f"Error closing failed session {session_id}: {e}")

        try:
            # Create new session
            new_session = BrowserSession(browser_config=self.browser_config)
            await new_session.initialize()
            new_session.session_id = session_id

            # Update references
            async with self._lock:
                for i, sess in enumerate(self._all_sessions):
                    if sess.session_id == session_id:
                        self._all_sessions[i] = new_session
                        break

                # Reset use count but keep other stats
                self._session_status[session_id]['use_count'] = 0

            logging.info(f"Successfully recovered session: {session_id}")
            return new_session

        except Exception as e:
            logging.error(f"Failed to recover session {session_id}: {e}")
            raise RuntimeError(f"Session recovery failed: {e}")

    async def close_all(self):
        """Close all sessions in the pool."""
        if self._closed:
            logging.warning("BrowserSessionPool already closed")
            return

        logging.info(f"Closing {len(self._all_sessions)} browser sessions...")

        close_tasks = []
        for session in self._all_sessions:
            if session:
                close_tasks.append(self._safe_close_session(session))

        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)

        self._all_sessions.clear()
        self._session_status.clear()
        self._closed = True

        logging.info("BrowserSessionPool closed successfully")

    async def _safe_close_session(self, session: BrowserSession):
        """Safely close a session with error handling."""
        try:
            await session.close()
        except Exception as e:
            logging.warning(f"Error closing session {session.session_id}: {e}")

    def get_pool_stats(self) -> Dict:
        """Get current pool statistics.

        Returns:
            Dict with pool status information
        """
        in_use_count = sum(1 for status in self._session_status.values() if status['in_use'])
        available_count = self.pool_size - in_use_count
        total_uses = sum(status['use_count'] for status in self._session_status.values())

        return {
            'pool_size': self.pool_size,
            'in_use': in_use_count,
            'available': available_count,
            'total_uses': total_uses,
            'initialized': self._initialized,
            'closed': self._closed,
            'sessions': dict(self._session_status)
        }

    async def __aenter__(self):
        """Async context manager entry."""
        if not self._initialized:
            await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close_all()
