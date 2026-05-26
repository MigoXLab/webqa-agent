"""Bare CDP WebSocket client for cookie injection.

Coexists with chrome-devtools-mcp's Puppeteer connection — CDP allows
multiple concurrent clients per browser target.

RFC 6455 compliance notes (all three are non-obvious failure modes):
  * Client→server frames must be masked (§5.3) — Chrome silently closes
    unmasked connections.
  * ``Sec-WebSocket-Accept`` is verified (§4.1) — a misbehaving proxy can
    silently break out of protocol if unchecked.
  * Server→client CDP responses may use 16-bit or 64-bit length encodings
    (§5.2) for payloads over 125 bytes.

All failures raise :class:`CDPCookieError`. CDP command errors expose only
the numeric code — never the server message, which may contain cookie values.

Sync/blocking. Safe from any thread.
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
from datetime import datetime

log = logging.getLogger(__name__)

_WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
_VALID_SAMESITE = {'Strict', 'Lax', 'None'}


def _normalize_cookie(c: dict) -> dict:
    """Translate a caller-supplied cookie dict to CDP ``Network.CookieParam``.

    Key rules:
    * Only http(s) ``url`` values are kept; non-http schemes are dropped.
    * ``expires`` accepts epoch int/float (> 0) or ISO-8601 string; anything
      else is omitted (CDP requires a numeric epoch).
    * ``sameSite`` must be ``'Strict'``, ``'Lax'``, or ``'None'`` exactly
      (case-sensitive); lowercase or invalid values are dropped.
    * Unknown keys are dropped — CDP rejects extras.
    """
    out: dict = {'name': c['name'], 'value': c['value']}
    if c.get('domain'):
        out['domain'] = c['domain']
    url = c.get('url')
    if isinstance(url, str) and (
        url.startswith('http://') or url.startswith('https://')
    ):
        out['url'] = url
    out['path'] = c.get('path') or '/'
    if c.get('secure'):
        out['secure'] = True
    if c.get('httpOnly'):
        out['httpOnly'] = True
    ss = c.get('sameSite')
    if ss in _VALID_SAMESITE:
        out['sameSite'] = ss
    exp = c.get('expires')
    if isinstance(exp, bool):
        # bool is a subclass of int — True would become epoch 1.
        pass
    elif isinstance(exp, (int, float)) and exp > 0:
        out['expires'] = float(exp)
    elif isinstance(exp, str) and exp:
        try:
            out['expires'] = datetime.fromisoformat(
                exp.replace('Z', '+00:00')).timestamp()
        except ValueError:
            pass
    return out


_OP_CONT = 0x0
_OP_TEXT = 0x1
_OP_BINARY = 0x2
_OP_CLOSE = 0x8
_OP_PING = 0x9
_OP_PONG = 0xA


class CDPCookieError(Exception):
    """Raised on any connection, protocol, or CDP-level failure.

    Messages are sanitized — cookie names/values never appear.
    """


class CDPCookieClient:
    def __init__(
        self,
        port: int,
        host: str = '127.0.0.1',
        timeout: float = 10.0,
    ) -> None:
        self._port = port
        self._host = host
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._req_id = 0

    # -------------------------------------------------------- lifecycle

    def connect(self) -> None:
        """Discover the browser WS URL and perform the WebSocket upgrade."""
        ws_url = self._discover_ws_url()
        ws_host, ws_port, path = self._parse_ws_url(ws_url)

        nonce = base64.b64encode(os.urandom(16)).decode()
        expected_accept = base64.b64encode(
            hashlib.sha1((nonce + _WS_GUID).encode()).digest()).decode()

        try:
            self._sock = socket.create_connection(
                (ws_host, ws_port), timeout=self._timeout)
        except OSError as exc:
            raise CDPCookieError(f'WS TCP connect failed: {exc}') from exc

        req = (
            f'GET /{path} HTTP/1.1\r\n'
            f'Host: {ws_host}:{ws_port}\r\n'
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
            raise CDPCookieError(f'WS handshake send/recv failed: {exc}') from exc

        status_line = resp.split(b'\r\n', 1)[0]
        if b'101 ' not in status_line:
            self.close()
            raise CDPCookieError(f'WS upgrade failed: {status_line!r}')
        if expected_accept.encode() not in resp:
            self.close()
            raise CDPCookieError('Sec-WebSocket-Accept mismatch')

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    # -------------------------------------------------------- public API

    def set_cookies(self, cookies: list[dict]) -> None:
        """CDP ``Storage.setCookies``. Skips entries missing name or value.

        Empty-string values are preserved — some servers use them as deletion
        sentinels. Only ``None`` values or absent ``name`` are dropped.
        """
        params = [
            _normalize_cookie(c) for c in cookies
            if c.get('name') and c.get('value') is not None
        ]
        if params:
            self._call('Storage.setCookies', {'cookies': params})

    def clear_cookies(self) -> None:
        """CDP ``Storage.clearCookies``."""
        self._call('Storage.clearCookies', {})

    def clear_and_set(self, cookies: list[dict]) -> None:
        """Clear all cookies then set the new ones in a single WS session."""
        self.clear_cookies()
        self.set_cookies(cookies)

    # -------------------------------------------------------- internals

    def _discover_ws_url(self) -> str:
        h = http.client.HTTPConnection(
            self._host, self._port, timeout=self._timeout)
        try:
            h.request('GET', '/json/version')
            r = h.getresponse()
            if r.status != 200:
                raise CDPCookieError(
                    f'/json/version returned HTTP {r.status}')
            body = r.read()
        except OSError as exc:
            raise CDPCookieError(f'CDP discover failed: {exc}') from exc
        finally:
            h.close()
        try:
            return json.loads(body)['webSocketDebuggerUrl']
        except (KeyError, ValueError) as exc:
            raise CDPCookieError(
                f'CDP /json/version missing webSocketDebuggerUrl: {exc}'
            ) from exc

    @staticmethod
    def _parse_ws_url(ws_url: str) -> tuple[str, int, str]:
        if not ws_url.startswith('ws://'):
            raise CDPCookieError(f'unsupported WS URL scheme: {ws_url!r}')
        _, _, rest = ws_url.partition('ws://')
        authority, _, path = rest.partition('/')
        host_part, _, port_part = authority.partition(':')
        try:
            port = int(port_part) if port_part else 80
        except ValueError as exc:
            raise CDPCookieError(f'invalid WS port: {port_part!r}') from exc
        return host_part, port, path

    def _call(self, method: str, params: dict) -> dict:
        if self._sock is None:
            raise CDPCookieError('not connected')
        self._req_id += 1
        rpc_id = self._req_id
        payload = json.dumps(
            {'id': rpc_id, 'method': method, 'params': params}).encode()
        self._send_masked(_OP_TEXT, payload)

        while True:
            opcode, data = self._recv_frame()
            if opcode == _OP_CLOSE:
                try:
                    self._send_masked(_OP_CLOSE, b'')
                except OSError:
                    pass
                raise CDPCookieError('server closed connection mid-call')
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
                raise CDPCookieError(
                    f'malformed JSON from CDP: {exc}') from exc
            if not isinstance(resp, dict):
                raise CDPCookieError('non-object JSON from CDP')
            if resp.get('id') != rpc_id:
                # CDP event pushes interleave with responses — skip them.
                continue
            err = resp.get('error')
            if err:
                # Drop the server message (may contain cookie values); keep only code.
                code = err.get('code') if isinstance(err, dict) else None
                raise CDPCookieError(
                    f'CDP command rejected (code={code})')
            return resp.get('result') or {}

    def _send_masked(self, opcode: int, payload: bytes) -> None:
        if self._sock is None:
            raise CDPCookieError('not connected')
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
            raise CDPCookieError(f'WS send failed: {exc}') from exc

    def _recv_frame(self) -> tuple[int, bytes]:
        """Receive one logical frame, assembling continuation frames."""
        data = b''
        first_opcode: int | None = None
        while True:
            b0, b1 = self._recv_exact(2)
            fin = b0 & 0x80
            opcode = b0 & 0x0F
            if opcode == _OP_CONT:
                if first_opcode is None:
                    raise CDPCookieError(
                        'continuation frame without initial opcode')
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
                chunk = self._sock.recv(n - len(buf))
            except OSError as exc:
                raise CDPCookieError(f'WS recv failed: {exc}') from exc
            if not chunk:
                raise CDPCookieError('socket closed unexpectedly')
            buf += chunk
        return buf

    def _recv_until(self, sep: bytes) -> bytes:
        buf = b''
        while sep not in buf:
            try:
                chunk = self._sock.recv(4096)
            except OSError as exc:
                raise CDPCookieError(
                    f'WS handshake recv failed: {exc}') from exc
            if not chunk:
                raise CDPCookieError('socket closed during handshake')
            buf += chunk
        return buf
