"""Shared utilities for loading and rendering cc-mini runs.

Centralises ``_load_cc_mini_runner`` and ``render_cc_mini_report`` so both
``webqa_agent.cli`` and ``backend.gen_webqa`` use a single implementation.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


def _cc_mini_root(project_root: Path | None = None) -> Path:
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent.parent
    return project_root / 'webqa-cc-mini'


def _load_cookies_module(
    *,
    project_root: Path | None = None,
    module_name: str = 'webqa_cc_mini_cookies',
):
    """Soft-load ``features.cookies`` from the sibling webqa-cc-mini tree.

    Mirrors ``load_cc_mini_runner``'s isolation pattern (temporary sys.path
    insertion + sys.modules cache key) so that ``webqa_agent`` keeps its
    soft dependency on webqa-cc-mini — pip-installing only ``webqa-agent``
    without the sibling tree must not blow up at import time.
    """
    cc_mini_root = _cc_mini_root(project_root)
    init_path = cc_mini_root / 'features' / 'cookies' / '__init__.py'
    if not init_path.exists():
        raise FileNotFoundError(
            f'webqa-cc-mini cookies module not found: {init_path}')

    cached = sys.modules.get(module_name)
    if cached is not None and hasattr(cached, 'build_cookie_extensions'):
        return cached

    original_sys_path = list(sys.path)
    try:
        if str(cc_mini_root) not in sys.path:
            sys.path.insert(0, str(cc_mini_root))
        spec = importlib.util.spec_from_file_location(
            module_name, init_path,
            submodule_search_locations=[str(init_path.parent)],
        )
        if spec is None or spec.loader is None:
            raise ImportError(f'Failed to import spec for {init_path}')
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = original_sys_path


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
            'browser_config.cookies is deprecated for cc-mini mode; '
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


def load_cc_mini_runner(
    *,
    project_root: Path | None = None,
    module_name: str = 'webqa_cc_mini_runner',
) -> Callable[..., Any]:
    """Load ``run_cc_mini`` from the sibling ``webqa-cc-mini/`` tree.

    Args:
        project_root: Root directory containing ``webqa-cc-mini/``.
            Defaults to two levels above this file.
        module_name: Module name used for ``sys.modules`` caching.
            Callers in different processes may pass different names to
            avoid cross-pollution.

    Returns:
        The ``run_cc_mini`` callable from ``webqa-cc-mini/runner.py``.
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent.parent

    cc_mini_root = project_root / 'webqa-cc-mini'
    runner_path = cc_mini_root / 'runner.py'

    if not runner_path.exists():
        raise FileNotFoundError(f'webqa-cc-mini runner not found: {runner_path}')

    cached_module = sys.modules.get(module_name)
    if cached_module is not None:
        run_cc_mini = getattr(cached_module, 'run_cc_mini', None)
        if callable(run_cc_mini):
            return run_cc_mini

    original_sys_path = list(sys.path)
    try:
        if str(cc_mini_root) not in sys.path:
            sys.path.insert(0, str(cc_mini_root))

        spec = importlib.util.spec_from_file_location(module_name, runner_path)
        if spec is None or spec.loader is None:
            raise ImportError(f'Failed to create import spec for {runner_path}')

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_sys_path

    run_cc_mini = getattr(module, 'run_cc_mini', None)
    if not callable(run_cc_mini):
        raise AttributeError(f'run_cc_mini not found in {runner_path}')
    return run_cc_mini


def render_cc_mini_report(
    run_result: Any,
    *,
    report_dir: str,
    url: str,
    task: str,
    language: str = 'zh-CN',
) -> Optional[str]:
    """Render an HTML report for a single cc-mini ``RunResult``.

    Thin wrapper around :func:`render_cc_mini_multi_report` for
    backward compatibility with callers that only have one run.
    """
    return render_cc_mini_multi_report(
        [run_result],
        report_dir=report_dir,
        url=url,
        tasks=[task],
        language=language,
    )


def render_cc_mini_multi_report(
    run_results: list[Any],
    *,
    report_dir: str,
    url: str,
    tasks: list[str],
    language: str = 'zh-CN',
) -> Optional[str]:
    """Render a single HTML report from N cc-mini ``RunResult`` objects.

    Preferred path uses the gen-mode React frontend via the multi-case
    adapter + ``ResultAggregator``.  Falls back to the standalone
    ``webqa-cc-mini/features/report.py`` for the FIRST run only when
    the gen-mode path fails (the fallback can't render multi-case).

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
        from webqa_agent.executor.cc_mini_report_adapter import (
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
        cc_mini_root = Path(__file__).resolve().parent.parent.parent / 'webqa-cc-mini'
        if str(cc_mini_root) not in sys.path:
            sys.path.insert(0, str(cc_mini_root))
        from features.report import render_html_report

        # Standalone fallback only renders one run; pick the first.
        html_path = render_html_report(
            run_results[0],
            out_dir / 'report.html',
            title=f'WebQA cc-mini — {url}',
            url=url,
            task=tasks[0],
        )
        return str(html_path)
    except Exception as exc:
        log.warning('Fallback report rendering also failed: %s', exc)
        return None
