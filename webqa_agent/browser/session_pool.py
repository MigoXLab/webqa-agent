"""Browser Session Pool for Parallel Test Case Execution.

This module provides a pool of browser sessions that can be shared across
parallel test case executions, optimizing resource usage while maintaining
isolation between test cases.

Optimized Design (v2):
- Removed redundant Semaphore, using only Queue for natural concurrency control
- Queue.get() blocks when empty, Queue.put() unblocks waiters
- Lazy health check: only recover on failure, not on every acquire
- Optional session warmup for faster first case execution
"""

import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime

from playwright.async_api import Error as PlaywrightError

from webqa_agent.browser.session import BrowserSession


class BrowserSessionPool:
    """Manages a pool of browser sessions for parallel test execution.

    Optimized Features:
    - Queue-based concurrency control (no redundant Semaphore)
    - Lazy health checking (only on failure)
    - Optional session warmup
    - Graceful cleanup on shutdown

    Concurrency Control:
    - Queue has exactly pool_size sessions
    - acquire() blocks when Queue is empty (all sessions in use)
    - release() puts session back, unblocking waiting acquires
    - No Semaphore needed - Queue naturally limits concurrency
    """

    def __init__(self, pool_size: int = 2, browser_config: Dict = None):
        """Initialize the session pool.

        Args:
            pool_size: Number of browser sessions to maintain in the pool
            browser_config: Browser configuration dict (viewport, headless, etc.)
        """
        self.pool_size = pool_size
        self.browser_config = browser_config or {}

        # Pool management - Queue is the ONLY concurrency control
        self._available_sessions: asyncio.Queue = asyncio.Queue()
        self._all_sessions: List[BrowserSession] = []
        self._session_status: Dict[str, Dict] = {}

        # Lock for status updates only (not for concurrency control)
        self._lock = asyncio.Lock()

        # State
        self._initialized = False
        self._closed = False

        logging.info(f"[SessionPool] Initializing with size={pool_size} (Queue-only concurrency)")

    async def initialize(self, warmup_url: Optional[str] = None) -> 'BrowserSessionPool':
        """Pre-create all browser sessions in the pool.

        Args:
            warmup_url: Optional URL to navigate to during warmup (speeds up first case)

        Returns:
            Self for method chaining
        """
        if self._initialized:
            logging.warning("[SessionPool] Already initialized")
            return self

        existing_sessions = len(self._all_sessions)
        sessions_to_create = self.pool_size - existing_sessions

        if sessions_to_create <= 0:
            self._initialized = True
            logging.info(f"[SessionPool] Already has {existing_sessions} session(s)")
            return self

        logging.info(f"[SessionPool] Creating {sessions_to_create} sessions in parallel...")
        start_time = datetime.now()
        created_sessions = []

        try:
            # Parallel session creation with pre-assigned session IDs
            async def create_session(index: int, session_id: str) -> BrowserSession:
                session = BrowserSession(
                    session_id=session_id,
                    browser_config=self.browser_config
                )
                await session.initialize()
                logging.debug(f"[SessionPool] Session {index+1}/{sessions_to_create} created ({session_id})")
                return session

            # Pre-generate session IDs for deterministic naming
            session_ids = [
                f"pool_session_{existing_sessions + i}"
                for i in range(sessions_to_create)
            ]

            created_sessions = await asyncio.gather(*[
                create_session(i, session_ids[i]) for i in range(sessions_to_create)
            ])

            init_duration = (datetime.now() - start_time).total_seconds()
            logging.info(f"[SessionPool] {sessions_to_create} sessions created in {init_duration:.2f}s")

            # Optional warmup - navigate all sessions to target URL in parallel
            if warmup_url:
                logging.info(f"[SessionPool] Warming up sessions with URL: {warmup_url}")
                warmup_start = datetime.now()
                await asyncio.gather(*[
                    session.get_page().goto(warmup_url, wait_until='domcontentloaded')
                    for session in created_sessions
                    if session.driver and not session.is_closed()
                ], return_exceptions=True)
                warmup_duration = (datetime.now() - warmup_start).total_seconds()
                logging.info(f"[SessionPool] Warmup completed in {warmup_duration:.2f}s")

            # Register sessions (session_id already assigned during creation)
            for session in created_sessions:
                self._all_sessions.append(session)
                await self._available_sessions.put(session)

                self._session_status[session.session_id] = {
                    'in_use': False,
                    'created_at': datetime.now().isoformat(),
                    'use_count': 0,
                    'last_acquired_at': None,
                    'last_released_at': None,
                    'external': False,
                    'failed_count': 0
                }

            self._initialized = True
            total_duration = (datetime.now() - start_time).total_seconds()
            logging.info(f"[SessionPool] Initialized with {len(self._all_sessions)} sessions in {total_duration:.2f}s")
            return self

        except Exception as e:
            logging.error(f"[SessionPool] Initialization failed: {e}")
            if created_sessions:
                await asyncio.gather(*[
                    self._safe_close_session(s) for s in created_sessions if s
                ], return_exceptions=True)
            await self.close_all()
            raise

    async def add_external_session(self, session: BrowserSession):
        """Add an externally created session to the pool.

        Args:
            session: An initialized BrowserSession instance
        """
        if self._closed:
            raise RuntimeError("Cannot add session to closed pool")

        if not session or not session.driver:
            raise ValueError("Session must be initialized before adding to pool")

        async with self._lock:
            self._all_sessions.append(session)
            await self._available_sessions.put(session)

            session_id = session.session_id
            self._session_status[session_id] = {
                'in_use': False,
                'created_at': datetime.now().isoformat(),
                'use_count': 0,
                'last_acquired_at': None,
                'last_released_at': None,
                'external': True,
                'failed_count': 0
            }

            if not self._initialized:
                self.pool_size = max(self.pool_size, len(self._all_sessions))

            logging.info(f"[SessionPool] Added external session: {session_id}")

    async def acquire(self, timeout: Optional[float] = 60.0) -> BrowserSession:
        """Acquire a browser session from the pool.

        Queue-based concurrency control:
        - If Queue has sessions, returns immediately
        - If Queue is empty, blocks until a session is released
        - No Semaphore needed - Queue naturally limits concurrency

        Args:
            timeout: Maximum time to wait for a session (seconds)

        Returns:
            Available BrowserSession instance
        """
        if not self._initialized:
            raise RuntimeError("BrowserSessionPool not initialized")

        if self._closed:
            raise RuntimeError("BrowserSessionPool has been closed")

        try:
            # Queue.get() blocks when empty - this IS the concurrency control
            if timeout is None:
                # Wait indefinitely - normal behavior for queued execution
                session = await self._available_sessions.get()
            else:
                session = await asyncio.wait_for(
                    self._available_sessions.get(),
                    timeout=timeout
                )

            # Update status (no health check here - lazy check on failure)
            async with self._lock:
                if session.session_id in self._session_status:
                    status = self._session_status[session.session_id]
                    status['in_use'] = True
                    status['use_count'] += 1
                    status['last_acquired_at'] = datetime.now().isoformat()

            logging.debug(f"[SessionPool] Acquired: {session.session_id}")
            return session

        except asyncio.TimeoutError:
            logging.error(f"[SessionPool] Timeout acquiring session (waited {timeout}s)")
            raise

    async def release(self, session: BrowserSession, failed: bool = False):
        """Release a browser session back to the pool.

        Args:
            session: The session to release
            failed: If True, session will be health-checked and possibly recovered
        """
        if not session:
            logging.warning("[SessionPool] Attempting to release None session")
            return

        session_id = session.session_id

        if session_id not in self._session_status:
            logging.warning(f"[SessionPool] Releasing unknown session: {session_id}")
            # Still put it back to avoid losing sessions
            await self._available_sessions.put(session)
            return

        try:
            # Lazy health check - only if caller indicates failure
            if failed:
                logging.info(f"[SessionPool] Session {session_id} marked as failed, recovering...")
                async with self._lock:
                    self._session_status[session_id]['failed_count'] += 1

                session = await self._recover_session(session)

            # Update status
            async with self._lock:
                status = self._session_status[session.session_id]
                status['in_use'] = False
                status['last_released_at'] = datetime.now().isoformat()

            # Return to pool - this unblocks waiting acquire() calls
            await self._available_sessions.put(session)
            logging.debug(f"[SessionPool] Released: {session.session_id}")

        except Exception as e:
            logging.error(f"[SessionPool] Error releasing {session_id}: {e}")
            # Try to put back anyway to prevent pool depletion
            try:
                await self._available_sessions.put(session)
            except Exception:
                pass

    async def _recover_session(self, failed_session: BrowserSession) -> BrowserSession:
        """Recover a failed session by recreating it.

        Args:
            failed_session: The session that failed

        Returns:
            New healthy session
        """
        session_id = failed_session.session_id
        logging.info(f"[SessionPool] Recovering session: {session_id}")

        try:
            await failed_session.close()
        except Exception as e:
            logging.warning(f"[SessionPool] Error closing failed session: {e}")

        try:
            new_session = BrowserSession(
                session_id=session_id,
                browser_config=self.browser_config
            )
            await new_session.initialize()

            async with self._lock:
                for i, sess in enumerate(self._all_sessions):
                    if sess.session_id == session_id:
                        self._all_sessions[i] = new_session
                        break
                self._session_status[session_id]['use_count'] = 0

            logging.info(f"[SessionPool] Recovered session: {session_id}")
            return new_session

        except Exception as e:
            logging.error(f"[SessionPool] Failed to recover session {session_id}: {e}")
            raise RuntimeError(f"Session recovery failed: {e}")

    async def close_all(self):
        """Close all sessions in the pool."""
        if self._closed:
            return

        logging.info(f"[SessionPool] Closing {len(self._all_sessions)} sessions...")

        await asyncio.gather(*[
            self._safe_close_session(s) for s in self._all_sessions if s
        ], return_exceptions=True)

        self._all_sessions.clear()
        self._session_status.clear()
        self._closed = True

        logging.info("[SessionPool] Closed successfully")

    async def _safe_close_session(self, session: BrowserSession):
        """Safely close a session."""
        try:
            await session.close()
        except Exception as e:
            logging.warning(f"[SessionPool] Error closing session: {e}")

    def get_pool_stats(self) -> Dict:
        """Get current pool statistics."""
        in_use_count = sum(1 for s in self._session_status.values() if s['in_use'])
        total_uses = sum(s['use_count'] for s in self._session_status.values())
        total_failures = sum(s['failed_count'] for s in self._session_status.values())

        return {
            'pool_size': self.pool_size,
            'in_use': in_use_count,
            'available': self.pool_size - in_use_count,
            'total_uses': total_uses,
            'total_failures': total_failures,
            'initialized': self._initialized,
            'closed': self._closed,
            'sessions': dict(self._session_status)
        }

    async def __aenter__(self):
        if not self._initialized:
            await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close_all()