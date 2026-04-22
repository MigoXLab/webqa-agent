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
    """Render an HTML report for a cc-mini ``RunResult``.

    Preferred path uses the gen-mode React frontend via the adapter +
    ``ResultAggregator``.  Falls back to the standalone
    ``webqa-cc-mini/features/report.py`` if the gen-mode path fails.

    Returns the absolute report path on success, ``None`` on failure.
    """
    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from webqa_agent.executor.cc_mini_report_adapter import (
            run_result_to_aggregated_data,
            run_result_to_session,
        )
        from webqa_agent.executor.result_aggregator import ResultAggregator

        session = run_result_to_session(
            run_result,
            url=url,
            task=task,
            report_dir=str(out_dir),
            language=language,
        )
        aggregated_data = run_result_to_aggregated_data(
            run_result,
            url=url,
            task=task,
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

        html_path = render_html_report(
            run_result,
            out_dir / 'report.html',
            title=f'WebQA cc-mini — {url}',
            url=url,
            task=task,
        )
        return str(html_path)
    except Exception as exc:
        log.warning('Fallback report rendering also failed: %s', exc)
        return None
