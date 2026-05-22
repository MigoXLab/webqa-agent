"""Cookie injection and multi-account switching — runnable examples.

Run any one of the demos below::

    python -m examples.cookies_basic single
    python -m examples.cookies_basic multi
    python -m examples.cookies_basic concurrent

Prerequisites:
  * ``npm install -g chrome-devtools-mcp@latest`` (pin to a tested version in
    CI — see README section on install).
  * An LLM provider credential in the environment
    (``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY``).

None of the demos hit a real remote service; they point at ``example.com`` so
you can observe the Chrome session, cookie injection, and agent loop without
leaking credentials.
"""
from __future__ import annotations

import asyncio
import sys

from webqa_agent.executor.flash.features.cookies import (
    AccountSpec, build_cookie_extensions)
from webqa_agent.executor.flash.runner import run_cc_mini

_DUMMY_ADMIN = [{
    'name': 'session', 'value': 'admin-demo-token',
    'domain': '.example.com', 'path': '/',
    'secure': True, 'httpOnly': True,
}]

_DUMMY_VIEWER = [{
    'name': 'session', 'value': 'viewer-demo-token',
    'domain': '.example.com', 'path': '/',
    'secure': True, 'httpOnly': True,
}]


def single_account_demo() -> None:
    """Inject one set of cookies at startup — no mid-run switching."""
    ext = build_cookie_extensions(cookies=_DUMMY_ADMIN)
    result = run_cc_mini(
        url='https://example.com/',
        user_input='Read the H1 and report back.',
        worker_id=0,
        **ext.as_kwargs(),
    )
    print('final:', result.final_text)
    if result.extensions_failed:
        print('extensions failed:', result.extensions_failed)


def multi_account_demo() -> None:
    """Two accounts; agent may call ``switch_account`` mid-run."""
    ext = build_cookie_extensions(accounts=[
        AccountSpec(name='admin', cookies=_DUMMY_ADMIN, default=True,
                    role='Full administrator'),
        AccountSpec(name='viewer', cookies=_DUMMY_VIEWER,
                    role='Read-only user'),
    ])
    result = run_cc_mini(
        url='https://example.com/',
        user_input=(
            'You start as admin. After reading the page once, switch to '
            'the viewer account via switch_account(account="viewer", '
            'navigate_url="https://example.com/") and report any visible '
            'differences.'
        ),
        worker_id=0,
        **ext.as_kwargs(),
    )
    print('final:', result.final_text)
    if result.extensions_failed:
        print('extensions failed:', result.extensions_failed)


async def concurrent_demo(n: int = 3) -> None:
    """Fan out N cases in parallel — each gets its own worker_id and port."""
    async def run_one(worker_id: int, account: AccountSpec) -> str:
        ext = build_cookie_extensions(accounts=[account])
        result = await asyncio.to_thread(
            run_cc_mini,
            url='https://example.com/',
            user_input=f'Worker {worker_id}: report the H1.',
            worker_id=worker_id,
            **ext.as_kwargs(),
        )
        return f'[w{worker_id}] {result.final_text[:80]}'

    accounts = [
        AccountSpec(name=f'user{i}',
                    cookies=[{'name': 'session',
                              'value': f'tok-{i}',
                              'domain': '.example.com',
                              'path': '/'}],
                    default=True)
        for i in range(n)
    ]
    outputs = await asyncio.gather(
        *(run_one(i, a) for i, a in enumerate(accounts)))
    for line in outputs:
        print(line)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else 'single'
    if mode == 'single':
        single_account_demo()
    elif mode == 'multi':
        multi_account_demo()
    elif mode == 'concurrent':
        asyncio.run(concurrent_demo())
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == '__main__':
    main()
