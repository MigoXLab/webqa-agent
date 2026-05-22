"""Tests for ``features.cookies.cdp_client``.

Uses a real TCP server in a thread to exercise RFC 6455 framing end-to-end:
the plan's completeness audit flagged hand-rolled WebSocket clients as the
highest implementation-bug surface, so this test targets the framing
semantics directly (masking, 3 length encodings, Sec-WebSocket-Accept,
ping/pong, close frame, fragmentation, JSON error handling).
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import socket
import struct
import threading
import time

import pytest

from webqa_agent.executor.flash.features.cookies.cdp_client import (
    _WS_GUID, CDPCookieClient, CDPCookieError)

# ---------------------------------------------------------------------------
# Fake CDP server
# ---------------------------------------------------------------------------


class FakeCDPServer:
    """Listens on a free port; speaks HTTP ``/json/version`` + WS.

    The WS side supports a scripted response queue: each test pushes
    ``(opcode, bytes, ok_to_skip_mask_check=False)`` entries that the
    server emits in order when it receives a client frame. The test can
    also install a ``on_frame_received`` callback to inspect client frames
    for mask-bit / payload-XOR assertions.
    """

    def __init__(self) -> None:
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(('127.0.0.1', 0))
        self._srv.listen(4)
        self._srv.settimeout(5.0)
        self.port = self._srv.getsockname()[1]
        self.received_frames: list[tuple[int, bytes, int, bytes]] = []
        # Each turn = list of (opcode, payload) pairs emitted in one batch
        # in response to one client frame. Tests push turns in the order
        # the server will consume them.
        self._turns: list[list[tuple[int, bytes]]] = []
        self._reject_accept_key = False
        self._reply_non_200_to_json = False
        self._omit_ws_url = False
        self._serve_thread: threading.Thread | None = None

    # ---- scripting -------------------------------------------------------

    def script_reply(self, opcode: int, data: bytes) -> None:
        """Schedule a single-frame turn."""
        self._turns.append([(opcode, data)])

    def script_text_response(self, obj: dict) -> None:
        self.script_reply(0x1, json.dumps(obj).encode())

    def script_bundle(self, frames: list[tuple]) -> None:
        """Schedule a multi-frame turn emitted atomically in one batch.

        Each frame is ``(opcode, payload)`` (FIN=1 implied) or
        ``(opcode, payload, fin)`` for fragmentation tests.
        """
        self._turns.append(list(frames))

    def reject_accept_key(self) -> None:
        self._reject_accept_key = True

    def reply_non_200_to_json(self) -> None:
        self._reply_non_200_to_json = True

    def omit_ws_url_from_json(self) -> None:
        self._omit_ws_url = True

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        self._serve_thread = threading.Thread(target=self._serve, daemon=True)
        self._serve_thread.start()

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._srv.close()
        if self._serve_thread is not None:
            self._serve_thread.join(timeout=2.0)

    # ---- server loop -----------------------------------------------------

    def _serve(self) -> None:
        try:
            while True:
                try:
                    conn, _addr = self._srv.accept()
                except (OSError, socket.timeout):
                    return
                conn.settimeout(5.0)
                try:
                    self._handle_one(conn)
                except (OSError, ConnectionError, CDPCookieError):
                    pass
                finally:
                    with contextlib.suppress(OSError):
                        conn.close()
        except OSError:
            return

    def _handle_one(self, conn: socket.socket) -> None:
        # Read one HTTP request line + headers.
        data = b''
        while b'\r\n\r\n' not in data:
            chunk = conn.recv(4096)
            if not chunk:
                return
            data += chunk
        request_line = data.split(b'\r\n', 1)[0]
        if request_line.startswith(b'GET /json/version'):
            self._reply_json_version(conn)
            return
        # Otherwise: assume WS upgrade.
        headers = _parse_http_headers(data)
        client_key = headers.get('sec-websocket-key', '')
        if self._reject_accept_key:
            accept_key = 'WRONG_KEY_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
        else:
            accept_key = base64.b64encode(
                hashlib.sha1((client_key + _WS_GUID).encode()).digest()
            ).decode()
        resp = (
            'HTTP/1.1 101 Switching Protocols\r\n'
            'Upgrade: websocket\r\nConnection: Upgrade\r\n'
            f'Sec-WebSocket-Accept: {accept_key}\r\n\r\n'
        ).encode()
        conn.sendall(resp)
        self._ws_loop(conn)

    def _reply_json_version(self, conn: socket.socket) -> None:
        if self._reply_non_200_to_json:
            body = b'nope'
            status = 'HTTP/1.1 500 Internal Server Error'
        else:
            obj = {'Browser': 'Chrome/1.2.3', 'Protocol-Version': '1.3'}
            if not self._omit_ws_url:
                obj['webSocketDebuggerUrl'] = (
                    f'ws://127.0.0.1:{self.port}/devtools/browser/aaa-bbb')
            body = json.dumps(obj).encode()
            status = 'HTTP/1.1 200 OK'
        resp = (
            f'{status}\r\nContent-Type: application/json\r\n'
            f'Content-Length: {len(body)}\r\n\r\n'
        ).encode() + body
        conn.sendall(resp)

    def _ws_loop(self, conn: socket.socket) -> None:
        """Pop one turn per received client frame and emit its frames.

        Matches real CDP semantics: the server emits a response (or a small
        batch of interleaved events + response) only when the client
        speaks. Tests that need server-initiated chains (ping → pong →
        text) script each server→client burst as a separate turn.
        """
        while True:
            frame = _recv_ws_frame(conn)
            if frame is None:
                return
            opcode, fin, masked, mask_key, payload = frame
            self.received_frames.append((opcode, mask_key, fin, payload))
            if opcode == 0x8:
                return
            if self._turns:
                turn = self._turns.pop(0)
                close_emitted = False
                for entry in turn:
                    if len(entry) == 3:
                        out_op, out_payload, out_fin = entry
                    else:
                        out_op, out_payload = entry
                        out_fin = True
                    conn.sendall(
                        _build_server_frame(out_op, out_payload, fin=out_fin))
                    if out_op == 0x8:
                        close_emitted = True
                        break
                if close_emitted:
                    # Brief grace window for the client's close-echo so the
                    # test can assert it was sent before the server exits.
                    try:
                        echo = _recv_ws_frame(conn)
                    except (OSError, ConnectionError):
                        echo = None
                    if echo is not None:
                        e_op, _e_fin, _e_m, e_mk, e_p = echo
                        self.received_frames.append((e_op, e_mk, _e_fin, e_p))
                    return


# ---------------------------------------------------------------------------
# Low-level framing helpers for the fake server
# ---------------------------------------------------------------------------


def _parse_http_headers(raw: bytes) -> dict:
    headers = {}
    lines = raw.split(b'\r\n\r\n', 1)[0].split(b'\r\n')[1:]
    for line in lines:
        if b':' in line:
            k, _, v = line.partition(b':')
            headers[k.decode().strip().lower()] = v.decode().strip()
    return headers


def _recv_ws_frame(sock: socket.socket):
    header = _recv_all(sock, 2)
    if not header:
        return None
    b0, b1 = header
    fin = bool(b0 & 0x80)
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    length = b1 & 0x7F
    if length == 126:
        length = struct.unpack('!H', _recv_all(sock, 2))[0]
    elif length == 127:
        length = struct.unpack('!Q', _recv_all(sock, 8))[0]
    mask_key = _recv_all(sock, 4) if masked else b''
    masked_payload = _recv_all(sock, length) if length else b''
    if masked:
        payload = bytes(
            b ^ mask_key[i % 4] for i, b in enumerate(masked_payload))
    else:
        payload = masked_payload
    return opcode, fin, masked, mask_key, payload


def _recv_all(sock: socket.socket, n: int) -> bytes:
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return buf
        buf += chunk
    return buf


def _build_server_frame(opcode: int, payload: bytes, *, fin: bool = True) -> bytes:
    """Server→client frame (unmasked per RFC 6455)."""
    first = (0x80 if fin else 0x00) | opcode
    length = len(payload)
    if length <= 125:
        return bytes([first, length]) + payload
    if length <= 0xFFFF:
        return bytes([first, 126]) + struct.pack('!H', length) + payload
    return bytes([first, 127]) + struct.pack('!Q', length) + payload


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def server():
    s = FakeCDPServer()
    s.start()
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Discovery / handshake
# ---------------------------------------------------------------------------


def test_connect_succeeds_with_good_handshake(server):
    c = CDPCookieClient(server.port, timeout=2.0)
    c.connect()
    c.close()


def test_non_200_from_json_version_raises(server):
    server.reply_non_200_to_json()
    c = CDPCookieClient(server.port, timeout=2.0)
    with pytest.raises(CDPCookieError, match='HTTP 500'):
        c.connect()


def test_missing_ws_url_raises(server):
    server.omit_ws_url_from_json()
    c = CDPCookieClient(server.port, timeout=2.0)
    with pytest.raises(CDPCookieError, match='webSocketDebuggerUrl'):
        c.connect()


def test_bad_accept_key_raises(server):
    server.reject_accept_key()
    c = CDPCookieClient(server.port, timeout=2.0)
    with pytest.raises(CDPCookieError, match='Sec-WebSocket-Accept'):
        c.connect()


def test_connection_refused_raises():
    # 1-byte port that's guaranteed free-ish — use 1 and expect refused.
    c = CDPCookieClient(port=1, timeout=1.0)
    with pytest.raises(CDPCookieError):
        c.connect()


# ---------------------------------------------------------------------------
# RFC 6455 client framing
# ---------------------------------------------------------------------------


def test_client_frames_are_masked(server):
    server.script_text_response({'id': 1, 'result': {}})
    c = CDPCookieClient(server.port, timeout=2.0)
    c.connect()
    try:
        c.clear_cookies()
    finally:
        c.close()

    assert server.received_frames, 'server never received a frame'
    opcode, mask_key, fin, payload = server.received_frames[0]
    assert opcode == 0x1
    assert len(mask_key) == 4, 'client frame must carry a 4-byte mask'
    # The framing helper already unmasked it to reconstruct payload;
    # just make sure the body is the JSON-RPC we sent.
    decoded = json.loads(payload)
    assert decoded['method'] == 'Storage.clearCookies'
    assert decoded['id'] == 1


def test_payload_length_encoding_short(server):
    """≤125 bytes uses the 7-bit length form."""
    server.script_text_response({'id': 1, 'result': {}})
    c = CDPCookieClient(server.port, timeout=2.0)
    c.connect()
    try:
        c.set_cookies([{'name': 'a', 'value': 'b'}])
    finally:
        c.close()
    opcode, _, _, payload = server.received_frames[0]
    assert opcode == 0x1
    assert len(payload) <= 125


def test_payload_length_encoding_medium(server):
    """>125 bytes triggers 16-bit extended length."""
    server.script_text_response({'id': 1, 'result': {}})
    c = CDPCookieClient(server.port, timeout=2.0)
    c.connect()
    long_cookies = [
        {'name': f'k{i}', 'value': 'x' * 50} for i in range(10)
    ]
    try:
        c.set_cookies(long_cookies)
    finally:
        c.close()
    opcode, _, _, payload = server.received_frames[0]
    assert opcode == 0x1
    assert len(payload) > 125
    assert len(payload) <= 0xFFFF


# ---------------------------------------------------------------------------
# Server → client framing
# ---------------------------------------------------------------------------


def test_server_fragmented_response_assembled(server):
    """Continuation frames (FIN=0) must be assembled before JSON parse."""
    body = json.dumps({'id': 1, 'result': {'ok': True}}).encode()
    chunk = max(1, len(body) // 3)
    server.script_bundle([
        (0x1, body[:chunk], False),               # text, FIN=0
        (0x0, body[chunk:2 * chunk], False),      # cont, FIN=0
        (0x0, body[2 * chunk:], True),            # cont, FIN=1
    ])

    c = CDPCookieClient(server.port, timeout=2.0)
    c.connect()
    try:
        c.clear_cookies()  # success == assembled JSON parsed
    finally:
        c.close()


def test_ping_frame_echoed_as_pong(server):
    """Server ping (opcode 0x9) must trigger a client pong then loop waits."""
    # Turn 1 fires when client sends RPC: server emits a ping.
    # Turn 2 fires when client sends pong: server emits the real response.
    server.script_reply(0x9, b'ping-payload')
    server.script_text_response({'id': 1, 'result': {}})
    c = CDPCookieClient(server.port, timeout=2.0)
    c.connect()
    try:
        c.clear_cookies()  # would hang if ping wasn't handled
    finally:
        c.close()

    opcodes = [f[0] for f in server.received_frames]
    assert 0x1 in opcodes          # original RPC
    assert 0xA in opcodes          # pong echo


def test_close_frame_raises_and_echoes(server):
    server.script_reply(0x8, b'')
    c = CDPCookieClient(server.port, timeout=2.0)
    c.connect()
    with pytest.raises(CDPCookieError, match='closed connection'):
        c.clear_cookies()
    # Client echoed a close back; wait briefly for server thread to
    # consume it (separate thread race).
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if any(f[0] == 0x8 for f in server.received_frames):
            break
        time.sleep(0.01)
    opcodes = [f[0] for f in server.received_frames]
    assert 0x8 in opcodes


def test_interleaved_event_with_wrong_id_skipped(server):
    """Events interleaving with responses (no/mismatched ``id``) must be
    skipped."""
    server.script_bundle([
        (0x1, json.dumps(
            {'method': 'Network.requestWillBeSent', 'params': {}}).encode()),
        (0x1, json.dumps({'id': 999, 'result': {}}).encode()),  # wrong id
        (0x1, json.dumps({'id': 1, 'result': {}}).encode()),    # real
    ])
    c = CDPCookieClient(server.port, timeout=2.0)
    c.connect()
    try:
        c.clear_cookies()
    finally:
        c.close()


def test_malformed_json_response_raises_cdp_error(server):
    server.script_reply(0x1, b'not-json!!!')
    c = CDPCookieClient(server.port, timeout=2.0)
    c.connect()
    with pytest.raises(CDPCookieError, match='malformed JSON'):
        c.clear_cookies()


def test_non_object_json_raises_cdp_error(server):
    server.script_reply(0x1, b'[1,2,3]')
    c = CDPCookieClient(server.port, timeout=2.0)
    c.connect()
    with pytest.raises(CDPCookieError, match='non-object'):
        c.clear_cookies()


def test_cdp_error_response_sanitized_no_cookie_message(server):
    """[s4] CDP error message (may contain cookie name) must be dropped; only
    code kept."""
    server.script_text_response({
        'id': 1,
        'error': {'code': -32602,
                  'message': 'rejected cookie uaa-token value ...'},
    })
    c = CDPCookieClient(server.port, timeout=2.0)
    c.connect()
    with pytest.raises(CDPCookieError) as exc_info:
        c.clear_cookies()
    s = str(exc_info.value)
    assert 'code=-32602' in s
    assert 'uaa-token' not in s
    assert 'rejected cookie' not in s


def test_response_without_result_or_error_returns_empty(server):
    """Protocol violation tolerated — empty dict returned."""
    server.script_text_response({'id': 1})
    c = CDPCookieClient(server.port, timeout=2.0)
    c.connect()
    try:
        # clear_cookies doesn't inspect result; just needs no exception.
        c.clear_cookies()
    finally:
        c.close()


def test_set_cookies_empty_list_is_noop(server):
    """No ``Storage.setCookies`` call when no valid entries."""
    c = CDPCookieClient(server.port, timeout=2.0)
    c.connect()
    try:
        c.set_cookies([])
        c.set_cookies([{'name': 'x'}])          # missing value
        c.set_cookies([{'value': 'x'}])          # missing name
    finally:
        c.close()
    # No frames sent at all because no RPC call happened.
    assert not server.received_frames


def test_clear_and_set_in_sequence(server):
    # clear_and_set sends two RPCs → schedule two single-frame turns.
    server.script_text_response({'id': 1, 'result': {}})
    server.script_text_response({'id': 2, 'result': {}})
    c = CDPCookieClient(server.port, timeout=2.0)
    c.connect()
    try:
        c.clear_and_set([{'name': 'a', 'value': 'b'}])
    finally:
        c.close()
    opcodes = [f[0] for f in server.received_frames]
    # Two client RPC frames (both text).
    assert opcodes == [0x1, 0x1]

    methods = []
    for _op, _mask, _fin, payload in server.received_frames:
        methods.append(json.loads(payload)['method'])
    assert methods == ['Storage.clearCookies', 'Storage.setCookies']
