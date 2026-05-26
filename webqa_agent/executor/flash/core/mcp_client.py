"""Minimal MCP (Model Context Protocol) stdio client.

Speaks JSON-RPC 2.0 over newline-delimited UTF-8 JSON against a subprocess
launched via stdio. No dependency on the official `mcp` Python SDK.

Protocol version negotiated: 2025-06-18 (stable). Server may counter with a
different version; we honor it.

Concurrency model: engine's ThreadPoolExecutor can call `MCPTool.execute`
concurrently on the same MCPServer. Writer lock serializes stdin; responses
are demultiplexed by request id via a thread-safe waiter dict.

stderr MUST be drained in a separate thread — servers like chrome-devtools-mcp
are chatty on stderr, and a full pipe would stall the child process.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import logging
import os
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable

from .tool import Tool, ToolResult

_log = logging.getLogger('cc_mini.mcp')

# Known-benign stderr patterns from upstream MCP servers. Each pattern matches
# harmless diagnostic output that would otherwise flood the DEBUG log
# (hundreds of lines per run) without informing the user of anything
# actionable. The pipe is still drained — only the log emit is suppressed.
_BENIGN_STDERR_PATTERNS: tuple[re.Pattern[str], ...] = (
    # chrome-devtools-mcp: emitted whenever the DevTools protocol surfaces an
    # issue code the MCP server has no handler for (e.g. PerformanceIssue,
    # LowTextContrastIssue). Purely informational.
    re.compile(r'No handler registered for issue code '),
)


def _is_benign_stderr(line: str) -> bool:
    return any(p.search(line) for p in _BENIGN_STDERR_PATTERNS)


PROTOCOL_VERSION = '2025-06-18'
CLIENT_NAME = 'cc-mini'
CLIENT_VERSION = '0.1'
_TOOL_NAME_MAX = 64
_DEFAULT_CALL_TIMEOUT = 60.0
_DEFAULT_STARTUP_TIMEOUT = 20.0
_SHUTDOWN_STDIN_GRACE = 3.0
_SHUTDOWN_TERM_GRACE = 1.0

# (server_name, original_tool_name) tuples for read-only MCP tools whose
# backend serialises on a single page (chrome-devtools-mcp's renderer main
# thread). Putting them in the engine's parallel batch causes every waiter to
# share one 60s clock and time out together. The engine reads the per-instance
# `MCPTool.concurrent_safe` flag set in __init__ to keep them in sequential
# batches instead. Server-name scoped so a third-party MCP that happens to
# expose `take_screenshot` is not affected.
_HEAVY_READONLY_TOOLS: frozenset[tuple[str, str]] = frozenset({
    ('browser', 'take_snapshot'),
    ('browser', 'take_screenshot'),
})

# Read-only tool name tokens (chrome-devtools-mcp / playwright-mcp naming conventions).
# Used when the MCP server omits readOnlyHint to infer read-only semantics
# heuristically.  Matching is done on word boundaries (underscores, dashes,
# whitespace, camelCase) so tokens like "list" don't accidentally match write
# operations such as "blacklist" / "whitelist" / "allowlist".
_READONLY_NAME_TOKENS: frozenset[str] = frozenset({
    'snapshot',
    'screenshot',
    'inspect',
    'list',
    'get',
    'describe',
    'info',
    'status',
    'dump',
    'read',
    'fetch',
    'accessibility',
})

# Splits on underscores, dashes, whitespace, and camelCase boundaries.
_NAME_TOKEN_SPLIT_RE = re.compile(r'[_\-\s]+|(?<=[a-z])(?=[A-Z])')


def _is_likely_readonly_by_name(raw_tool_name: str) -> bool:
    """Heuristic: infer read-only semantics when the MCP server omits
    readOnlyHint. Tokenises the tool name and checks for a read-only keyword."""
    tokens = [tok.lower() for tok in _NAME_TOKEN_SPLIT_RE.split(raw_tool_name) if tok]
    return any(tok in _READONLY_NAME_TOKENS for tok in tokens)


class MCPError(Exception):
    """Raised on MCP-level protocol/transport errors."""


@dataclass
class _Waiter:
    event: threading.Event
    # Populated by reader before set(): either a JSON-RPC response dict or
    # an MCPError instance for transport-level failures.
    result: Any = None


class MCPServer:
    """One MCP stdio subprocess + its JSON-RPC client state."""

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self.name = name
        self._command = command
        self._args = list(args or [])
        self._env = env
        self._cwd = cwd

        self._proc: subprocess.Popen[bytes] | None = None
        self._stdin_lock = threading.Lock()
        self._waiters_lock = threading.Lock()
        self._waiters: dict[int, _Waiter] = {}
        self._id_counter = itertools.count(1)
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._alive = False
        self.negotiated_protocol_version: str | None = None
        self.tools: list[dict] = []
        self._recent_stderr: deque[str] = deque(maxlen=30)

    # ------------------------------------------------------------------ lifecycle

    def start(self, startup_timeout_s: float = _DEFAULT_STARTUP_TIMEOUT) -> None:
        """Spawn the subprocess, start reader threads, run
        initialize+tools/list.

        Raises MCPError if anything fails within startup_timeout_s.
        """
        cmd = [self._command] + self._args
        # Resolve command via PATH explicitly for a clearer error message than
        # Popen's generic FileNotFoundError.
        if shutil.which(self._command) is None and not os.path.isabs(self._command):
            raise MCPError(f'{self.name}: command not found on PATH: {self._command!r}')

        merged_env = None
        if self._env:
            merged_env = os.environ.copy()
            merged_env.update(self._env)

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self._cwd,
                env=merged_env,
                bufsize=0,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            raise MCPError(f'{self.name}: failed to spawn: {exc}') from exc

        self._alive = True
        self._reader_thread = threading.Thread(
            target=self._read_stdout, name=f'mcp-{self.name}-reader', daemon=True
        )
        self._reader_thread.start()
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, name=f'mcp-{self.name}-stderr', daemon=True
        )
        self._stderr_thread.start()

        try:
            self._initialize(startup_timeout_s)
            self.tools = self._list_tools(startup_timeout_s)
        except Exception:
            # Give the stderr drain thread a moment to collect remaining output.
            time.sleep(0.3)
            if self._recent_stderr:
                stderr_snippet = '\n'.join(self._recent_stderr)
                _log.warning(
                    '%s: server stderr before failure:\n%s', self.name, stderr_snippet,
                )
            self.shutdown()
            raise

    def shutdown(self) -> None:
        """Best-effort termination.

        Safe to call multiple times.
        """
        if self._proc is None:
            return

        self._alive = False
        # Wake anyone still waiting
        with self._waiters_lock:
            waiters = list(self._waiters.values())
            self._waiters.clear()
        for w in waiters:
            w.result = MCPError(f'{self.name}: server shutting down')
            w.event.set()

        proc = self._proc
        try:
            if proc.stdin and not proc.stdin.closed:
                try:
                    proc.stdin.close()
                except (OSError, BrokenPipeError):
                    pass
            try:
                proc.wait(timeout=_SHUTDOWN_STDIN_GRACE)
            except subprocess.TimeoutExpired:
                self._kill_process_group(proc, signal.SIGTERM)
                try:
                    proc.wait(timeout=_SHUTDOWN_TERM_GRACE)
                except subprocess.TimeoutExpired:
                    self._kill_process_group(proc, signal.SIGKILL)
                    try:
                        proc.wait(timeout=_SHUTDOWN_TERM_GRACE)
                    except subprocess.TimeoutExpired:
                        pass
        finally:
            self._proc = None

    @staticmethod
    def _kill_process_group(proc: subprocess.Popen[bytes], sig: int) -> None:
        """Send *sig* to the entire process group (MCP server + Chrome
        tree)."""
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                if sig == signal.SIGTERM:
                    proc.terminate()
                else:
                    proc.kill()
            except OSError:
                pass

    # ------------------------------------------------------------------ io threads

    def _read_stdout(self) -> None:
        assert self._proc and self._proc.stdout
        stdout = self._proc.stdout
        try:
            for raw in iter(stdout.readline, b''):
                if not raw:
                    break
                line = raw.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode('utf-8'))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    _log.warning('%s: bad JSON from server: %s', self.name, exc)
                    continue
                self._dispatch_message(msg)
        except Exception as exc:  # reader must never die silently
            _log.warning('%s: reader thread error: %s', self.name, exc)
        finally:
            # EOF: wake all remaining waiters
            with self._waiters_lock:
                waiters = list(self._waiters.values())
                self._waiters.clear()
            for w in waiters:
                w.result = MCPError(f'{self.name}: server closed connection')
                w.event.set()

    def _drain_stderr(self) -> None:
        assert self._proc and self._proc.stderr
        stderr = self._proc.stderr
        try:
            for raw in iter(stderr.readline, b''):
                if not raw:
                    break
                # Keep the pipe empty so the child process never blocks on a
                # full stderr buffer. Filter known-benign noise before
                # emitting — otherwise chrome-devtools-mcp fills the DEBUG
                # log with hundreds of "No handler registered for issue code"
                # messages per run (harmless DevTools-protocol warnings that
                # do not affect agent correctness).
                decoded = raw.rstrip().decode('utf-8', 'replace')
                if _is_benign_stderr(decoded):
                    continue
                self._recent_stderr.append(decoded)
                _log.debug('%s[stderr]: %s', self.name, decoded)
        except Exception:
            pass

    def _dispatch_message(self, msg: dict) -> None:
        msg_id = msg.get('id')
        method = msg.get('method')

        if method is not None and msg_id is not None:
            # Server-initiated request — we don't support any, reject politely.
            self._send_raw({
                'jsonrpc': '2.0',
                'id': msg_id,
                'error': {'code': -32601, 'message': f'Method not found: {method}'},
            })
            return

        if method is not None:
            # Notification from server — ignore.
            return

        if msg_id is None:
            _log.warning('%s: message without id or method: %s', self.name, msg)
            return

        with self._waiters_lock:
            waiter = self._waiters.pop(msg_id, None)
        if waiter is None:
            # Late response after timeout — drop silently.
            return
        waiter.result = msg
        waiter.event.set()

    # ------------------------------------------------------------------ rpc

    def _send_raw(self, payload: dict) -> None:
        """Write one JSON-RPC message.

        Serialized by stdin_lock.
        """
        if self._proc is None or self._proc.stdin is None:
            raise MCPError(f'{self.name}: not started')
        data = (json.dumps(payload, ensure_ascii=False) + '\n').encode('utf-8')
        with self._stdin_lock:
            try:
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
            except (OSError, BrokenPipeError) as exc:
                raise MCPError(f'{self.name}: stdin write failed: {exc}') from exc

    def _request(self, method: str, params: dict | None, timeout_s: float) -> dict:
        """Send a request and wait for its response.

        Raises MCPError on failure.
        """
        msg_id = next(self._id_counter)
        waiter = _Waiter(event=threading.Event())
        # Register waiter BEFORE writing to stdin so a fast response can't miss us.
        with self._waiters_lock:
            self._waiters[msg_id] = waiter

        payload: dict = {'jsonrpc': '2.0', 'id': msg_id, 'method': method}
        if params is not None:
            payload['params'] = params

        try:
            self._send_raw(payload)
        except MCPError:
            with self._waiters_lock:
                self._waiters.pop(msg_id, None)
            raise

        if not waiter.event.wait(timeout=timeout_s):
            with self._waiters_lock:
                self._waiters.pop(msg_id, None)
            # Tell the server to abandon the request so it stops occupying
            # the renderer's main thread.  Without this, an in-flight
            # locator.wait() in chrome-devtools-mcp keeps running past our
            # local timeout and the next call_tool queues behind it for
            # another full timeout window.  The MCP spec lets receivers
            # ignore the notification if the request has already finished,
            # so a late response racing this branch is harmless.
            try:
                self._send_notification(
                    'notifications/cancelled',
                    {
                        'requestId': msg_id,
                        'reason': f'client timeout after {timeout_s}s',
                    },
                )
            except Exception as cancel_exc:
                _log.debug(
                    '%s: failed to send cancellation for id=%s: %s',
                    self.name, msg_id, cancel_exc,
                )
            raise MCPError(f'{self.name}: {method} timed out after {timeout_s}s')

        result = waiter.result
        if isinstance(result, MCPError):
            raise result
        if not isinstance(result, dict):
            raise MCPError(f'{self.name}: unexpected response type: {type(result)!r}')
        if 'error' in result:
            err = result['error'] or {}
            raise MCPError(
                f"{self.name}: {method} error {err.get('code')}: {err.get('message')}"
            )
        return result.get('result') or {}

    def _send_notification(self, method: str, params: dict | None = None) -> None:
        payload: dict = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            payload['params'] = params
        self._send_raw(payload)

    # ------------------------------------------------------------------ protocol

    def _initialize(self, timeout_s: float) -> None:
        result = self._request(
            'initialize',
            {
                'protocolVersion': PROTOCOL_VERSION,
                'capabilities': {},
                'clientInfo': {'name': CLIENT_NAME, 'version': CLIENT_VERSION},
            },
            timeout_s=timeout_s,
        )
        self.negotiated_protocol_version = result.get('protocolVersion') or PROTOCOL_VERSION
        self._send_notification('notifications/initialized')

    def _list_tools(self, timeout_s: float) -> list[dict]:
        # Handle pagination via optional cursor field.
        tools: list[dict] = []
        cursor: str | None = None
        while True:
            params = {'cursor': cursor} if cursor else None
            result = self._request('tools/list', params, timeout_s=timeout_s)
            tools.extend(result.get('tools', []) or [])
            cursor = result.get('nextCursor')
            if not cursor:
                break
        return tools

    def call_tool(
        self,
        tool_name: str,
        arguments: dict,
        timeout_s: float = _DEFAULT_CALL_TIMEOUT,
    ) -> ToolResult:
        try:
            result = self._request(
                'tools/call',
                {'name': tool_name, 'arguments': arguments or {}},
                timeout_s=timeout_s,
            )
        except MCPError as exc:
            return ToolResult(content=str(exc), is_error=True)

        content = result.get('content') or []
        text = _render_content_blocks(content)
        is_error = bool(result.get('isError'))
        blocks = content if isinstance(content, list) else []
        return ToolResult(content=text, is_error=is_error, content_blocks=blocks)


# ---------------------------------------------------------------------- rendering


def _render_content_blocks(blocks: Iterable[dict]) -> str:
    """Join MCP content blocks into a string.

    Non-text blocks become markers so chrome-devtools screenshots etc. aren't
    silently dropped.
    """
    parts: list[str] = []
    for blk in blocks:
        btype = blk.get('type')
        if btype == 'text':
            parts.append(str(blk.get('text', '')))
        elif btype == 'image':
            mime = blk.get('mimeType') or '?'
            data = blk.get('data') or ''
            parts.append(f'[image: {mime}, {len(data)} base64 chars — not inlined]')
        elif btype == 'audio':
            mime = blk.get('mimeType') or '?'
            parts.append(f'[audio: {mime} — not inlined]')
        elif btype == 'resource':
            res = blk.get('resource') or {}
            uri = res.get('uri') or '?'
            parts.append(f'[resource: {uri}]')
        elif btype == 'resource_link':
            uri = blk.get('uri') or '?'
            parts.append(f'[resource_link: {uri}]')
        else:
            parts.append(f"[{btype or 'unknown'} block]")
    return '\n'.join(p for p in parts if p)


# ---------------------------------------------------------------------- tool adapter


def _make_tool_name(server_name: str, tool_name: str) -> str:
    full = f'mcp__{server_name}__{tool_name}'
    if len(full) <= _TOOL_NAME_MAX:
        return full
    # Budget: mcp__{server}__{hash8}_{truncated-tail}
    digest = hashlib.sha256(tool_name.encode('utf-8')).hexdigest()[:8]
    prefix = f'mcp__{server_name}__{digest}_'
    remaining = _TOOL_NAME_MAX - len(prefix)
    if remaining <= 0:
        # Even the prefix is too long — degrade server segment too.
        srv_digest = hashlib.sha256(server_name.encode('utf-8')).hexdigest()[:8]
        prefix = f'mcp__{srv_digest}__{digest}_'
        remaining = _TOOL_NAME_MAX - len(prefix)
    tail = tool_name[-max(remaining, 1):] if remaining > 0 else ''
    return (prefix + tail)[:_TOOL_NAME_MAX]


class MCPTool(Tool):
    def __init__(self, server: MCPServer, spec: dict) -> None:
        self._server = server
        self._spec = spec
        self._original_name = spec.get('name', '')
        self._name = _make_tool_name(server.name, self._original_name)
        self._description = (spec.get('description') or '').strip() or (
            f'MCP tool {self._original_name} from server {server.name}'
        )
        self._input_schema = spec.get('inputSchema') or {'type': 'object', 'properties': {}}
        annotations = spec.get('annotations') or {}
        # Distinguish "server omitted the hint" from "server explicitly said
        # not read-only".  `dict.get('readOnlyHint', False)` collapses both to
        # False, after which the name heuristic could override an *explicit*
        # readOnlyHint=False — turning a mutating tool with a misleading name
        # (e.g. `get_and_clear_cache`, `list_and_purge_orphans`) into a
        # read-only one and dropping it into the parallel batch.  Honour the
        # explicit hint when present; fall back to the heuristic only when
        # the field is missing — chrome-devtools-mcp and playwright-mcp
        # rarely set it at all.
        hint = annotations.get('readOnlyHint')
        if hint is None:
            self._read_only = _is_likely_readonly_by_name(self._original_name)
        else:
            self._read_only = bool(hint)

        # Keep heavy read-only tools sequential — see _HEAVY_READONLY_TOOLS.
        self.concurrent_safe = (
            self._read_only
            and (server.name, self._original_name) not in _HEAVY_READONLY_TOOLS
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict:
        return self._input_schema

    def is_read_only(self) -> bool:
        return self._read_only

    def get_activity_description(self, **kwargs) -> str | None:
        return f'MCP {self._server.name}: {self._original_name}'

    def execute(self, **kwargs) -> ToolResult:
        return self._server.call_tool(self._original_name, kwargs)


# ---------------------------------------------------------------------- manager


class MCPManager:
    """Owns a set of MCPServers; starts them in parallel, cleans up on exit."""

    def __init__(self, server_configs: Iterable[Any]) -> None:
        # Accepts MCPServerConfig-likes: attributes name, command, args, env.
        self._configs = list(server_configs)
        self._servers: dict[str, MCPServer] = {}

    def start_and_collect_tools(self) -> list[Tool]:
        if not self._configs:
            return []
        tools: list[Tool] = []
        # Start each server in its own thread so slow `npx` cold starts
        # don't serialize.
        results: queue.Queue[tuple[str, MCPServer | None, Exception | None]] = queue.Queue()

        def _start_one(cfg: Any) -> None:
            server = MCPServer(
                name=cfg.name,
                command=cfg.command,
                args=list(cfg.args or []),
                env=dict(cfg.env or {}) or None,
            )
            try:
                server.start()
                results.put((cfg.name, server, None))
            except Exception as exc:
                results.put((cfg.name, server, exc))

        threads = []
        for cfg in self._configs:
            t = threading.Thread(target=_start_one, args=(cfg,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

        while not results.empty():
            name, server, err = results.get()
            if err is not None:
                _log.warning('MCP server %r failed to start: %s', name, err)
                if name == 'browser':
                    raise RuntimeError(f"Critical MCP server 'browser' failed to start: {err}")
                continue
            if server is None:
                continue
            self._servers[name] = server
            tool_count = len(server.tools)
            _log.info('MCP server %r started, %d tools loaded', name, tool_count)
            for spec in server.tools:
                try:
                    tools.append(MCPTool(server, spec))
                except Exception as exc:
                    _log.warning('%s: skipping malformed tool spec %s: %s', name, spec, exc)
        return tools

    def shutdown_all(self) -> None:
        for name, server in list(self._servers.items()):
            try:
                server.shutdown()
            except Exception as exc:
                _log.warning('shutdown of %s failed: %s', name, exc)
        self._servers.clear()
