"""Unified browser event collector.

Provides **two layers** of event capture on a single set of Playwright listeners:

1. **Per-action buffers** – cleared before each action via ``clear()``, harvested
   via ``collect()``.  Used for verify-context (LLM sees what happened in one step).

2. **Session-wide buffers** – accumulated over the entire session, returned by
   ``get_session_summary()``.  Used for report generation and WARNING status.

Typical flow::

    collector.set_ignore_rules(console_rules, network_rules)
    # ... per action ...
    await collector.clear()                  # reset per-action only
    await page.click(...)
    events = await collector.collect()      # per-action snapshot

    # ... end of session ...
    summary = collector.get_session_summary()   # full session data
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from playwright.async_api import Page

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 5 * 1024  # 5KB limit for stored bodies

_SKIPPED_CONTENT_TYPES = (
    'image/', 'audio/', 'video/', 'application/pdf',
    'application/octet-stream', 'font/', 'application/x-font',
    'application/javascript', 'application/x-javascript',
    'text/javascript', 'text/css',
)


# ---------------------------------------------------------------------------
# Ignore-rule matching (moved from check.py)
# ---------------------------------------------------------------------------

class IgnoreRuleMatcher:
    """Helper class to match ignore rules with patterns."""

    @staticmethod
    def should_ignore_network(url: str, ignore_rules: Optional[List[Dict]] = None) -> bool:
        if not ignore_rules:
            return False
        for rule in ignore_rules:
            pattern = rule.get('pattern', '')
            rule_type = rule.get('type', 'url')
            if not pattern:
                continue
            try:
                if rule_type in ('domain', 'url'):
                    if re.search(pattern, url, re.IGNORECASE):
                        return True
            except re.error:
                continue
        return False

    @staticmethod
    def should_ignore_console(message: str, ignore_rules: Optional[List[Dict]] = None) -> bool:
        if not ignore_rules:
            return False
        for rule in ignore_rules:
            pattern = rule.get('pattern', '')
            match_type = rule.get('match_type', 'contains')
            if not pattern:
                continue
            try:
                if match_type == 'regex':
                    if re.search(pattern, message, re.IGNORECASE):
                        return True
                elif match_type == 'contains':
                    if pattern.lower() in message.lower():
                        return True
            except re.error:
                continue
        return False


# ---------------------------------------------------------------------------
# Download record
# ---------------------------------------------------------------------------

@dataclass
class _DownloadRecord:
    success: bool = False
    url: str = ''
    suggested_filename: str = ''
    saved_path: Optional[str] = None
    file_size: Optional[int] = None
    failure: Optional[str] = None


# ---------------------------------------------------------------------------
# Content helpers (ported from NetworkCheck)
# ---------------------------------------------------------------------------

def _sanitize_content(data: Any) -> Any:
    """Recursively remove markdown code blocks to save space."""
    if isinstance(data, str):
        code_block_pattern = r'```[\s\S]*?```'
        if re.search(code_block_pattern, data):
            data = re.sub(code_block_pattern, '<Code block omitted>', data)
        return data
    elif isinstance(data, list):
        return [_sanitize_content(item) for item in data]
    elif isinstance(data, dict):
        return {k: _sanitize_content(v) for k, v in data.items()}
    return data


def _truncate_payload(payload: Any) -> Optional[str]:
    """Trim request payload to keep monitoring data lightweight."""
    if payload is None:
        return None
    try:
        if isinstance(payload, (dict, list)):
            text = json.dumps(payload, ensure_ascii=False)[:MAX_BODY_BYTES]
            if len(text) >= MAX_BODY_BYTES:
                text += '... [payload truncated]'
            return text
        text = str(payload)
        if len(text) > MAX_BODY_BYTES:
            return text[:MAX_BODY_BYTES] + '... [payload truncated]'
        return text
    except Exception:
        return '<payload truncated>'


def _truncate_body(body_bytes: bytes, content_type: str) -> str:
    """Trim response body to MAX_BODY_BYTES and sanitize."""
    if not body_bytes:
        return ''
    size = len(body_bytes)
    slice_bytes = body_bytes[:MAX_BODY_BYTES]
    try:
        text = slice_bytes.decode('utf-8', errors='replace')
    except Exception:
        text = str(slice_bytes)
    text = _sanitize_content(text)
    if size > MAX_BODY_BYTES:
        text += f'\n... [body truncated to {MAX_BODY_BYTES} bytes from {size}]'
    return text


# ---------------------------------------------------------------------------
# BrowserEventCollector
# ---------------------------------------------------------------------------

class BrowserEventCollector:
    """Unified browser event collector with per-action and session-wide
    buffers.

    **Per-action data** (console errors, page errors, failed requests) is
    collected via Playwright 1.56+ native APIs (``page.console_messages()``,
    ``page.page_errors()``, ``page.requests()``) using snapshot-diff: indices
    are recorded at ``clear()`` and new items since then are returned by
    ``collect()``.

    **Session-wide data** uses event listeners for real-time processing
    (ignore-rule filtering, response body capture, request record tracking).

    Captured event types
    --------------------
    * **download** – file download (start + completion)
    * **console** – ``console.error()`` messages
    * **pageerror** – uncaught JavaScript exceptions
    * **requestfailed** – network requests that failed
    * **request / response / requestfinished** – full API monitoring
    """

    def __init__(self, downloads_dir: Optional[str] = None):
        self._downloads_dir = downloads_dir
        self._page: Optional[Page] = None

        # -- Ignore rules (set later via set_ignore_rules) --
        self._console_ignore_rules: List[Dict] = []
        self._network_ignore_rules: List[Dict] = []

        # -- Per-action: downloads need manual buffer (no native API) --
        self._downloads: List[_DownloadRecord] = []
        self._download_event: asyncio.Event = asyncio.Event()

        # -- Per-action: snapshot indices for native API diffing --
        # Playwright 1.56+ provides page.console_messages(), page.page_errors(),
        # page.requests() which track events internally.  We record the index
        # at clear() and diff at collect() to get per-action events.
        self._console_snapshot_idx: int = 0
        self._page_errors_snapshot_idx: int = 0
        self._requests_snapshot_idx: int = 0

        # -- Session-wide buffers (accumulated, never cleared by clear()) --
        self._ses_console_errors: List[Dict[str, Any]] = []
        self._ses_ignored_console: List[Dict[str, Any]] = []
        self._ses_page_errors: List[Dict[str, str]] = []
        self._ses_requests: List[Dict[str, Any]] = []
        self._ses_responses: List[Dict[str, Any]] = []
        self._ses_failed_requests: List[Dict[str, Any]] = []

        self._attached = False

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_ignore_rules(
        self,
        console_rules: Optional[List[Dict]] = None,
        network_rules: Optional[List[Dict]] = None,
    ) -> None:
        """Set ignore rules for session-wide filtering.

        Per-action buffers are **not** filtered (verify needs all data).
        """
        self._console_ignore_rules = console_rules or []
        self._network_ignore_rules = network_rules or []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def attach(self, page: Page) -> None:
        """Register event listeners on *page*.

        Per-action console/pageerror/request data uses Playwright 1.56+
        native APIs in ``collect()``.  Event listeners here serve
        session-wide accumulation (ignore-rule filtering, response body
        capture).
        """
        if self._attached:
            return
        self._page = page
        page.on('download', self._on_download)
        page.on('console', self._on_console)
        page.on('pageerror', self._on_page_error)
        page.on('requestfailed', self._on_request_failed)
        page.on('request', self._on_request)
        page.on('response', self._on_response)
        page.on('requestfinished', self._on_request_finished)
        self._attached = True
        logger.debug('[EventCollector] Attached to page (7 listeners)')

    def detach(self, page: Page) -> None:
        """Remove event listeners (idempotent)."""
        if not self._attached:
            return
        handlers = [
            ('download', self._on_download),
            ('console', self._on_console),
            ('pageerror', self._on_page_error),
            ('requestfailed', self._on_request_failed),
            ('request', self._on_request),
            ('response', self._on_response),
            ('requestfinished', self._on_request_finished),
        ]
        for event, handler in handlers:
            try:
                page.remove_listener(event, handler)
            except Exception:
                pass
        self._attached = False
        self._page = None

    async def clear(self) -> None:
        """Reset **per-action** state only.

        Snapshots current Playwright native API indices so that the next
        ``collect()`` returns only events that occurred after this point.
        Session-wide buffers are kept.
        """
        self._downloads.clear()
        self._download_event.clear()
        if self._page and not self._page.is_closed():
            self._console_snapshot_idx = len(await self._page.console_messages())
            self._page_errors_snapshot_idx = len(await self._page.page_errors())
            self._requests_snapshot_idx = len(await self._page.requests())
        else:
            self._console_snapshot_idx = 0
            self._page_errors_snapshot_idx = 0
            self._requests_snapshot_idx = 0

    async def reset(self, page: Page) -> None:
        """Detach from old page, clear per-action state, attach to new page.

        Session-wide network tracking (requests/responses) is also reset
        because the old page is gone and pending request state is stale.
        Console and download session history is preserved.
        """
        self._page = None  # old page is dead; clear before clear() snapshots
        await self.clear()
        self._ses_requests.clear()
        self._ses_responses.clear()
        self._ses_failed_requests.clear()
        self._attached = False
        self.attach(page)

    def reset_session(self) -> None:
        """Clear all session-wide buffers.

        Call when starting a new test case.
        """
        self._ses_console_errors.clear()
        self._ses_ignored_console.clear()
        self._ses_page_errors.clear()
        self._ses_requests.clear()
        self._ses_responses.clear()
        self._ses_failed_requests.clear()

    # ------------------------------------------------------------------
    # Per-action API
    # ------------------------------------------------------------------

    async def collect(self, timeout: float = 5.0) -> Dict[str, Any]:
        """Return per-action events since the last ``clear()``.

        Uses Playwright 1.56+ native APIs (``page.console_messages()``,
        ``page.page_errors()``, ``page.requests()``) to snapshot events
        that occurred since the last ``clear()`` call.

        If a download was started, waits up to *timeout* seconds for
        completion.  Returns empty dict when nothing happened.
        """
        if self._downloads:
            try:
                await asyncio.wait_for(
                    self._download_event.wait(), timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.debug('[EventCollector] Download wait timed out')

        result: Dict[str, Any] = {}

        if self._downloads:
            dl = self._downloads[-1]
            result['download'] = {
                'success': dl.success,
                'url': dl.url,
                'suggested_filename': dl.suggested_filename,
                'saved_path': dl.saved_path,
                'file_size': dl.file_size,
                'failure': dl.failure,
            }

        if self._page and not self._page.is_closed():
            all_msgs = await self._page.console_messages()
            new_msgs = all_msgs[self._console_snapshot_idx:]
            console_errors = [
                {
                    'text': msg.text,
                    'location': self._format_console_location(msg),
                }
                for msg in new_msgs
                if msg.type == 'error'
            ]
            if console_errors:
                result['console_errors'] = console_errors

            all_page_errors = await self._page.page_errors()
            new_page_errors = all_page_errors[self._page_errors_snapshot_idx:]
            if new_page_errors:
                result['page_errors'] = [
                    {'message': str(e)} for e in new_page_errors
                ]

            all_requests = await self._page.requests()
            new_requests = all_requests[self._requests_snapshot_idx:]
            failed = [
                {
                    'url': r.url,
                    'method': r.method,
                    'failure': r.failure,
                }
                for r in new_requests
                if r.failure
            ]
            if failed:
                result['request_failures'] = failed

        return result

    # ------------------------------------------------------------------
    # Session-wide API
    # ------------------------------------------------------------------

    def get_session_summary(self) -> Dict[str, Any]:
        """Return accumulated session data in the monitoring format.

        Compatible with the old ``get_monitoring_results()`` return value::

            {
                'console': [{'msg': ..., 'location': ...}, ...],
                'network': {
                    'requests': [...],
                    'responses': [...],
                    'failed_requests': [...]
                }
            }
        """
        return {
            'console': list(self._ses_console_errors),
            'network': {
                'requests': list(self._ses_requests),
                'responses': list(self._ses_responses),
                'failed_requests': list(self._ses_failed_requests),
            },
        }

    def get_session_console_errors(self) -> List[Dict[str, Any]]:
        """Session-wide console errors (ignore-rules applied)."""
        return list(self._ses_console_errors)

    def get_session_ignored_console(self) -> List[Dict[str, Any]]:
        """Ignored console errors (for debugging)."""
        return list(self._ses_ignored_console)

    def get_session_network(self) -> Dict[str, Any]:
        """Session-wide network data."""
        return {
            'requests': list(self._ses_requests),
            'responses': list(self._ses_responses),
            'failed_requests': list(self._ses_failed_requests),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_console_location(msg) -> str:
        """Format ConsoleMessage.location to a readable string."""
        loc = getattr(msg, 'location', None) or {}
        if isinstance(loc, dict) and loc.get('url'):
            return (
                f"{loc['url']}:{loc.get('lineNumber', '?')}"
                f":{loc.get('columnNumber', '?')}"
            )
        return ''

    # ------------------------------------------------------------------
    # Playwright event handlers (session-wide accumulation only)
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
        """Session-wide console error accumulation with ignore-rule filtering.

        Per-action data uses page.console_messages() in collect().
        """
        if msg.type != 'error':
            return

        error_text = msg.text
        loc_raw = getattr(msg, 'location', None) or {}

        if IgnoreRuleMatcher.should_ignore_console(error_text, self._console_ignore_rules):
            self._ses_ignored_console.append({
                'msg': error_text,
                'location': loc_raw,
                'ignored': True,
            })
        else:
            self._ses_console_errors.append({
                'msg': error_text,
                'location': loc_raw,
            })

    def _on_page_error(self, error) -> None:
        """Session-wide page error accumulation.

        Per-action data uses page.page_errors() in collect().
        """
        self._ses_page_errors.append({'message': str(error)})
        logger.debug(f'[EventCollector] pageerror: {error}')

    def _on_request_failed(self, request) -> None:
        """Session-wide failed request tracking.

        Per-action data uses page.requests() in collect().
        """
        request_payload = None
        for req in self._ses_requests:
            if req['url'] == request.url:
                req['failed'] = True
                request_payload = req.get('payload')
                break

        self._ses_failed_requests.append({
            'url': request.url,
            'failure': request.failure,
            'method': request.method,
            'payload': request_payload,
        })

    async def _on_request(self, request) -> None:
        request_payload = None
        try:
            post_data = request.post_data
            if post_data:
                try:
                    request_payload = json.loads(post_data)
                except (json.JSONDecodeError, ValueError):
                    request_payload = post_data
        except Exception:
            pass

        self._ses_requests.append({
            'url': request.url,
            'method': request.method,
            'payload': _truncate_payload(request_payload),
            'completed': False,
            'failed': False,
        })

    async def _on_response(self, response) -> None:
        response_url = response.url

        if IgnoreRuleMatcher.should_ignore_network(response_url, self._network_ignore_rules):
            return

        try:
            current_request = None
            for req in self._ses_requests:
                if req['url'] == response_url:
                    current_request = req
                    break
            if not current_request:
                return

            try:
                headers = await response.all_headers()
                content_type = headers.get('content-type', '')
            except Exception:
                content_type = ''

            response_data: Dict[str, Any] = {
                'url': response_url,
                'status': response.status,
                'method': response.request.method,
                'content_type': content_type,
                'payload': current_request.get('payload'),
            }

            if response.status >= 400:
                response_data['error'] = f'HTTP {response.status}'
                self._ses_responses.append(response_data)
                return

            try:
                ct_lower = content_type.lower()
                if 'text/event-stream' in ct_lower:
                    response_data['body'] = '<event-stream omitted>'
                elif any(t in ct_lower for t in _SKIPPED_CONTENT_TYPES):
                    response_data['body'] = f'<{content_type} asset omitted>'
                else:
                    body_bytes = await response.body()
                    response_data['body'] = _truncate_body(body_bytes, content_type)
            except Exception as e:
                response_data['error'] = str(e)

            self._ses_responses.append(response_data)
        except Exception:
            pass

    async def _on_request_finished(self, request) -> None:
        try:
            response = await request.response()
            if not response:
                return
            for req in self._ses_requests:
                if req['url'] == request.url:
                    req['completed'] = True
                    break
        except Exception:
            pass
