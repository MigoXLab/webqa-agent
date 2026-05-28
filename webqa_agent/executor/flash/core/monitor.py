"""CDP-based browser monitor for capturing console + network during a case.

Connects directly to the Chrome DevTools Protocol WebSocket endpoint that
chrome-devtools-mcp already exposes, auto-attaches to all page targets in
flatten mode, and records:

* console: ``Runtime.consoleAPICalled``, ``Runtime.exceptionThrown`` and
  ``Log.entryAdded`` (the last is where 404-style resource errors surface).
* network: ``Network.requestWillBeSent`` / ``responseReceived`` /
  ``loadingFinished`` / ``loadingFailed``, with response body fetched on
  demand for HTML / JSON content-types.

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

_log = logging.getLogger(__name__)

# Body content-types we will fetch via Network.getResponseBody. Anything else
# is replaced with a "<{mime} asset omitted>" placeholder so the JSON stays
# manageable for large pages with hundreds of asset loads.
_BODY_INCLUDE_PREFIXES = ('text/html', 'application/json')
_BODY_TRUNCATE_BYTES = 5120
_BODY_FETCH_TIMEOUT_S = 8.0
_CALL_TIMEOUT_S = 10.0
_DISCOVER_TIMEOUT_S = 5.0


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
        from websocket import create_connection
        # Chrome's CDP rejects WS handshakes that carry an Origin header it
        # doesn't allow (default policy = null origin only). websocket-client
        # injects ``Origin: http://<host>:<port>`` by default, which triggers
        # a 403. ``suppress_origin=True`` skips that header entirely.
        self._ws = create_connection(
            ws_url, timeout=_CALL_TIMEOUT_S, suppress_origin=True,
        )
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
                except Exception:
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
    ) -> None:
        self._host = host
        self._port = port
        self._max_body_bytes = max_body_bytes
        self._client: _CDPClient | None = None
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
        self._started = False

    def start(self) -> None:
        ws_url = self._discover_browser_ws_url()
        self._client = _CDPClient(ws_url, on_event=self._dispatch_event)
        self._body_pool = ThreadPoolExecutor(
            max_workers=3, thread_name_prefix='cdp-body',
        )
        try:
            self._client.call(
                'Target.setAutoAttach',
                {
                    'autoAttach': True,
                    'waitForDebuggerOnStart': False,
                    'flatten': True,
                },
            )
        except Exception as exc:
            _log.warning('Monitor: Target.setAutoAttach failed: %s', exc)
        # Pick up pages that existed before we attached. setAutoAttach covers
        # future targets; targets created before our call need explicit attach.
        try:
            result = self._client.call('Target.getTargets')
            for t in (result or {}).get('targetInfos', []) or []:
                if t.get('type') in ('page', 'iframe') and not t.get('attached'):
                    try:
                        self._client.call(
                            'Target.attachToTarget',
                            {'targetId': t['targetId'], 'flatten': True},
                            timeout=_CALL_TIMEOUT_S,
                        )
                    except Exception as exc:
                        _log.debug(
                            'Monitor: attachToTarget %s failed: %s',
                            t.get('targetId'), exc,
                        )
        except Exception as exc:
            _log.debug('Monitor: Target.getTargets failed: %s', exc)
        self._started = True
        _log.info('Monitor started against %s:%d', self._host, self._port)

    def stop(self) -> dict:
        if not self._started:
            return self._snapshot()
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
        return self._snapshot()

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
        if client is None:
            return
        for method_name in ('Network.enable', 'Runtime.enable', 'Log.enable'):
            try:
                client.call(method_name, session_id=new_session, timeout=5.0)
            except Exception as exc:
                _log.debug(
                    'Monitor: enabling %s on session %s failed: %s',
                    method_name, new_session, exc,
                )
        # Cascade auto-attach so nested iframes also get covered.
        try:
            client.call(
                'Target.setAutoAttach',
                {
                    'autoAttach': True,
                    'waitForDebuggerOnStart': False,
                    'flatten': True,
                },
                session_id=new_session, timeout=5.0,
            )
        except Exception as exc:
            _log.debug(
                'Monitor: nested setAutoAttach on %s failed: %s', new_session, exc,
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
        payload = post_data if post_data else None
        key = self._request_key(session_id, request_id)
        with self._lock:
            existing = self._requests.get(key)
            if existing is not None:
                # Redirect chains reuse the requestId; keep the latest URL.
                existing.update({
                    'url': url, 'method': method, 'payload': payload,
                })
                return
            self._requests[key] = {
                'url': url,
                'method': method,
                'payload': payload,
                'completed': False,
                'failed': False,
            }
            self._requests_order.append(key)

    def _handle_response_received(
        self, params: dict, session_id: str | None,
    ) -> None:
        request_id = params.get('requestId') or ''
        resp = params.get('response') or {}
        url = resp.get('url') or ''
        if not url or url.startswith('data:'):
            return
        key = self._request_key(session_id, request_id)
        with self._lock:
            req_record = self._requests.get(key) or {}
            method = req_record.get('method') or 'GET'
            payload = req_record.get('payload')
            self._responses[key] = {
                'url': url,
                'status': int(resp.get('status') or 0),
                'method': method,
                'content_type': resp.get('mimeType') or '',
                'payload': payload,
                'body': '',
            }

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
            if key not in self._responses_order:
                self._responses_order.append(key)
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
