"""Independent verification tool — uses a separate LLM to judge assertions.

Separates the "doer" (main agent) from the "checker" (filter model) to
counter self-verification bias.  Collects evidence from the browser via
MCP, then asks a cheaper model to evaluate the assertion against that
evidence.

Usage by the agent::

    verify(assertion="The login form shows an error message for invalid credentials")
    verify(assertion="Cart badge displays 3", evidence_mode="snapshot")
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..core.llm import (LLMClient, infer_provider_from_model,
                        supports_reasoning_effort)
from ..core.mcp_client import MCPServer
from ..core.tool import Tool, ToolResult

_log = logging.getLogger('cc_mini.verify')

_MAX_TOKENS = 1024
_SNAPSHOT_MAX_CHARS = 40_000
_MCP_TIMEOUT = 30.0
_JSON_FENCE_RE = re.compile(r'^```(?:json)?\s*|\s*```$', re.DOTALL)
_VERDICT_TAGS = {'PASSED': '[SUCCESS]', 'FAILED': '[FAILURE]'}

_SYSTEM_PROMPT = (
    'You are an independent QA verifier. You receive page evidence '
    '(DOM snapshot and/or screenshot) from a browser session and an '
    'assertion to evaluate.\n\n'
    'Your job:\n'
    '1. Examine the evidence carefully.\n'
    '2. Determine whether the assertion is SUPPORTED or CONTRADICTED '
    'by the evidence, or if the evidence is INSUFFICIENT.\n'
    '3. Respond with ONLY a JSON object (no markdown fences):\n\n'
    '{"verdict": "PASSED"|"FAILED"|"CANNOT_VERIFY", '
    '"details": "<one-sentence explanation>", '
    '"evidence_used": "<what you observed in the evidence>"}\n\n'
    'Rules:\n'
    '- PASSED: evidence clearly supports the assertion.\n'
    '- FAILED: evidence clearly contradicts the assertion.\n'
    '- CANNOT_VERIFY: evidence is insufficient or ambiguous.\n'
    '- Be objective. Do not guess or assume beyond what is shown.\n'
    '- Keep details concise — one sentence.'
)


def _build_user_prompt(assertion: str, snapshot_text: str | None) -> str:
    parts = [f'## Assertion\n{assertion}\n']
    if snapshot_text:
        truncated = snapshot_text[:_SNAPSHOT_MAX_CHARS]
        if len(snapshot_text) > _SNAPSHOT_MAX_CHARS:
            truncated += '\n[snapshot truncated]'
        parts.append(f'## DOM Snapshot\n```\n{truncated}\n```\n')
    return '\n'.join(parts)


class VerifyTool(Tool):
    # Read-only by contract, but execute() fans out to take_snapshot +
    # take_screenshot on the same browser MCPServer; running it in a parallel
    # batch with other read-only tools makes them all queue on the renderer's
    # main thread and inflates the chance of a 30s/60s synchronous timeout.
    concurrent_safe = False
    """Evaluate an assertion against current page state using an independent
    LLM."""

    def __init__(
        self,
        browser_server: MCPServer,
        llm_client: LLMClient,
        model: str,
    ) -> None:
        self._browser = browser_server
        self._llm = llm_client
        self._model = model

    @property
    def name(self) -> str:
        return 'verify'

    @property
    def description(self) -> str:
        return (
            'Independently verify an assertion about the current page state. '
            'Collects DOM snapshot and/or screenshot as evidence, then uses a '
            'separate LLM to judge whether the assertion holds.\n\n'
            'Use this tool at key checkpoints to get an objective second '
            'opinion — it catches failures you might overlook.\n\n'
            'Returns: [SUCCESS], [FAILURE], or [WARNING] with details.'
        )

    @property
    def input_schema(self) -> dict:
        return {
            'type': 'object',
            'properties': {
                'assertion': {
                    'type': 'string',
                    'description': (
                        'The statement to verify against current page state. '
                        'Be specific: "The search results contain at least 3 items" '
                        'is better than "search works".'
                    ),
                },
                'evidence_mode': {
                    'type': 'string',
                    'enum': ['snapshot', 'visual', 'full'],
                    'description': (
                        '"snapshot" = DOM tree only (fast, good for text/structure). '
                        '"visual" = screenshot only (good for layout/styling). '
                        '"full" = both snapshot + screenshot (most thorough). '
                        'Default: "full".'
                    ),
                },
            },
            'required': ['assertion'],
        }

    def is_read_only(self) -> bool:
        return True

    def get_activity_description(self, **kwargs: Any) -> str | None:
        assertion = str(kwargs.get('assertion', ''))[:60]
        return f'Verifying: {assertion}'

    def execute(self, **kwargs: Any) -> ToolResult:
        assertion = (kwargs.get('assertion') or '').strip()
        if not assertion:
            return ToolResult(
                content='[FAILURE] No assertion provided.',
                is_error=True,
            )
        if len(assertion) < 15:
            return ToolResult(
                content=(
                    '[WARNING] Assertion too vague. Be specific: '
                    '"The error message reads X" not "page looks good".'
                ),
            )
        evidence_mode = (kwargs.get('evidence_mode') or 'full').strip().lower()
        if evidence_mode not in ('snapshot', 'visual', 'full'):
            evidence_mode = 'full'

        snapshot_text, screenshot_blocks = self._collect_evidence(evidence_mode)

        if not snapshot_text and not screenshot_blocks:
            return ToolResult(
                content=(
                    f'[WARNING] {assertion} — '
                    'Failed to collect any evidence from the browser.'
                ),
            )

        return self._judge(assertion, snapshot_text, screenshot_blocks)

    def _collect_evidence(
        self, mode: str,
    ) -> tuple[str | None, list[dict[str, Any]]]:
        snapshot_text: str | None = None
        screenshot_blocks: list[dict[str, Any]] = []

        if mode in ('snapshot', 'full'):
            try:
                result = self._browser.call_tool(
                    'take_snapshot', {}, timeout_s=_MCP_TIMEOUT,
                )
                if not result.is_error:
                    snapshot_text = result.content
            except Exception as exc:
                _log.warning('verify: take_snapshot failed: %s', exc)

        if mode in ('visual', 'full'):
            try:
                result = self._browser.call_tool(
                    'take_screenshot',
                    {'format': 'jpeg', 'quality': 55},
                    timeout_s=_MCP_TIMEOUT,
                )
                if not result.is_error and result.content_blocks:
                    screenshot_blocks = [
                        blk for blk in result.content_blocks
                        if isinstance(blk, dict)
                        and blk.get('type') == 'image'
                        and blk.get('data')
                    ]
            except Exception as exc:
                _log.warning('verify: take_screenshot failed: %s', exc)

        return snapshot_text, screenshot_blocks

    def _judge(
        self,
        assertion: str,
        snapshot_text: str | None,
        screenshot_blocks: list[dict[str, Any]],
    ) -> ToolResult:
        user_content: list[dict[str, Any]] = []

        user_text = _build_user_prompt(assertion, snapshot_text)
        user_content.append({'type': 'text', 'text': user_text})

        for blk in screenshot_blocks:
            mime = str(blk.get('mimeType') or 'image/png')
            data = str(blk.get('data', ''))
            user_content.append({
                'type': 'image',
                'source': {
                    'type': 'base64',
                    'media_type': mime,
                    'data': data,
                },
            })

        messages = [{'role': 'user', 'content': user_content}]

        _provider = infer_provider_from_model(self._model)
        _use_temp = not supports_reasoning_effort(_provider, self._model)

        try:
            response = self._llm.create_message(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                system=_SYSTEM_PROMPT,
                messages=messages,
                temperature=0.0 if _use_temp else None,
            )
        except Exception as exc:
            _log.error('verify: LLM call failed: %s', exc)
            return ToolResult(
                content=(
                    f'[WARNING] {assertion} — '
                    f'Verification LLM call failed: {exc}'
                ),
            )

        return self._parse_verdict(assertion, response.content)

    def _parse_verdict(
        self, assertion: str, content: list[dict[str, Any]],
    ) -> ToolResult:
        raw_text = _JSON_FENCE_RE.sub('', ''.join(
            block.get('text', '') for block in content
            if isinstance(block, dict) and block.get('type') == 'text'
        )).strip()

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            return ToolResult(
                content=(
                    f'[WARNING] {assertion} — '
                    f'Could not parse verifier response: {raw_text[:200]}'
                ),
            )

        verdict = str(parsed.get('verdict', 'CANNOT_VERIFY')).upper()
        if verdict not in ('PASSED', 'FAILED', 'CANNOT_VERIFY'):
            verdict = 'CANNOT_VERIFY'
        details = str(parsed.get('details', ''))
        evidence_used = str(parsed.get('evidence_used', ''))

        tag = _VERDICT_TAGS.get(verdict, '[WARNING]')

        parts = [f'{tag} {assertion}']
        if details:
            parts.append(f'Details: {details}')
        if evidence_used:
            parts.append(f'Evidence: {evidence_used}')

        return ToolResult(content=' — '.join(parts))
