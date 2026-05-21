"""Pytest configuration for webqa-cc-mini tests.

Registers custom markers so they don't emit ``PytestUnknownMarkWarning``
during collection.
"""
from __future__ import annotations


def pytest_configure(config) -> None:
    config.addinivalue_line(
        'markers',
        'perf: performance benchmarks (latency / memory / process count). '
        'Run selectively with `pytest -m perf`; exclude with `pytest -m "not perf"`.',
    )
    config.addinivalue_line(
        'markers',
        'integration: end-to-end tests that need a real chrome-devtools-mcp '
        'subprocess + Chromium + LLM credentials. Skipped by default in unit '
        'test runs.',
    )
