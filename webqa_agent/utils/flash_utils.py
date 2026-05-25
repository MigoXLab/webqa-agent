"""Shared utilities for loading and rendering Flash engine runs.

Centralises ``load_flash_runner`` and ``render_flash_report`` so both
``webqa_agent.cli`` and ``backend.gen_webqa`` use a single implementation.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


def _load_cookies_module(
    *,
    project_root: Path | None = None,
    module_name: str = 'webqa_cc_mini_cookies',
):
    """Soft-load ``features.cookies`` from the mini package.

    Backward-compatible signature: ``project_root`` and ``module_name``
    are accepted but ignored — the package is now importable directly.
    """
    from webqa_agent.executor.flash.features import cookies
    return cookies


def build_cookie_extensions_from_config(
    cfg: dict,
    *,
    source_file: str | Path | None = None,
    project_root: Path | None = None,
):
    """Build a webqa-cc-mini ``Extensions`` bundle from a webqa-agent config.

    Reads the top-level ``accounts:`` list (preferred) and
    ``browser_config.cookies`` (deprecated fallback) from ``cfg`` and turns
    them into an ``Extensions`` object suitable for spreading into
    ``run_cc_mini`` via ``**ext.as_kwargs()``.

    Resolution rules:

    * ``accounts:`` non-empty → forwarded; if no entry has ``default: true``,
      the first account is auto-promoted with a logged warning.
    * ``accounts:`` empty + ``browser_config.cookies`` non-empty → cookies
      are wrapped as a single anonymous default account with a deprecation
      warning telling the user to migrate.
    * ``accounts:`` empty + no fallback cookies → returns ``None`` (caller
      should treat as a no-op).

    Args:
        cfg: Parsed YAML config dict.
        source_file: Path to the YAML file, used for resolving relative
            ``cookies_file`` paths inside accounts.
        project_root: Override webqa-agent root (mostly for tests).

    Returns:
        ``Extensions`` instance, or ``None`` when no cookie sources are set.

    Raises:
        ValueError: When the cookie configuration is invalid (duplicate
            names, multiple defaults, missing ``domain``/``url``, etc.).
            Always raised with a single-line user-facing message.
    """
    from webqa_agent.utils.config import load_accounts

    accounts_raw = cfg.get('accounts') or []
    fallback_cookies = (
        (cfg.get('browser_config') or {}).get('cookies') or []
    )
    if not accounts_raw and not fallback_cookies:
        return None

    cookies_mod = _load_cookies_module(project_root=project_root)
    AccountSpec = cookies_mod.AccountSpec
    build_cookie_extensions = cookies_mod.build_cookie_extensions

    account_specs: list = []
    if accounts_raw:
        try:
            loaded = load_accounts(accounts_raw, source_file=source_file) or []
        except Exception as exc:
            raise ValueError(
                f'Invalid accounts config: {exc}') from exc

        for ac in loaded:
            account_specs.append(AccountSpec(
                name=ac.name,
                cookies=list(ac.resolved_cookies or []),
                role=ac.role or '',
                default=bool(ac.default),
            ))

        # [u3] Auto-promote first account when no explicit default is set.
        # Visible to the user — silent auto-promotion would violate the
        # project-wide CLAUDE.md rule "默认行为不变".
        if account_specs and not any(a.default for a in account_specs):
            promoted = account_specs[0]
            log.warning(
                "No 'default: true' on any account; auto-promoting "
                "accounts[0]=%r as the startup identity. Set 'default: true' "
                'explicitly to silence this warning.',
                promoted.name,
            )
            promoted.default = True

    fb_cookies_for_build: list[dict] = []
    if not account_specs and fallback_cookies:
        # Backward-compat: caller has only browser_config.cookies (the
        # legacy config shape). Treat as a single anonymous default — and
        # tell them to migrate so this branch can be removed eventually.
        log.warning(
            'browser_config.cookies is deprecated for Flash mode; '
            'migrate to accounts: [{name: ..., cookies_file: ...}] '
            'in your config. The legacy field will be wrapped as a '
            'fallback identity for this run.'
        )
        fb_cookies_for_build = list(fallback_cookies)

    try:
        return build_cookie_extensions(
            accounts=account_specs or None,
            cookies=fb_cookies_for_build or None,
        )
    except ValueError as exc:
        # build_cookie_extensions formats a multi-line bullet list; collapse
        # to a one-line CLI message but keep the underlying detail visible.
        raise ValueError(f'Cookie configuration rejected: {exc}') from exc


def load_flash_runner(
    *,
    project_root: Path | None = None,
    module_name: str = 'webqa_cc_mini_runner',
) -> Callable[..., Any]:
    """Load ``run_cc_mini`` (the Flash engine entrypoint).

    Backward-compatible signature: ``project_root`` and ``module_name``
    are accepted but ignored — the package is now importable directly.

    Returns:
        The ``run_cc_mini`` callable from ``webqa_agent.executor.flash.runner``.
    """
    from webqa_agent.executor.flash.runner import run_cc_mini
    return run_cc_mini


def render_flash_report(
    run_result: Any,
    *,
    report_dir: str,
    url: str,
    task: str,
    language: str = 'zh-CN',
    model: str | None = None,
    filter_model: str | None = None,
) -> Optional[str]:
    """Render an HTML report for a single Flash ``RunResult``.

    Thin wrapper around :func:`render_flash_multi_report` for
    backward compatibility with callers that only have one run.
    """
    return render_flash_multi_report(
        [run_result],
        report_dir=report_dir,
        url=url,
        tasks=[task],
        language=language,
        model=model,
        filter_model=filter_model,
    )


def render_flash_multi_report(
    run_results: list[Any],
    *,
    report_dir: str,
    url: str,
    tasks: list[str],
    language: str = 'zh-CN',
    model: str | None = None,
    filter_model: str | None = None,
) -> Optional[str]:
    """Render a single HTML report from N Flash ``RunResult`` objects.

    Preferred path uses the gen-mode React frontend via the multi-case
    adapter + ``ResultAggregator``.  Falls back to the standalone
    ``webqa_agent/executor/flash/features/report.py`` for the FIRST run
    only when the gen-mode path fails (the fallback can't render multi-case).

    Returns the absolute report path on success, ``None`` on failure.
    """
    if len(run_results) != len(tasks):
        raise ValueError(
            f'run_results ({len(run_results)}) and tasks ({len(tasks)}) '
            'must have the same length.'
        )
    if not run_results:
        raise ValueError('run_results must not be empty.')

    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from webqa_agent.executor.flash_report_adapter import (
            run_result_to_session, run_results_to_aggregated_data)
        from webqa_agent.executor.result_aggregator import ResultAggregator

        # Session-level metadata is carried by the FIRST run; the
        # aggregated_data dict is what the React frontend actually reads
        # so individual case data still flows through correctly.
        session = run_result_to_session(
            run_results[0],
            url=url,
            task=tasks[0],
            report_dir=str(out_dir),
            language=language,
        )
        aggregated_data = run_results_to_aggregated_data(
            run_results,
            url=url,
            tasks=tasks,
            language=language,
            model=model,
            filter_model=filter_model,
        )
        aggregator = ResultAggregator(report_config={
            'language': language,
            'report_dir': str(out_dir),
        })
        generated_path = aggregator.generate_html_report_fully_inlined(
            session,
            report_dir=str(out_dir),
            aggregated_data=aggregated_data,
        )
        if generated_path and Path(generated_path).exists():
            return generated_path
    except Exception as exc:
        log.warning('Gen-mode report rendering failed, trying fallback: %s', exc)

    try:
        from webqa_agent.executor.flash.features.report import \
            render_html_report

        # Standalone fallback only renders one run; pick the first.
        html_path = render_html_report(
            run_results[0],
            out_dir / 'report.html',
            title=f'WebQA Flash — {url}',
            url=url,
            task=tasks[0],
        )
        return str(html_path)
    except Exception as exc:
        log.warning('Fallback report rendering also failed: %s', exc)
        return None
