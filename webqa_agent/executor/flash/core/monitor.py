"""CDP-based browser monitor for capturing console + network during a case.

Connects directly to the Chrome DevTools Protocol WebSocket endpoint that
chrome-devtools-mcp already exposes, auto-attaches to all page targets in
flatten mode, and records:

* console: ``Runtime.consoleAPICalled``, ``Runtime.exceptionThrown`` and
  ``Log.entryAdded`` (the last is where 404-style resource errors surface).
* network: ``Network.requestWillBeSent`` / ``responseReceived`` /
  ``loadingFinished`` / ``loadingFailed``, with response body fetched on
  demand for HTML / JSON content-types. Request payloads CDP does not inline
  (``hasPostData=True``) are back-fetched via ``Network.getRequestPostData``
  so every body-bearing request keeps its payload.

Listening is fully passive — the agent's tool choices are unaffected. The
listener runs in its own thread; the engine main loop is never blocked.
"""
from __future__ import annotations

import http.client
import itertools
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from webqa_agent.browser.event_collector import IgnoreRuleMatcher

_log = logging.getLogger(__name__)

# Body content-types we will fetch via Network.getResponseBody. Anything else
# is replaced with a "<{mime} asset omitted>" placeholder so the JSON stays
# manageable for large pages with hundreds of asset loads.
_BODY_INCLUDE_PREFIXES = ('text/html', 'application/json')
_BODY_TRUNCATE_BYTES = 5120
_BODY_FETCH_TIMEOUT_S = 8.0
_CALL_TIMEOUT_S = 10.0
_DISCOVER_TIMEOUT_S = 5.0
# Ask Chrome to inline request bodies up to this size directly in
# ``Network.requestWillBeSent`` (default omits them, exposing only
# hasPostData=True). Bodies larger than this still fall back to
# ``Network.getRequestPostData``. 64 KiB comfortably covers API/JSON payloads
# while the stored value is truncated to ``max_body_bytes`` anyway.
_MAX_POST_DATA_SIZE = 65536
# How long ``start()`` waits for the first page target to attach + enable
# before returning. Best-effort: on timeout we proceed with the same coverage
# as before the wait existed.
_INITIAL_ATTACH_TIMEOUT_S = 2.0
# Per-session setup is dispatched off the CDP reader thread so synchronous
# ``client.call`` waits can receive their responses without deadlocking.
_SESSION_ENABLE_TIMEOUT_S = 2.0


def _is_event_stream(content_type: str) -> bool:
    """True for Server-Sent-Events responses (``text/event-stream``)."""
    return (content_type or '').lower().startswith('text/event-stream')


@dataclass
class _Waiter:
    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Any = None


