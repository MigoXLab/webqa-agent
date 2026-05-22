# SPDX-License-Identifier: Apache-2.0
# Portions adapted from cc-mini (https://github.com/e10nMa2k/cc-mini)
# Original author: e10nMa2k. Modifications © 2026 WebQA Agent contributors.
"""Minimal config helpers for the library-mode web agent.

Kept from the original cc-mini config.py: model alias resolution, per-model max
token defaults, and the MCPServerConfig dataclass. All TOML-file / AppConfig /
env-var loading was removed — the library accepts parameters directly via
run_cc_mini().
"""
from __future__ import annotations

from dataclasses import dataclass

from .llm import validate_provider

DEFAULT_MODEL = 'claude-sonnet-4-6'
DEFAULT_PROVIDER = 'anthropic'

_ANTHROPIC_FALLBACK_MAX_TOKENS = 32000
_OPENAI_FALLBACK_MAX_TOKENS = 8192

_MODEL_ALIASES = {
    'sonnet': 'claude-sonnet-4-6',
    'opus': 'claude-opus-4-6',
    'haiku': 'claude-haiku-4-5-20251001',
    'best': 'claude-opus-4-6',
    'sonnet35': 'claude-3-5-sonnet-20241022',
    'sonnet37': 'claude-3-7-sonnet-20250219',
    'haiku35': 'claude-3-5-haiku-20241022',
    'sonnet45': 'claude-sonnet-4-5-20250929',
    'opus45': 'claude-opus-4-5-20251101',
    'claude-opus-4.6': 'claude-opus-4-6',
    'claude-opus-4.5': 'claude-opus-4-5',
    'claude-opus-4.1': 'claude-opus-4-1',
    'claude-opus-4': 'claude-opus-4',
    'claude-sonnet-4.6': 'claude-sonnet-4-6',
    'claude-sonnet-4.5': 'claude-sonnet-4-5',
    'claude-sonnet-4': 'claude-sonnet-4',
    'claude-3.7-sonnet': 'claude-3-7-sonnet',
    'claude-3.5-sonnet': 'claude-3-5-sonnet',
    'claude-3.5-haiku': 'claude-3-5-haiku',
    'claude-3-haiku': 'claude-3-haiku',
}

# First prefix match wins. Values from official getModelMaxOutputTokens().
_MODEL_MAX_TOKENS = (
    ('claude-opus-4-6', 64000),
    ('claude-sonnet-4-6', 32000),
    ('claude-opus-4-5', 32000),
    ('claude-sonnet-4-5', 32000),
    ('claude-sonnet-4', 32000),
    ('claude-haiku-4', 32000),
    ('claude-opus-4-1', 32000),
    ('claude-opus-4', 32000),
    ('claude-3-7-sonnet', 32000),
    ('claude-3-5-sonnet', 8192),
    ('claude-3-5-haiku', 8192),
    ('claude-3-haiku', 4096),
    # OpenAI
    ('gpt-5', 8192),
    ('gpt-4.1', 16384),
    ('gpt-4o', 16384),
    ('o1', 32768),
    ('o3', 32768),
    ('o4', 32768),
    # Gemini (via OpenAI-compatible proxies). Kept as separate series entries
    # so future per-version tuning (e.g. gemini-3 raised to 65536) becomes a
    # one-line change without reshuffling prefix order. Values intentionally
    # conservative — Gemini proxies vary in what they actually accept.
    ('gemini-3', 8192),
    ('gemini-2.5', 8192),
    ('gemini-2', 8192),
    ('gemini-', 8192),
)


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()


def resolve_model(model: str | None, provider: str = DEFAULT_PROVIDER) -> str:
    provider = validate_provider(provider)
    if not model:
        from .llm import default_model_for_provider
        return default_model_for_provider(provider)
    normalized = model.strip()
    if provider != 'anthropic':
        return normalized
    return _MODEL_ALIASES.get(normalized, normalized)


def default_max_tokens_for_model(
    model: str | None,
    provider: str = DEFAULT_PROVIDER,
) -> int:
    provider = validate_provider(provider)
    resolved = resolve_model(model, provider=provider)
    for prefix, limit in _MODEL_MAX_TOKENS:
        if resolved.startswith(prefix):
            return limit
    if provider == 'openai':
        return _OPENAI_FALLBACK_MAX_TOKENS
    return _ANTHROPIC_FALLBACK_MAX_TOKENS
