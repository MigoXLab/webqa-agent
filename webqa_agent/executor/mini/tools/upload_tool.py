"""Direct-CDP file upload tool — fallback for chrome-devtools-mcp
``upload_file``.

The standard ``mcp__browser__upload_file`` works by clicking the control
identified by ``uid`` from the latest accessibility snapshot and capturing the
resulting native file chooser. When the file ``<input>`` is hidden, the
trigger is not exposed in the a11y tree, or the page uses a custom upload
flow, that path fails.

This tool bypasses the chooser entirely: connects to the same Chrome instance
over CDP, locates the file input with a CSS selector, and calls
``DOM.setFileInputFiles`` to assign files directly on the element.

Usage by the agent::

    cdp_upload_file(file_path="/abs/path/to/file.pdf")
    cdp_upload_file(file_path="/abs/path/to/file.pdf",
                    selector="div.upload-area input[type='file']")

Limitations (current revision):
- Looks in the top frame only — iframe traversal is not yet implemented.
- ``file_path`` must be absolute and readable by the Chrome process.
- One file per call (``DOM.setFileInputFiles`` supports lists; exposed when
  agents actually need multi-file).
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import logging
import os
import socket
import struct
from pathlib import Path
from typing import Any

from ..core.tool import Tool, ToolResult

_log = logging.getLogger('cc_mini.upload')

_WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
_OP_TEXT = 0x1
_OP_CLOSE = 0x8
_OP_PING = 0x9
_OP_PONG = 0xA

_DEFAULT_TIMEOUT = 10.0
# Hosts CDP debug HTTP/WS endpoint — kept loopback for the same reason
# `--remote-debugging-address=127.0.0.1` is hardcoded in runner._default_browser_mcp.
_CDP_HOST = '127.0.0.1'


class _CDPError(Exception):
    """Raised on any CDP transport or command failure."""


class _PageCDPClient:
    """Minimal CDP-over-WebSocket client targeting a single page.

    Independent of the cookies CDPCookieClient because that one binds to the
    browser-level ``/json/version`` endpoint, whereas DOM commands require a
    page-level target from ``/json/list``.
    """

    def __init__(
        self,
        port: int,
        host: str = _CDP_HOST,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._req_id = 0

    # -------------------------------------------------------- target discovery

    def list_page_targets(self) -> list[dict]:
        """Return all page-type targets reported by ``/json/list``."""
        conn = http.client.HTTPConnection(
            self._host, self._port, timeout=self._timeout,
        )
        try:
            conn.request('GET', '/json/list')
            resp = conn.getresponse()
            if resp.status != 200:
                raise _CDPError(f'/json/list HTTP {resp.status}')
            body = resp.read()
        except OSError as exc:
            raise _CDPError(f'CDP discovery failed: {exc}') from exc
        finally:
            conn.close()
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise _CDPError(f'/json/list invalid JSON: {exc}') from exc
        if not isinstance(data, list):
            raise _CDPError('/json/list returned non-array payload')
        return [t for t in data if isinstance(t, dict) and t.get('type') == 'page']

    # -------------------------------------------------------- lifecycle

    def connect(self, ws_url: str) -> None:
        host, port, path = self._parse_ws_url(ws_url)
        nonce = base64.b64encode(os.urandom(16)).decode()
        expected_accept = base64.b64encode(
            hashlib.sha1((nonce + _WS_GUID).encode()).digest(),
        ).decode()
        try:
            self._sock = socket.create_connection(
                (host, port), timeout=self._timeout,
            )
        except OSError as exc:
            raise _CDPError(f'WS TCP connect failed: {exc}') from exc

        req = (
            f'GET /{path} HTTP/1.1\r\n'
            f'Host: {host}:{port}\r\n'
            f'Upgrade: websocket\r\n'
            f'Connection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {nonce}\r\n'
            f'Sec-WebSocket-Version: 13\r\n\r\n'
        ).encode()
        try:
            self._sock.sendall(req)
            resp = self._recv_until(b'\r\n\r\n')
        except OSError as exc:
            self.close()
            raise _CDPError(f'WS handshake send/recv failed: {exc}') from exc

        status_line = resp.split(b'\r\n', 1)[0]
        if b'101 ' not in status_line:
            self.close()
            raise _CDPError(f'WS upgrade failed: {status_line!r}')
        if expected_accept.encode() not in resp:
            self.close()
            raise _CDPError('Sec-WebSocket-Accept mismatch')

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    # -------------------------------------------------------- JSON-RPC

    def call(self, method: str, params: dict | None = None) -> dict:
        if self._sock is None:
            raise _CDPError('not connected')
        self._req_id += 1
        rpc_id = self._req_id
        payload = json.dumps(
            {'id': rpc_id, 'method': method, 'params': params or {}},
        ).encode()
        self._send_masked(_OP_TEXT, payload)

        while True:
            opcode, data = self._recv_frame()
            if opcode == _OP_CLOSE:
                try:
                    self._send_masked(_OP_CLOSE, b'')
                except OSError:
                    pass
                raise _CDPError('server closed connection mid-call')
            if opcode == _OP_PING:
                try:
                    self._send_masked(_OP_PONG, data)
                except OSError:
                    pass
                continue
            if opcode != _OP_TEXT:
                continue
            try:
                resp = json.loads(data)
            except json.JSONDecodeError as exc:
                raise _CDPError(f'malformed JSON from CDP: {exc}') from exc
            if not isinstance(resp, dict):
                raise _CDPError('non-object JSON from CDP')
            if resp.get('id') != rpc_id:
                # Skip event pushes interleaved with the response.
                continue
            err = resp.get('error')
            if err:
                code = err.get('code') if isinstance(err, dict) else None
                msg = err.get('message') if isinstance(err, dict) else ''
                raise _CDPError(f'CDP command rejected (code={code}): {msg}')
            return resp.get('result') or {}

    # -------------------------------------------------------- WS framing

    @staticmethod
    def _parse_ws_url(ws_url: str) -> tuple[str, int, str]:
        if not ws_url.startswith('ws://'):
            raise _CDPError(f'unsupported WS URL scheme: {ws_url!r}')
        _, _, rest = ws_url.partition('ws://')
        authority, _, path = rest.partition('/')
        host_part, _, port_part = authority.partition(':')
        try:
            port = int(port_part) if port_part else 80
        except ValueError as exc:
            raise _CDPError(f'invalid WS port: {port_part!r}') from exc
        return host_part, port, path

    def _send_masked(self, opcode: int, payload: bytes) -> None:
        if self._sock is None:
            raise _CDPError('not connected')
        header = bytes([0x80 | opcode])
        length = len(payload)
        if length <= 125:
            header += bytes([0x80 | length])
        elif length <= 0xFFFF:
            header += bytes([0x80 | 126]) + struct.pack('!H', length)
        else:
            header += bytes([0x80 | 127]) + struct.pack('!Q', length)
        mask_key = os.urandom(4)
        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        try:
            self._sock.sendall(header + mask_key + masked)
        except OSError as exc:
            raise _CDPError(f'WS send failed: {exc}') from exc

    def _recv_frame(self) -> tuple[int, bytes]:
        data = b''
        first_opcode: int | None = None
        while True:
            b0, b1 = self._recv_exact(2)
            fin = b0 & 0x80
            opcode = b0 & 0x0F
            if opcode == 0x0:
                if first_opcode is None:
                    raise _CDPError('continuation frame without initial opcode')
            else:
                if first_opcode is None:
                    first_opcode = opcode
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack('!H', self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack('!Q', self._recv_exact(8))[0]
            data += self._recv_exact(length) if length else b''
            if fin:
                assert first_opcode is not None
                return first_opcode, data

    def _recv_exact(self, n: int) -> bytes:
        buf = b''
        while len(buf) < n:
            try:
                chunk = self._sock.recv(n - len(buf))  # type: ignore[union-attr]
            except OSError as exc:
                raise _CDPError(f'WS recv failed: {exc}') from exc
            if not chunk:
                raise _CDPError('socket closed unexpectedly')
            buf += chunk
        return buf

    def _recv_until(self, sep: bytes) -> bytes:
        buf = b''
        while sep not in buf:
            try:
                chunk = self._sock.recv(4096)  # type: ignore[union-attr]
            except OSError as exc:
                raise _CDPError(f'WS handshake recv failed: {exc}') from exc
            if not chunk:
                raise _CDPError('socket closed during handshake')
            buf += chunk
        return buf


# Chrome-internal page URLs we never want to target — none of these host a real
# upload flow, so skipping them avoids accidentally setting files on a blank
# tab that the agent is not testing.
_INTERNAL_URL_PREFIXES = (
    'about:', 'chrome://', 'chrome-extension://', 'devtools://', 'edge://',
)


def _select_target(
    targets: list[dict], url_contains: str | None,
) -> dict | None:
    if not targets:
        return None
    if url_contains:
        needle = url_contains.lower()
        matches = [t for t in targets if needle in (t.get('url') or '').lower()]
        if matches:
            return matches[-1]
    non_internal = [
        t for t in targets
        if not (t.get('url') or '').startswith(_INTERNAL_URL_PREFIXES)
    ]
    pool = non_internal or targets
    return pool[-1]


_FIND_INPUT_JS = """(() => {
    const sel = %s;
    const isFileInput = (n) => n && n.tagName === 'INPUT' && n.type === 'file';
    let el = null;
    try { el = document.querySelector(sel); } catch (e) { el = null; }
    if (isFileInput(el)) return el;
    if (el) {
        const nested = el.querySelector('input[type="file"]');
        if (isFileInput(nested)) return nested;
    }
    return document.querySelector('input[type="file"]');
})()"""


class CDPUploadTool(Tool):
    """Direct-CDP file upload — bypasses the file-chooser intercept path.

    Lifecycle:
    1. ``bind_mcp(server, port)`` is called by ``runner.py`` after the MCP
       server is up. Stores the port for CDP discovery.
    2. ``execute()`` connects to the active page, sets files on the matched
       input, returns a tagged status string.
    """

    def __init__(self) -> None:
        self._mcp_server: Any | None = None
        self._port: int | None = None

    def bind_mcp(self, mcp_server: Any, port: int) -> None:
        if self._mcp_server is not None:
            _log.warning(
                'bind_mcp called twice on %s; ignoring second bind', self.name,
            )
            return
        self._mcp_server = mcp_server
        self._port = port

    # -------------------------------------------------------- Tool ABC

    @property
    def name(self) -> str:
        return 'cdp_upload_file'

    @property
    def description(self) -> str:
        return (
            'Upload a file to an <input type="file"> element on the current '
            'page. Do NOT click any upload trigger first — this tool sets '
            'the file directly via CDP, bypassing the native file chooser.\n\n'
            'How it works: connects to Chrome via DevTools Protocol, finds '
            'the <input type="file"> via a CSS selector (default: '
            '`input[type="file"]`), and calls `DOM.setFileInputFiles`. '
            'Top-frame only; iframe inputs are not yet supported.\n\n'
            'After a successful call, take_snapshot/take_screenshot to '
            'confirm the upload took effect (filename badge, preview, etc.).'
        )

    @property
    def input_schema(self) -> dict:
        return {
            'type': 'object',
            'properties': {
                'file_path': {
                    'type': 'string',
                    'description': (
                        'Absolute filesystem path to the file to upload. '
                        'Must exist and be readable by the Chrome process.'
                    ),
                },
                'selector': {
                    'type': 'string',
                    'description': (
                        'CSS selector for the <input type="file"> element. '
                        'Default: `input[type="file"]`. If the selector '
                        'matches a wrapper element instead of a real file '
                        'input, the tool searches inside it for one.'
                    ),
                },
                'target_url_contains': {
                    'type': 'string',
                    'description': (
                        'Optional. When several pages are open, prefer the '
                        'page whose URL contains this substring. Default: '
                        'most recently opened non-internal page.'
                    ),
                },
            },
            'required': ['file_path'],
        }

    def is_read_only(self) -> bool:
        return False

    def get_activity_description(self, **kwargs: Any) -> str | None:
        file_path = str(kwargs.get('file_path') or '')
        name = os.path.basename(file_path) or 'file'
        return f'Uploading {name} via CDP upload tool'

    # -------------------------------------------------------- execute

    def execute(self, **kwargs: Any) -> ToolResult:
        file_path = (kwargs.get('file_path') or '').strip()
        selector = (kwargs.get('selector') or 'input[type="file"]').strip()
        url_contains = (kwargs.get('target_url_contains') or '').strip() or None

        if not file_path:
            return ToolResult(
                content='[FAILURE: VALIDATION_ERROR: missing file_path argument]',
                is_error=True,
            )

        path = Path(file_path).expanduser()
        if not path.is_absolute():
            return ToolResult(
                content=(
                    f'[FAILURE: VALIDATION_ERROR: file_path must be absolute, '
                    f'got {file_path!r}]'
                ),
                is_error=True,
            )
        if not path.exists():
            return ToolResult(
                content=f'[FAILURE: VALIDATION_ERROR: file not found: {file_path!r}]',
                is_error=True,
            )
        if not path.is_file():
            return ToolResult(
                content=(
                    f'[FAILURE: VALIDATION_ERROR: not a regular file: '
                    f'{file_path!r}]'
                ),
                is_error=True,
            )

        if self._port is None:
            return ToolResult(
                content=(
                    '[CRITICAL_ERROR: cdp_upload_file not bound to a CDP port — '
                    'infrastructure error. Verify the browser MCP server is '
                    'launched with --chrome-arg=--remote-debugging-port=N.]'
                ),
                is_error=True,
            )

        client = _PageCDPClient(self._port)

        try:
            try:
                targets = client.list_page_targets()
            except _CDPError as exc:
                return ToolResult(
                    content=(
                        f'[FAILURE: NETWORK_ERROR: CDP discovery failed: {exc}. '
                        'The browser may not be up yet — try navigate_page first.]'
                    ),
                    is_error=True,
                )

            target = _select_target(targets, url_contains)
            if target is None:
                hint = (
                    f' matching {url_contains!r}' if url_contains else ''
                )
                return ToolResult(
                    content=(
                        f'[FAILURE: NAVIGATION_FAILED: no page target{hint} — '
                        'open the target page (navigate_page) before calling '
                        'cdp_upload_file.]'
                    ),
                    is_error=True,
                )

            ws_url = target.get('webSocketDebuggerUrl')
            if not isinstance(ws_url, str) or not ws_url:
                return ToolResult(
                    content=(
                        f'[FAILURE: NETWORK_ERROR: CDP target '
                        f'{target.get("id")!r} missing webSocketDebuggerUrl]'
                    ),
                    is_error=True,
                )

            try:
                client.connect(ws_url)
            except _CDPError as exc:
                return ToolResult(
                    content=(
                        f'[FAILURE: NETWORK_ERROR: CDP WebSocket connect '
                        f'failed: {exc}]'
                    ),
                    is_error=True,
                )

            expression = _FIND_INPUT_JS % json.dumps(selector)
            try:
                eval_result = client.call('Runtime.evaluate', {
                    'expression': expression,
                    'returnByValue': False,
                    'awaitPromise': False,
                    'includeCommandLineAPI': False,
                })
            except _CDPError as exc:
                return ToolResult(
                    content=(
                        f'[FAILURE: PAGE_CRASHED: Runtime.evaluate failed: {exc}]'
                    ),
                    is_error=True,
                )

            remote_obj = eval_result.get('result') or {}
            exception_details = eval_result.get('exceptionDetails')
            if exception_details:
                msg = (
                    exception_details.get('text')
                    or exception_details.get('exception', {}).get('description')
                    or 'unknown exception'
                )
                return ToolResult(
                    content=(
                        f'[FAILURE: VALIDATION_ERROR: selector {selector!r} '
                        f'raised an exception: {msg}]'
                    ),
                    is_error=True,
                )
            object_id = remote_obj.get('objectId')
            if remote_obj.get('subtype') == 'null' or not object_id:
                return ToolResult(
                    content=(
                        f'[FAILURE: ELEMENT_NOT_FOUND: no <input type="file"> '
                        f'matched selector {selector!r} on '
                        f'{target.get("url") or "?"!r}. Take a fresh '
                        'take_snapshot to confirm the input exists, then '
                        'retry with a more specific selector.]'
                    ),
                    is_error=True,
                )

            try:
                client.call('DOM.setFileInputFiles', {
                    'files': [str(path)],
                    'objectId': object_id,
                })
            except _CDPError as exc:
                return ToolResult(
                    content=(
                        f'[FAILURE: VALIDATION_ERROR: DOM.setFileInputFiles '
                        f'rejected: {exc}. Confirm the matched element is '
                        'actually a file input (not a wrapper).]'
                    ),
                    is_error=True,
                )

            return ToolResult(
                content=(
                    f'[SUCCESS] Uploaded {path.name} via CDP to file input '
                    f'on page {target.get("url") or "?"}. Re-snapshot or '
                    'screenshot to verify the upload took effect.'
                ),
            )
        finally:
            client.close()
