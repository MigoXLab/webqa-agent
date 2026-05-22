"""Wait-for-DOM-stable tool.

Uses MutationObserver + debounce via chrome-devtools-mcp's evaluate_script to
wait until the page DOM stops changing — ideal for streaming LLM output,
progressive rendering, and async content loads.
"""
from __future__ import annotations

import logging
import time

from ..core.mcp_client import MCPServer
from ..core.tool import Tool, ToolResult

_log = logging.getLogger(__name__)

_MCP_TIMEOUT = 90

_JS_WAIT_STABLE_TEMPLATE = """\
async () => {{
  const debounceMs = {debounce};
  const timeoutMs = {timeout};
  return await new Promise((resolve) => {{
    const deadline = Date.now() + timeoutMs;
    let timer = null;
    let mutationCount = 0;
    const done = (reason) => {{
      observer.disconnect();
      if (timer) clearTimeout(timer);
      resolve(JSON.stringify({{
        stable: reason === 'stable', reason,
        mutations: mutationCount,
        elapsed: Date.now() - (deadline - timeoutMs),
      }}));
    }};
    const reset = () => {{
      if (timer) clearTimeout(timer);
      if (Date.now() >= deadline) {{ done('timeout'); return; }}
      timer = setTimeout(() => done('stable'), debounceMs);
    }};
    const observer = new MutationObserver((records) => {{
      mutationCount += records.length;
      reset();
    }});
    observer.observe(document.body, {{
      childList: true, subtree: true, characterData: true,
    }});
    reset();
    setTimeout(() => done('timeout'), timeoutMs);
  }});
}}"""


class WaitForDomStableTool(Tool):
    """Wait until DOM stops changing (MutationObserver + debounce).

    Useful for streaming output, progressive rendering, lazy loads.
    Resolves when no DOM mutations occur for `debounce_ms` milliseconds,
    or aborts after `timeout_ms`.
    """

    concurrent_safe = False

    def __init__(self, browser_server: MCPServer) -> None:
        self._browser = browser_server

    @property
    def name(self) -> str:
        return 'wait_for_dom_stable'

    @property
    def description(self) -> str:
        return (
            'Wait until the page DOM stops changing. Useful for streaming '
            'LLM output, progressive rendering, and async content loads. '
            'Resolves when no DOM mutation occurs for debounce_ms, or '
            'times out after timeout_ms.'
        )

    @property
    def input_schema(self) -> dict:
        return {
            'type': 'object',
            'properties': {
                'debounce_ms': {
                    'type': 'integer',
                    'description': (
                        'Milliseconds of silence (no DOM changes) before '
                        'considering the page stable. Default 2000.'
                    ),
                    'default': 2000,
                },
                'timeout_ms': {
                    'type': 'integer',
                    'description': (
                        'Maximum wait time in milliseconds. Default 60000 '
                        '(60 seconds).'
                    ),
                    'default': 60000,
                },
            },
            'required': [],
        }

    def execute(self, **kwargs) -> ToolResult:
        debounce = max(500, min(int(kwargs.get('debounce_ms', 2000)), 10000))
        timeout = max(1000, min(int(kwargs.get('timeout_ms', 60000)), 120000))

        _log.info(
            'wait_for_dom_stable: debounce=%dms timeout=%dms',
            debounce, timeout,
        )

        mcp_timeout = (timeout / 1000) + 10
        t0 = time.monotonic()

        try:
            js_fn = _JS_WAIT_STABLE_TEMPLATE.format(
                debounce=debounce, timeout=timeout,
            )
            result = self._browser.call_tool(
                'evaluate_script',
                {'function': js_fn},
                timeout_s=mcp_timeout,
            )
        except Exception as exc:
            elapsed = time.monotonic() - t0
            _log.warning('wait_for_dom_stable failed: %s (%.1fs)', exc, elapsed)
            return ToolResult(
                content=f'DOM stability check failed: {exc}',
                is_error=True,
            )

        elapsed = time.monotonic() - t0

        if result.is_error:
            return ToolResult(
                content=f'DOM stability check error: {result.content}',
                is_error=True,
            )

        _log.info(
            'wait_for_dom_stable: done in %.1fs — %s',
            elapsed, result.content[:200],
        )
        return ToolResult(content=result.content)

    def get_activity_description(self, **kwargs) -> str:
        timeout = kwargs.get('timeout_ms', 60000)
        return f'Waiting for DOM to stabilize (up to {timeout}ms)'

    def is_read_only(self) -> bool:
        return True
