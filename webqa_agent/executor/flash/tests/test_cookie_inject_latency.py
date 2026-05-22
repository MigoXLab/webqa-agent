"""Latency benchmark — cookie injection round-trip.

Measures ``connect() + set_cookies() + close()`` against the FakeCDPServer
used by test_cdp_client.py. This bounds the per-worker startup overhead
the feature adds on top of a run.

Skipped by default; run with ``pytest -m perf`` or ``--run-perf``.
"""
from __future__ import annotations

import statistics

import pytest

from webqa_agent.executor.flash.features.cookies.cdp_client import \
    CDPCookieClient
# Reuse the fake server defined in test_cdp_client.py rather than duplicating
# ~250 lines of framing code.
from webqa_agent.executor.flash.tests.test_cdp_client import \
    FakeCDPServer  # noqa: E402

pytestmark = pytest.mark.perf


_COOKIES = [{
    'name': 'session',
    'value': 'x' * 200,
    'domain': '.example.com',
    'path': '/',
    'secure': True,
    'httpOnly': True,
}]


def _one_round_trip(port: int) -> float:
    """Return wall-clock seconds for connect + set_cookies + close."""
    import time as _time
    t0 = _time.perf_counter()
    c = CDPCookieClient(port, timeout=2.0)
    c.connect()
    try:
        c.set_cookies(_COOKIES)
    finally:
        c.close()
    return _time.perf_counter() - t0


def test_inject_latency_p95_under_150ms():
    """[perf] 10 injections, p95 latency < 150ms against a loopback fake.

    A real chrome-devtools-mcp / Chromium pair adds its own latency on top of
    this number — this test bounds only the client-side transport cost, which
    is the incremental overhead the cookies feature contributes.
    """
    server = FakeCDPServer()
    server.start()
    try:
        # Script enough `Storage.setCookies` responses to satisfy 10 runs.
        for i in range(10):
            server.script_text_response({'id': 1, 'result': {}})

        samples = []
        for _ in range(10):
            samples.append(_one_round_trip(server.port))

        p95 = statistics.quantiles(samples, n=20)[-1]  # 95th percentile
        median = statistics.median(samples)
        print(
            f'\nCDP inject latency: median={median * 1000:.1f}ms '
            f'p95={p95 * 1000:.1f}ms samples={[round(s * 1000, 1) for s in samples]}')

        assert p95 < 0.150, (
            f'p95 latency {p95 * 1000:.1f}ms exceeds 150ms budget; samples='
            f'{samples}')
    finally:
        server.close()