class _CDPClient:
    """Minimal CDP-over-WebSocket JSON-RPC client.

    Uses flatten mode so messages for sub-sessions (page/iframe targets)
    travel over the same WebSocket with a ``sessionId`` envelope field.
    """

    def __init__(self, ws_url: str, on_event: Callable[[dict], None]) -> None:
        # Lazy import keeps the heavy dependency optional for users who
        # never enable the monitor.
        from websocket import WebSocketTimeoutException, create_connection

        # Chrome's CDP rejects WS handshakes that carry an Origin header it
        # doesn't allow (default policy = null origin only). websocket-client
        # injects ``Origin: http://<host>:<port>`` by default, which triggers
        # a 403. ``suppress_origin=True`` skips that header entirely.
        self._ws = create_connection(
            ws_url, timeout=_CALL_TIMEOUT_S, suppress_origin=True,
        )
        # The connect timeout above also becomes the per-recv socket timeout.
        # A passive listener spends most of its time idle between CDP events,
        # so recv() WILL exceed it during quiet gaps — that's expected, not a
        # disconnect. The read loop catches the resulting timeout (see
        # ``_read_loop``) and keeps waiting; this attribute lets it tell a
        # benign idle timeout apart from a real socket failure.
        self._timeout_exc = WebSocketTimeoutException
        self._send_lock = threading.Lock()
        self._waiters: dict[int, _Waiter] = {}
        self._waiters_lock = threading.Lock()
        self._id_counter = itertools.count(1)
        self._on_event = on_event
        self._alive = True
        self._reader_thread = threading.Thread(
            target=self._read_loop, name='cdp-monitor-reader', daemon=True,
        )
        self._reader_thread.start()

    def call(
        self, method: str, params: dict | None = None,
        *, session_id: str | None = None, timeout: float = _CALL_TIMEOUT_S,
    ) -> Any:
        if not self._alive:
            raise RuntimeError('CDP client is closed')
        msg_id = next(self._id_counter)
        waiter = _Waiter()
        with self._waiters_lock:
            self._waiters[msg_id] = waiter
        payload: dict[str, Any] = {'id': msg_id, 'method': method}
        if params:
            payload['params'] = params
        if session_id:
            payload['sessionId'] = session_id
        try:
            with self._send_lock:
                self._ws.send(json.dumps(payload))
        except Exception:
            with self._waiters_lock:
                self._waiters.pop(msg_id, None)
            raise
        if not waiter.event.wait(timeout):
            with self._waiters_lock:
                self._waiters.pop(msg_id, None)
            raise TimeoutError(f'CDP {method} timed out after {timeout}s')
        if waiter.error is not None:
            raise RuntimeError(f'CDP {method} error: {waiter.error}')
        return waiter.result

    def send_no_wait(
        self, method: str, params: dict | None = None,
        *, session_id: str | None = None,
    ) -> None:
        """Send a CDP request without waiting for the response.

        Used for setup calls (``Target.setAutoAttach``,
        ``Target.attachToTarget``) where the side effect — the browser
        starts auto-attaching and emitting ``Target.attachedToTarget``
        events — is what we care about, not the return value. Skipping
        the response wait avoids the ~10s ``setAutoAttach`` hang on the
        browser-level session that delays every case start.

        The CDP reader thread will receive the eventual reply and find no
        waiter registered, which is harmless (``_read_loop`` simply drops
        the message when the waiter dict has no entry).
        """
        if not self._alive:
            raise RuntimeError('CDP client is closed')
        msg_id = next(self._id_counter)
        payload: dict[str, Any] = {'id': msg_id, 'method': method}
        if params:
            payload['params'] = params
        if session_id:
            payload['sessionId'] = session_id
        with self._send_lock:
            self._ws.send(json.dumps(payload))

    def close(self) -> None:
        self._alive = False
        try:
            self._ws.close()
        except Exception:
            pass
        with self._waiters_lock:
            waiters = list(self._waiters.values())
            self._waiters.clear()
        for w in waiters:
            w.error = 'connection closed'
            w.event.set()
        self._reader_thread.join(timeout=1.0)

    def _read_loop(self) -> None:
        try:
            while self._alive:
                try:
                    raw = self._ws.recv()
                except self._timeout_exc:
                    # Idle gap longer than the socket timeout — NOT a
                    # disconnect. The connection is healthy; resume waiting for
                    # the next CDP event. (Missing this is what silently killed
                    # capture ~10s into the first quiet period.)
                    continue
                except Exception as exc:
                    # Only a deliberate close() should end the reader. Any other
                    # exit means the CDP socket dropped mid-case and capture
                    # silently stops — surface it loudly so it isn't mistaken
                    # for "no traffic happened".
                    if self._alive:
                        _log.warning(
                            'Monitor: CDP reader socket dropped — network/console '
                            'capture STOPS here (%s: %s)',
                            type(exc).__name__, exc,
                        )
                    break
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if 'id' in msg and 'method' not in msg:
                    with self._waiters_lock:
                        waiter = self._waiters.pop(msg['id'], None)
                    if waiter is not None:
                        if 'error' in msg:
                            waiter.error = msg['error']
                        else:
                            waiter.result = msg.get('result')
                        waiter.event.set()
                elif 'method' in msg:
                    try:
                        self._on_event(msg)
                    except Exception as exc:
                        _log.debug('CDP event handler error: %s', exc)
        finally:
            with self._waiters_lock:
                waiters = list(self._waiters.values())
                self._waiters.clear()
            for w in waiters:
                w.error = 'reader exited'
                w.event.set()


