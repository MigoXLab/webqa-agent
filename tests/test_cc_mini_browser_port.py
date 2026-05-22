"""Tests for cc-mini managed Chrome CDP port preflight."""
from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest


def _load_runner(monkeypatch: pytest.MonkeyPatch):
    from webqa_agent.executor.flash import runner
    return runner


def _listening_socket() -> tuple[socket.socket, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    sock.listen(1)
    return sock, sock.getsockname()[1]


def test_managed_cdp_port_preflight_rejects_occupied_port(monkeypatch) -> None:
    """Managed Chrome must not start when CDP extensions would hit old
    Chrome."""
    runner = _load_runner(monkeypatch)
    sock, port = _listening_socket()
    try:
        cfg = runner.MCPServerConfig(
            name='browser',
            command='chrome-devtools-mcp',
            args=(f'--chrome-arg=--remote-debugging-port={port}',),
        )

        with pytest.raises(RuntimeError, match=str(port)):
            runner._ensure_cdp_port_available_for_extensions(
                [cfg], cdp_required=True)
    finally:
        sock.close()


def test_external_browser_url_allows_occupied_port(monkeypatch) -> None:
    """An occupied port is expected when attaching to an explicit browser
    URL."""
    runner = _load_runner(monkeypatch)
    sock, port = _listening_socket()
    try:
        cfg = runner.MCPServerConfig(
            name='browser',
            command='chrome-devtools-mcp',
            args=(f'--browser-url=http://127.0.0.1:{port}',),
        )

        runner._ensure_cdp_port_available_for_extensions(
            [cfg], cdp_required=True)
    finally:
        sock.close()


def test_preflight_is_skipped_when_no_cdp_extension_needs_port(monkeypatch) -> None:
    """Non-cookie runs should not fail only because a debug port is
    occupied."""
    runner = _load_runner(monkeypatch)
    sock, port = _listening_socket()
    try:
        cfg = runner.MCPServerConfig(
            name='browser',
            command='chrome-devtools-mcp',
            args=(f'--chrome-arg=--remote-debugging-port={port}',),
        )

        runner._ensure_cdp_port_available_for_extensions(
            [cfg], cdp_required=False)
    finally:
        sock.close()


def test_managed_cdp_endpoint_ready_accepts_missing_devtools_file(
    monkeypatch, tmp_path,
) -> None:
    """The HTTP endpoint is authoritative; DevToolsActivePort is optional."""
    runner = _load_runner(monkeypatch)
    cfg = runner.MCPServerConfig(
        name='browser',
        command='chrome-devtools-mcp',
        args=('--chrome-arg=--remote-debugging-port=9222',),
    )
    seen: list[tuple[str, int]] = []

    def fake_probe(host: str, port: int) -> None:
        seen.append((host, port))

    monkeypatch.setattr(runner, '_probe_cdp_http_endpoint', fake_probe)

    runner._ensure_managed_cdp_endpoint_ready(
        [cfg], profile=tmp_path, cdp_required=True)

    assert seen == [('127.0.0.1', 9222)]


def test_managed_cdp_endpoint_ready_rejects_wrong_profile_port(
    monkeypatch, tmp_path,
) -> None:
    """The DevToolsActivePort file must match the configured fixed port."""
    runner = _load_runner(monkeypatch)
    cfg = runner.MCPServerConfig(
        name='browser',
        command='chrome-devtools-mcp',
        args=('--chrome-arg=--remote-debugging-port=9222',),
    )
    (tmp_path / 'DevToolsActivePort').write_text(
        '9333\n/devtools/browser/test\n', encoding='utf-8')
    monkeypatch.setattr(
        runner, '_probe_cdp_http_endpoint', lambda host, port: None)

    with pytest.raises(RuntimeError, match='expected 9222'):
        runner._ensure_managed_cdp_endpoint_ready(
            [cfg], profile=tmp_path, cdp_required=True)


def test_managed_cdp_endpoint_ready_skips_external_browser(
    monkeypatch, tmp_path,
) -> None:
    """External browser attachments are validated by their explicit
    endpoint."""
    runner = _load_runner(monkeypatch)
    cfg = runner.MCPServerConfig(
        name='browser',
        command='chrome-devtools-mcp',
        args=('--browser-url=http://127.0.0.1:9222',),
    )

    runner._ensure_managed_cdp_endpoint_ready(
        [cfg], profile=tmp_path, cdp_required=True)


def test_tool_result_error_is_fatal(monkeypatch) -> None:
    """MCP startup failures must not be ignored before CDP injection."""
    runner = _load_runner(monkeypatch)
    result = SimpleNamespace(is_error=True, content='browser failed')

    with pytest.raises(RuntimeError, match='browser failed'):
        runner._ensure_tool_result_ok(result, context='browser list_pages')
