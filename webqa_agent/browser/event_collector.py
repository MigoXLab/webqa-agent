"""Per-action browser event collector.

Captures browser events (download, console errors, JS exceptions, request
failures) that happen *between* two ``clear()`` calls.  The typical flow is:

    collector.clear()          # reset before an action
    await page.click(...)      # action triggers browser events
    events = await collector.collect(timeout=5)  # harvest events

The collected dict is then embedded into the action response / last_action_context
so that:
- The LLM agent can see what happened (e.g. download completed, JS error)
- ``execute_ui_assertion`` can verify those events programmatically
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from playwright.async_api import Page

logger = logging.getLogger(__name__)


@dataclass
class _DownloadRecord:
    success: bool = False
    url: str = ''
    suggested_filename: str = ''
    saved_path: Optional[str] = None
    file_size: Optional[int] = None
    failure: Optional[str] = None


class BrowserEventCollector:
    """Collects browser events between ``clear()`` / ``collect()`` cycles.

    Designed to be attached **once** to a page (or re-attached after reset).
    Thread-safe within a single asyncio event loop.

    Captured event types
    --------------------
    * **download** – file download (start + completion)
    * **console_error** – ``console.error()`` messages
    * **page_error** – uncaught JavaScript exceptions (``pageerror``)
    * **request_failed** – network requests that failed (``requestfailed``)
    """

    def __init__(self, downloads_dir: Optional[str] = None):
        self._downloads_dir = downloads_dir

        # Per-action event buffers (cleared before each action)
        self._downloads: List[_DownloadRecord] = []
        self._console_errors: List[Dict[str, Any]] = []
        self._page_errors: List[Dict[str, str]] = []
        self._request_failures: List[Dict[str, Any]] = []

        # Async signal: set when at least one download finishes
        self._download_event: asyncio.Event = asyncio.Event()

        self._attached = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def attach(self, page: Page) -> None:
        """Register event listeners on *page*.

        Safe to call multiple times (detach + re-attach pattern for
        ``reset_context``).
        """
        if self._attached:
            return
        page.on('download', self._on_download)
        page.on('console', self._on_console)
        page.on('pageerror', self._on_page_error)
        page.on('requestfailed', self._on_request_failed)
        self._attached = True
        logger.debug('[EventCollector] Attached to page')

    def detach(self, page: Page) -> None:
        """Remove event listeners (idempotent)."""
        if not self._attached:
            return
        for event, handler in [
            ('download', self._on_download),
            ('console', self._on_console),
            ('pageerror', self._on_page_error),
            ('requestfailed', self._on_request_failed),
        ]:
            try:
                page.remove_listener(event, handler)
            except Exception:
                pass
        self._attached = False

    def clear(self) -> None:
        """Reset all event buffers.

        Call before executing an action.
        """
        self._downloads.clear()
        self._console_errors.clear()
        self._page_errors.clear()
        self._request_failures.clear()
        self._download_event.clear()

    def reset(self, page: Page) -> None:
        """Clear buffers, mark as detached, and attach to a new *page*.

        Use when the old page has been closed (e.g. ``reset_context``).
        """
        self.clear()
        self._attached = False
        self.attach(page)

    async def collect(self, timeout: float = 5.0) -> Dict[str, Any]:
        """Return all captured events since the last ``clear()``.

        If a download was started, waits up to *timeout* seconds for it to
        finish (save_as completes).  Other events are available immediately.

        Returns:
            Dict with keys present **only** when events were captured::

                {
                    "download": {...},          # if a download occurred
                    "console_errors": [...],    # if console.error() fired
                    "page_errors": [...],       # if uncaught JS exceptions
                    "request_failures": [...],  # if network requests failed
                }

            Empty dict ``{}`` means nothing noteworthy happened.
        """
        # If a download started, wait for it to finish
        if self._downloads:
            try:
                await asyncio.wait_for(
                    self._download_event.wait(), timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.debug('[EventCollector] Download wait timed out')

        result: Dict[str, Any] = {}

        if self._downloads:
            dl = self._downloads[-1]  # most recent download
            result['download'] = {
                'success': dl.success,
                'url': dl.url,
                'suggested_filename': dl.suggested_filename,
                'saved_path': dl.saved_path,
                'file_size': dl.file_size,
                'failure': dl.failure,
            }

        if self._console_errors:
            result['console_errors'] = list(self._console_errors)

        if self._page_errors:
            result['page_errors'] = list(self._page_errors)

        if self._request_failures:
            result['request_failures'] = list(self._request_failures)

        return result

    # ------------------------------------------------------------------
    # Playwright event handlers (private)
    # ------------------------------------------------------------------

    async def _on_download(self, download) -> None:
        rec = _DownloadRecord(
            url=download.url,
            suggested_filename=download.suggested_filename,
        )
        self._downloads.append(rec)
        logger.info(
            f'[EventCollector] Download started: '
            f'{rec.suggested_filename} from {rec.url}'
        )

        failure = await download.failure()
        if failure:
            rec.success = False
            rec.failure = failure
            logger.warning(f'[EventCollector] Download failed: {failure}')
            self._download_event.set()
            return

        # Persist the file and verify it actually landed on disk
        if self._downloads_dir:
            from pathlib import Path
            dest = Path(self._downloads_dir) / rec.suggested_filename
            try:
                await download.save_as(str(dest))
                if dest.exists():
                    rec.saved_path = str(dest)
                    rec.file_size = dest.stat().st_size
                    rec.success = rec.file_size > 0
                    if not rec.success:
                        rec.failure = 'file saved but size is 0 bytes'
                else:
                    rec.success = False
                    rec.failure = 'save_as completed but file not found on disk'
            except Exception as e:
                rec.success = False
                rec.failure = f'save_as failed: {e}'
                logger.warning(f'[EventCollector] save_as failed: {e}')
        else:
            rec.success = False
            rec.failure = 'no downloads directory configured'

        if rec.success:
            logger.info(
                f'[EventCollector] Download verified: '
                f'{rec.suggested_filename} ({rec.file_size} bytes) at {rec.saved_path}'
            )
        else:
            logger.warning(
                f'[EventCollector] Download not verified: '
                f'{rec.suggested_filename}, reason: {rec.failure}'
            )
        self._download_event.set()

    def _on_console(self, msg) -> None:
        if msg.type == 'error':
            self._console_errors.append({
                'text': msg.text,
                'location': str(getattr(msg, 'location', '')),
            })

    def _on_page_error(self, error) -> None:
        self._page_errors.append({
            'message': str(error),
        })
        logger.debug(f'[EventCollector] pageerror: {error}')

    def _on_request_failed(self, request) -> None:
        self._request_failures.append({
            'url': request.url,
            'method': request.method,
            'failure': request.failure,
        })