class MonitorListener:
    """Captures browser console + network throughout a case run.

    Output schema (returned by :meth:`stop`)::

        {
          "console": [{"msg": str, "location": {"url", "lineNumber", "columnNumber"}}, ...],
          "network": {
            "requests":        [{"url", "method", "payload", "completed", "failed"}, ...],
            "responses":       [{"url", "status", "method", "content_type", "payload", "body"}, ...],
            "failed_requests": [{"url", "method", "payload", "completed", "failed"}, ...]
          }
        }

    ``requests`` is ordered by first observation (``requestWillBeSent``).
    ``responses`` is ordered by completion (``loadingFinished``).
    ``failed_requests`` is ordered by ``loadingFailed`` arrival.
    """

    def __init__(
        self, *, host: str, port: int,
        max_body_bytes: int = _BODY_TRUNCATE_BYTES,
        ignore_rules: dict | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._max_body_bytes = max_body_bytes
        # ``ignore_rules`` mirrors the config shape consumed by the non-flash
        # path (``{'console': [...], 'network': [...]}``) so the same
        # config/test_config rules suppress noise here too.
        rules = ignore_rules or {}
        self._console_ignore_rules: list[dict] = rules.get('console') or []
        self._network_ignore_rules: list[dict] = rules.get('network') or []
        self._client: _CDPClient | None = None
        self._setup_pool: ThreadPoolExecutor | None = None
        self._body_pool: ThreadPoolExecutor | None = None
        self._lock = threading.RLock()
        self._console: list[dict] = []
        self._requests_order: list[str] = []
        self._requests: dict[str, dict] = {}
        self._responses_order: list[str] = []
        self._responses: dict[str, dict] = {}
        self._failed_order: list[str] = []
        self._failed: dict[str, dict] = {}
        self._enabled_sessions: set[str] = set()
        # Set by the reader thread once the first page target is attached and
        # its Network/Runtime/Log domains have been enabled. ``start()`` blocks
        # briefly on this so it doesn't return (letting the agent navigate)
        # before the initial page is actually being monitored.
        self._first_page_attached = threading.Event()
        self._started = False

    def start(self) -> None:
        ws_url = self._discover_browser_ws_url()
        self._client = _CDPClient(ws_url, on_event=self._dispatch_event)
        self._setup_pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix='cdp-setup',
        )
        self._body_pool = ThreadPoolExecutor(
            max_workers=3, thread_name_prefix='cdp-body',
        )
        # Fire-and-forget the browser-level setup. Waiting on
        # Target.setAutoAttach used to add ~10s of delay before every case
        # because chrome-devtools-mcp's CDP claim on the browser-level
        # endpoint leaves the response hung. The side effect (auto-attach to
        # future page targets + emit ``Target.attachedToTarget`` events) lands
        # regardless of whether we read the reply.
        try:
            self._client.send_no_wait(
                'Target.setAutoAttach',
                {
                    'autoAttach': True,
                    'waitForDebuggerOnStart': False,
                    'flatten': True,
                },
            )
        except Exception as exc:
            _log.warning('Monitor: Target.setAutoAttach send failed: %s', exc)
        # Pick up pages that already exist when we attached: we can't list
        # them without a synchronous response (Target.getTargets), so we
        # broadcast attachToTarget against the well-known "discover" pattern
        # via Target.setDiscoverTargets, which makes Chrome emit
        # Target.targetCreated for every existing target. Our event handler
        # already turns those into attaches without needing the list reply.
        try:
            self._client.send_no_wait(
                'Target.setDiscoverTargets',
                {'discover': True},
            )
        except Exception as exc:
            _log.debug(
                'Monitor: Target.setDiscoverTargets send failed: %s', exc,
            )
        # Don't return until the initial page target is attached + its domains
        # enabled, otherwise the agent's first navigation can race ahead of our
        # Network.enable and we miss the initial page-load traffic.
        if not self._first_page_attached.wait(timeout=_INITIAL_ATTACH_TIMEOUT_S):
            _log.debug(
                'Monitor: no page target attached within %.1fs of start',
                _INITIAL_ATTACH_TIMEOUT_S,
            )
        self._started = True
        _log.info('Monitor started against %s:%d', self._host, self._port)

    def stop(self) -> dict:
        if not self._started:
            return self._snapshot()
        if self._setup_pool is not None:
            self._setup_pool.shutdown(wait=True)
            self._setup_pool = None
        if self._body_pool is not None:
            self._body_pool.shutdown(wait=True)
            self._body_pool = None
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        self._started = False
        snap = self._snapshot()
        net = snap['network']
        _log.info(
            'Monitor stopped: %d request(s), %d response(s), %d failed, '
            '%d console',
            len(net['requests']), len(net['responses']),
            len(net['failed_requests']), len(snap['console']),
        )
        return snap

    def _snapshot(self) -> dict:
        with self._lock:
            return {
                'console': list(self._console),
                'network': {
                    'requests': [self._requests[k] for k in self._requests_order],
                    'responses': [self._responses[k] for k in self._responses_order],
                    'failed_requests': [self._failed[k] for k in self._failed_order],
                },
            }

    # ------------------------------------------------------------------ events

    def _discover_browser_ws_url(self) -> str:
        conn = http.client.HTTPConnection(
            self._host, self._port, timeout=_DISCOVER_TIMEOUT_S,
        )
        try:
            conn.request('GET', '/json/version')
            resp = conn.getresponse()
            body = resp.read()
        finally:
            conn.close()
        info = json.loads(body)
        ws = info.get('webSocketDebuggerUrl')
        if not ws:
            raise RuntimeError('CDP /json/version did not return webSocketDebuggerUrl')
        return ws

    def _dispatch_event(self, msg: dict) -> None:
        method = msg.get('method', '')
        params = msg.get('params') or {}
        session_id = msg.get('sessionId')
        if method == 'Target.attachedToTarget':
            self._handle_attached(params)
        elif method == 'Target.detachedFromTarget':
            self._handle_detached(params)
        elif method == 'Target.targetCreated':
            self._handle_target_created(params)
        elif method == 'Network.requestWillBeSent':
            self._handle_request_will_be_sent(params, session_id)
        elif method == 'Network.responseReceived':
            self._handle_response_received(params, session_id)
        elif method == 'Network.loadingFinished':
            self._handle_loading_finished(params, session_id)
        elif method == 'Network.loadingFailed':
            self._handle_loading_failed(params, session_id)
        elif method == 'Runtime.consoleAPICalled':
            self._handle_console_api(params)
        elif method == 'Runtime.exceptionThrown':
            self._handle_exception_thrown(params)
        elif method == 'Log.entryAdded':
            self._handle_log_entry(params)

    def _handle_attached(self, params: dict) -> None:
        info = params.get('targetInfo') or {}
        ttype = info.get('type')
        new_session = params.get('sessionId')
        if not new_session:
            return
        if ttype not in ('page', 'iframe'):
            # Workers / service workers don't produce the events we report.
            return
        if new_session in self._enabled_sessions:
            return
        self._enabled_sessions.add(new_session)
        client = self._client
        pool = self._setup_pool
        if client is None or pool is None:
            return
        try:
            pool.submit(
                self._enable_attached_session, new_session, ttype, info,
            )
        except RuntimeError:
            _log.debug(
                'Monitor: setup pool closed before session %s could be enabled',
                new_session,
            )

    def _enable_attached_session(
        self, session_id: str, ttype: str, info: dict,
    ) -> None:
        """Enable CDP domains for an attached target outside the reader
        thread."""
        client = self._client
        if client is None:
            return
        network_enabled = False
        try:
            client.call(
                'Network.enable',
                {'maxPostDataSize': _MAX_POST_DATA_SIZE},
                session_id=session_id,
                timeout=_SESSION_ENABLE_TIMEOUT_S,
            )
            network_enabled = True
            if ttype == 'page':
                self._first_page_attached.set()
            client.call(
                'Runtime.enable',
                session_id=session_id,
                timeout=_SESSION_ENABLE_TIMEOUT_S,
            )
            client.call(
                'Log.enable',
                session_id=session_id,
                timeout=_SESSION_ENABLE_TIMEOUT_S,
            )
            # Cascade auto-attach so nested iframes also get covered. This
            # setup is useful but not part of the first-page readiness gate.
            client.send_no_wait(
                'Target.setAutoAttach',
                {
                    'autoAttach': True,
                    'waitForDebuggerOnStart': False,
                    'flatten': True,
                },
                session_id=session_id,
            )
        except Exception as exc:
            _log.warning(
                'Monitor: enabling %s session %s failed: %s',
                ttype, session_id, exc,
            )
        else:
            _log.info(
                'Monitor: attached + enabled %s session %s (url=%s); '
                '%d session(s) live',
                ttype, session_id, (info.get('url') or '')[:80],
                len(self._enabled_sessions),
            )
        finally:
            # Runtime/Log failures should not make us miss first navigation
            # traffic once Network is active.
            if ttype == 'page' and network_enabled:
                self._first_page_attached.set()

    def _handle_detached(self, params: dict) -> None:
        """Log + forget a detached session.

        A detach on the page we were capturing (cross-process navigation, tab
        recycle, devtools client conflict) means its Network/Runtime/Log events
        stop arriving. We surface it so a mid-case capture gap is explained;
        ``Target.setAutoAttach`` should re-attach a replacement, which
        ``_handle_attached`` re-enables.
        """
        sid = params.get('sessionId')
        if not sid or sid not in self._enabled_sessions:
            return
        self._enabled_sessions.discard(sid)
        _log.warning(
            'Monitor: session %s detached — capture paused for it; '
            '%d session(s) still live', sid, len(self._enabled_sessions),
        )

    def _handle_target_created(self, params: dict) -> None:
        """Auto-attach to pre-existing targets emitted by setDiscoverTargets.

        ``Target.setAutoAttach`` only covers targets created **after** the
        call; ``Target.setDiscoverTargets`` makes Chrome enumerate existing
        ones via ``Target.targetCreated`` events. We attach to every page
        target we see here so the initial ``about:blank`` / first-navigation
        traffic also flows through our session subscription.
        """
        info = params.get('targetInfo') or {}
        ttype = info.get('type')
        target_id = info.get('targetId')
        if ttype not in ('page', 'iframe') or not target_id:
            return
        if info.get('attached'):
            return
        client = self._client
        if client is None:
            return
        try:
            client.send_no_wait(
                'Target.attachToTarget',
                {'targetId': target_id, 'flatten': True},
            )
        except Exception as exc:
            _log.debug(
                'Monitor: attachToTarget %s failed: %s', target_id, exc,
            )

    def _request_key(self, session_id: str | None, request_id: str) -> str:
        return f'{session_id or ""}:{request_id}'

    def _handle_request_will_be_sent(
        self, params: dict, session_id: str | None,
    ) -> None:
        request_id = params.get('requestId') or ''
        req = params.get('request') or {}
        url = req.get('url') or ''
        if not url or url.startswith('data:'):
            return
        method = req.get('method') or 'GET'
        post_data = req.get('postData')
        # CDP omits the inline postData for larger bodies (sendBeacon beacons,
        # file uploads, long prompts), exposing only ``hasPostData=True``. We
        # fetch those out-of-band below so every body-bearing request still
        # carries its payload.
        has_post_data = bool(req.get('hasPostData'))
        payload = post_data if post_data else None
        need_post_fetch = payload is None and has_post_data
        key = self._request_key(session_id, request_id)
        with self._lock:
            existing = self._requests.get(key)
            if existing is not None:
                # Redirect chains reuse the requestId; keep the latest URL.
                existing.update({
                    'url': url, 'method': method, 'payload': payload,
                })
            else:
                self._requests[key] = {
                    'url': url,
                    'method': method,
                    'payload': payload,
                    'completed': False,
                    'failed': False,
                }
                self._requests_order.append(key)
        if need_post_fetch:
            self._schedule_post_data_fetch(key, session_id, request_id)

    def _handle_response_received(
        self, params: dict, session_id: str | None,
    ) -> None:
        request_id = params.get('requestId') or ''
        resp = params.get('response') or {}
        url = resp.get('url') or ''
        if not url or url.startswith('data:'):
            return
        if IgnoreRuleMatcher.should_ignore_network(url, self._network_ignore_rules):
            return
        content_type = resp.get('mimeType') or ''
        # SSE / streaming responses often never reach loadingFinished while the
        # case is running, so seed the body placeholder up front.
        body = '<event-stream omitted>' if _is_event_stream(content_type) else ''
        key = self._request_key(session_id, request_id)
        with self._lock:
            req_record = self._requests.get(key) or {}
            method = req_record.get('method') or 'GET'
            payload = req_record.get('payload')
            self._responses[key] = {
                'url': url,
                'status': int(resp.get('status') or 0),
                'method': method,
                'content_type': content_type,
                'payload': payload,
                'body': body,
            }
            # Record on first observation (responseReceived) — not on
            # loadingFinished — so streaming / still-in-flight responses are
            # captured even when they never complete during the case.
            # loadingFinished later only flips ``completed`` and fills the body.
            if key not in self._responses_order:
                self._responses_order.append(key)

    def _should_fetch_body(self, content_type: str) -> bool:
        ct = (content_type or '').lower()
        return any(ct.startswith(p) for p in _BODY_INCLUDE_PREFIXES)

    def _handle_loading_finished(
        self, params: dict, session_id: str | None,
    ) -> None:
        request_id = params.get('requestId') or ''
        key = self._request_key(session_id, request_id)
        with self._lock:
            if key in self._requests:
                self._requests[key]['completed'] = True
            response = self._responses.get(key)
            if response is None:
                return
            content_type = response.get('content_type') or ''
            # Normally added at responseReceived; guard covers the rare case a
            # response arrives without a preceding responseReceived event.
            if key not in self._responses_order:
                self._responses_order.append(key)
        if _is_event_stream(content_type):
            # Body already set to '<event-stream omitted>'; don't overwrite or
            # attempt to fetch a (potentially unbounded) stream body.
            return
        if self._should_fetch_body(content_type):
            self._schedule_body_fetch(key, session_id, request_id, content_type)
        else:
            self._set_body_placeholder(key, content_type)

    def _set_body_placeholder(self, key: str, content_type: str) -> None:
        ct = (content_type or 'application/octet-stream').split(';')[0].strip() \
            or 'application/octet-stream'
        with self._lock:
            record = self._responses.get(key)
            if record is not None:
                record['body'] = f'<{ct} asset omitted>'

    def _schedule_body_fetch(
        self, key: str, session_id: str | None, request_id: str,
        content_type: str,
    ) -> None:
        pool = self._body_pool
        client = self._client
        if pool is None or client is None:
            return

        def _fetch() -> None:
            try:
                result = client.call(
                    'Network.getResponseBody',
                    {'requestId': request_id},
                    session_id=session_id,
                    timeout=_BODY_FETCH_TIMEOUT_S,
                )
            except Exception as exc:
                _log.debug(
                    'Monitor: getResponseBody failed for %s: %s',
                    request_id, exc,
                )
                # Leave body as empty string — downstream tools can still
                # render the entry, they just won't see content for this one.
                return
            if not isinstance(result, dict):
                return
            body = result.get('body') or ''
            if result.get('base64Encoded'):
                # Binary body — treat like other asset types.
                self._set_body_placeholder(key, content_type)
                return
            encoded = body.encode('utf-8')
            original_len = len(encoded)
            if original_len > self._max_body_bytes:
                truncated = encoded[:self._max_body_bytes].decode(
                    'utf-8', errors='ignore',
                )
                body = (
                    f'{truncated}\n... [body truncated to '
                    f'{self._max_body_bytes} bytes from {original_len}]'
                )
            with self._lock:
                record = self._responses.get(key)
                if record is not None:
                    record['body'] = body

        try:
            pool.submit(_fetch)
        except RuntimeError:
            # Pool already shut down (case finished); ignore.
            pass

    def _schedule_post_data_fetch(
        self, key: str, session_id: str | None, request_id: str,
    ) -> None:
        """Fetch a request body CDP did not inline (``hasPostData=True``).

        Runs on the body pool — never the reader thread — because
        ``client.call`` blocks on a reply the reader thread must deliver.
        """
        pool = self._body_pool
        client = self._client
        if pool is None or client is None:
            return

        def _fetch() -> None:
            try:
                result = client.call(
                    'Network.getRequestPostData',
                    {'requestId': request_id},
                    session_id=session_id,
                    timeout=_BODY_FETCH_TIMEOUT_S,
                )
            except Exception as exc:
                _log.debug(
                    'Monitor: getRequestPostData failed for %s: %s',
                    request_id, exc,
                )
                # Body exists but couldn't be retrieved (binary upload, evicted
                # from the buffer, ...). Record a marker so a body-bearing
                # request never reports an empty payload.
                self._set_payload(key, '<request body omitted>')
                return
            post_data = result.get('postData') if isinstance(result, dict) else None
            if not post_data:
                self._set_payload(key, '<request body omitted>')
                return
            self._set_payload(key, self._truncate_payload(post_data))

        try:
            pool.submit(_fetch)
        except RuntimeError:
            pass

    def _set_payload(self, key: str, payload: str) -> None:
        """Backfill a late-fetched payload onto every record for ``key``."""
        with self._lock:
            for store in (self._requests, self._responses, self._failed):
                record = store.get(key)
                if record is not None:
                    record['payload'] = payload

    def _truncate_payload(self, payload: str) -> str:
        encoded = payload.encode('utf-8')
        original_len = len(encoded)
        if original_len <= self._max_body_bytes:
            return payload
        truncated = encoded[:self._max_body_bytes].decode('utf-8', errors='ignore')
        return (
            f'{truncated}\n... [payload truncated to '
            f'{self._max_body_bytes} bytes from {original_len}]'
        )

    def _handle_loading_failed(
        self, params: dict, session_id: str | None,
    ) -> None:
        request_id = params.get('requestId') or ''
        key = self._request_key(session_id, request_id)
        with self._lock:
            record = self._requests.get(key)
            if record is None:
                return
            record['failed'] = True
            # Snapshot — failed list is its own ordered view.
            self._failed[key] = dict(record)
            if key not in self._failed_order:
                self._failed_order.append(key)

    def _handle_console_api(self, params: dict) -> None:
        # Only surface ``console.error`` calls. Info / log / warn / debug are
        # high-volume on modern SPAs (analytics SDKs, dev libraries) and drown
        # the report. The agreed schema is for *error* signals only.
        if params.get('type') != 'error':
            return
        args = params.get('args') or []
        text = ' '.join(_stringify_remote_object(a) for a in args)
        url, line, col = _location_from_stack(params.get('stackTrace'))
        self._append_console(text, url, line, col)

    def _handle_exception_thrown(self, params: dict) -> None:
        details = params.get('exceptionDetails') or {}
        text = details.get('text') or 'Uncaught exception'
        exc_obj = details.get('exception') or {}
        desc = exc_obj.get('description')
        if desc:
            text = f'{text}: {desc}'
        url = details.get('url') or ''
        line = int(details.get('lineNumber') or 0)
        col = int(details.get('columnNumber') or 0)
        if not url:
            url, line, col = _location_from_stack(details.get('stackTrace'))
        self._append_console(text, url, line, col)

    def _handle_log_entry(self, params: dict) -> None:
        entry = params.get('entry') or {}
        # Only error-level entries — this is where 404 / failed resource loads
        # surface (``Failed to load resource: the server responded with a
        # status of 404``). Warning-level browser logs are typically
        # deprecation notes and not what the user wants in the report.
        if (entry.get('level') or 'info') != 'error':
            return
        text = entry.get('text') or ''
        url = entry.get('url') or ''
        line = int(entry.get('lineNumber') or 0)
        col = 0
        self._append_console(text, url, line, col)

    def _append_console(self, msg: str, url: str, line: int, col: int) -> None:
        if IgnoreRuleMatcher.should_ignore_console(msg, self._console_ignore_rules):
            return
        entry = {
            'msg': msg,
            'location': {
                'url': url,
                'lineNumber': line,
                'columnNumber': col,
            },
        }
        with self._lock:
            self._console.append(entry)


def _stringify_remote_object(obj: Any) -> str:
    if not isinstance(obj, dict):
        return str(obj)
    if obj.get('type') == 'string':
        return str(obj.get('value', ''))
    if 'value' in obj and obj.get('type') not in ('object', 'function'):
        val = obj['value']
        return str(val) if val is not None else 'null'
    if 'description' in obj:
        return str(obj['description'])
    if 'unserializableValue' in obj:
        return str(obj['unserializableValue'])
    return str(obj.get('type') or '')


def _location_from_stack(stack_trace: Any) -> tuple[str, int, int]:
    if not isinstance(stack_trace, dict):
        return '', 0, 0
    frames = stack_trace.get('callFrames') or []
    if not frames:
        return '', 0, 0
    frame = frames[0]
    return (
        str(frame.get('url') or ''),
        int(frame.get('lineNumber') or 0),
        int(frame.get('columnNumber') or 0),
    )
