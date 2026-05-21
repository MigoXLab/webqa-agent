"""HTML report utility for RunResult.

A pure post-processing helper: takes the ``RunResult`` returned by
``run_cc_mini()`` and renders a self-contained HTML file summarising the
run. No LLM calls, no external dependencies (stdlib only), one function
call away from the caller.

Why a utility and not a skill:
    Rendering a structured dataclass into HTML is deterministic data
    transformation. Skills are for LLM-driven domain knowledge — there is
    no decision for the LLM to make here. Shipping this as a library
    function keeps the cc-mini skill surface focused on cases where
    progressive disclosure genuinely pays off.

Usage::

    from webqa_cc_mini.runner import run_cc_mini
    from features.report import render_html_report

    result = run_cc_mini(url="https://example.com", user_input="...")
    html_path = render_html_report(
        result,
        output_path="run_report.html",
        title="Smoke test",
        url="https://example.com",
        task="Verify the H1 heading",
    )
    print(f"Report: {html_path}")
"""
from __future__ import annotations

import html
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

# The report is fully self-contained: one <style> block, one dataset,
# no external assets. Keeps the artifact shareable as a single file.
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    --bg: #0f1419; --fg: #e6e6e6; --muted: #8b9098;
    --ok: #4ade80; --err: #f87171; --warn: #facc15;
    --panel: #1a1f28; --border: #2a2f38; --accent: #60a5fa;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui,
                 "PingFang SC", "Microsoft YaHei", sans-serif;
    margin: 0; padding: 24px; background: var(--bg); color: var(--fg);
    line-height: 1.55;
  }}
  h1 {{ font-size: 20px; margin: 0 0 12px; }}
  h2 {{ font-size: 15px; margin: 24px 0 10px; color: var(--muted);
        text-transform: uppercase; letter-spacing: 0.5px; }}
  .meta {{ color: var(--muted); font-size: 13px; margin-bottom: 20px; }}
  .stats {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }}
  .stat {{
    background: var(--panel); border: 1px solid var(--border);
    padding: 10px 14px; border-radius: 6px; min-width: 110px;
  }}
  .stat .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; }}
  .stat .value {{ font-size: 18px; font-weight: 600; margin-top: 2px; }}
  .stat.ok .value {{ color: var(--ok); }}
  .stat.err .value {{ color: var(--err); }}
  .stat.warn .value {{ color: var(--warn); }}
  .panel {{
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 6px; padding: 14px 16px; margin-bottom: 12px;
  }}
  .panel.error {{ border-color: var(--err); }}
  .panel-head {{ display: flex; justify-content: space-between; align-items: center;
                 font-size: 14px; font-weight: 500; margin-bottom: 8px; }}
  .panel-head .tag {{ padding: 2px 8px; border-radius: 4px; font-size: 11px;
                      background: var(--border); color: var(--fg); text-transform: uppercase;
                      letter-spacing: 0.3px; }}
  .panel-head .tag.ok {{ background: #14532d; color: var(--ok); }}
  .panel-head .tag.err {{ background: #7f1d1d; color: var(--err); }}
  pre {{
    font-family: "SF Mono", "Consolas", "Monaco", monospace;
    font-size: 12px; color: var(--fg); background: var(--bg);
    border: 1px solid var(--border); border-radius: 4px;
    padding: 10px 12px; margin: 6px 0 0;
    white-space: pre-wrap; word-break: break-word; overflow-x: auto;
  }}
  .summary {{
    background: var(--panel); border-left: 3px solid var(--accent);
    border-radius: 4px; padding: 12px 16px; margin-bottom: 24px;
    white-space: pre-wrap;
  }}
  .aborted-banner {{
    background: #7f1d1d; color: #fecaca; padding: 10px 14px;
    border-radius: 4px; margin-bottom: 16px; font-weight: 500;
  }}
  details summary {{ cursor: pointer; color: var(--muted); font-size: 12px;
                     margin-top: 4px; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">Generated {generated_at}{context}</div>

{aborted_banner}
<h2>Summary</h2>
<div class="stats">{stats}</div>

{final_text_block}

<h2>Steps ({step_count})</h2>
{steps_html}

</body>
</html>
"""


def render_html_report(
    run_result: Any,
    output_path: str | Path,
    *,
    title: str = 'Web Agent Run',
    url: str | None = None,
    task: str | None = None,
) -> Path:
    """Render a :class:`RunResult` to a self-contained HTML file.

    Args:
        run_result: The ``RunResult`` instance returned by ``run_cc_mini()``.
            Must expose ``final_text``, ``steps``, ``aborted``,
            ``input_tokens``, ``output_tokens``.
        output_path: Destination path (created with parent dirs as needed).
        title: Title rendered at the top and in the <title> tag.
        url: Optional target URL to include in the meta line.
        task: Optional task description to include in the meta line.

    Returns:
        Absolute :class:`Path` of the written HTML file.
    """
    out_path = Path(output_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    raw_steps = getattr(run_result, 'steps', ()) or ()
    steps = raw_steps if isinstance(raw_steps, list) else list(raw_steps)
    aborted = bool(getattr(run_result, 'aborted', False))
    error_steps = sum(1 for s in steps if bool(getattr(s, 'is_error', False)))

    context_parts: list[str] = []
    if url:
        context_parts.append(f'URL: {html.escape(url)}')
    if task:
        context_parts.append(f'Task: {html.escape(task)}')
    context = (' · ' + ' · '.join(context_parts)) if context_parts else ''

    aborted_banner = (
        '<div class="aborted-banner">Run was aborted before completion.</div>'
        if aborted else ''
    )

    stats_html = _render_stats(
        step_count=len(steps),
        error_count=error_steps,
        input_tokens=int(getattr(run_result, 'input_tokens', 0) or 0),
        output_tokens=int(getattr(run_result, 'output_tokens', 0) or 0),
        aborted=aborted,
    )

    final_text = _text_attr(run_result, 'final_text')
    final_text_block = (
        f'<h2>Final message</h2>\n<div class="summary">{html.escape(final_text)}</div>'
        if final_text.strip() else ''
    )

    steps_html = _render_steps(steps) or (
        '<div class="panel"><em>No tool steps were executed.</em></div>'
    )

    html_content = _HTML_TEMPLATE.format(
        title=html.escape(title),
        generated_at=html.escape(datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        context=context,
        aborted_banner=aborted_banner,
        stats=stats_html,
        final_text_block=final_text_block,
        step_count=len(steps),
        steps_html=steps_html,
    )
    out_path.write_text(html_content, encoding='utf-8')
    return out_path


# ---------------------------------------------------------------------------
# Internal rendering helpers
# ---------------------------------------------------------------------------

def _render_stats(
    *,
    step_count: int,
    error_count: int,
    input_tokens: int,
    output_tokens: int,
    aborted: bool,
) -> str:
    status_cls = 'err' if aborted or error_count else 'ok'
    status_text = 'aborted' if aborted else ('errors' if error_count else 'ok')
    tiles = [
        ('', 'Steps', str(step_count)),
        ('err' if error_count else '', 'Errors', str(error_count)),
        (status_cls, 'Status', status_text),
        ('', 'Input tokens', _fmt_int(input_tokens)),
        ('', 'Output tokens', _fmt_int(output_tokens)),
    ]
    return '\n'.join(
        f'<div class="stat {cls}"><div class="label">{html.escape(label)}</div>'
        f'<div class="value">{html.escape(value)}</div></div>'
        for cls, label, value in tiles
    )


def _render_steps(steps: Iterable[Any]) -> str:
    parts: list[str] = []
    for i, step in enumerate(steps, start=1):
        tool = _text_attr(step, 'tool') or 'unknown'
        is_error = bool(getattr(step, 'is_error', False))
        panel_cls = 'panel error' if is_error else 'panel'
        tag_cls = 'tag err' if is_error else 'tag ok'
        tag_text = 'error' if is_error else 'ok'
        input_block = _render_json_block(getattr(step, 'input', {}), 'Input')
        result_text = _text_attr(step, 'result')
        result_block = (
            _render_block(result_text, 'Result', open_=True)
            if result_text else ''
        )
        parts.append(
            f'<div class="{panel_cls}">'
            f'<div class="panel-head"><span>Step {i} · {html.escape(tool)}</span>'
            f'<span class="{tag_cls}">{tag_text}</span></div>'
            f'{input_block}{result_block}'
            f'</div>'
        )
    return '\n'.join(parts)


def _render_block(content: str, label: str, *, open_: bool = False) -> str:
    tag = '<details open>' if open_ else '<details>'
    return (
        f'{tag}<summary>{html.escape(label)}</summary>'
        f'<pre>{html.escape(content)}</pre></details>'
    )


def _render_json_block(data: Any, label: str) -> str:
    try:
        if is_dataclass(data) and not isinstance(data, type):
            data = asdict(data)
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        text = repr(data)
    return _render_block(text, label)


def _text_attr(obj: Any, name: str) -> str:
    val = getattr(obj, name, '')
    return val if isinstance(val, str) else str(val or '')


def _fmt_int(n: int) -> str:
    # Python's comma grouping format is a no-op for |n| < 1000, so a
    # single branch is enough.
    return f'{n:,}'
