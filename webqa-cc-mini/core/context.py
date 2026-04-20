"""System prompt builder for the web agent."""
from __future__ import annotations

from typing import Sequence

from .skill_registry import SkillMetadata


def build_web_agent_system_prompt(
    target_url: str,
    task: str,
    skills: Sequence[SkillMetadata] | None = None,
) -> str:
    base = (
        'You are a web exploration and testing agent.\n\n'
        'You have browser tools via MCP to navigate, inspect DOM, click, fill, '
        'take screenshots, and assert results.\n\n'
        f'## Target\nURL: {target_url}\nTask: {task}\n\n'
        '## Workflow\n'
        '1. Navigate to the target URL.\n'
        '2. Take a snapshot to understand page structure.\n'
        '3. Before each mutating action (click/fill/navigate), gather all\n'
        '   read-only observations you need in a single turn — call snapshot,\n'
        '   screenshot, get_url, and similar tools together; the engine runs\n'
        '   them in parallel.\n'
        '4. Capture screenshots at key checkpoints.\n'
        '5. Summarize findings in your final message and stop (do not call more tools).\n\n'
        '## Rules\n'
        '- Prefer accessibility snapshots over raw HTML.\n'
        '- Batch independent read-only tools (snapshot, screenshot, get_url,\n'
        '  list_*, accessibility_*) in a single response — the engine executes\n'
        '  them concurrently, saving LLM round-trips.\n'
        '- One mutating action at a time (click, fill, navigate, submit); wait\n'
        '  for its result before issuing the next mutation, since each one\n'
        '  changes page state that subsequent observations depend on.\n'
        '- Stop when task is complete OR clearly blocked; do not loop forever.\n'
    )
    if not skills:
        return base
    return base + _format_skills_section(skills)


def _format_skills_section(skills: Sequence[SkillMetadata]) -> str:
    lines = [
        '',
        '## Available skills',
        '',
        'Each skill below is an optional procedure. Call the `load_skill` '
        'tool with a skill name to fetch its detailed instructions *before* '
        'using it. Skip this section entirely if none of the skills match '
        'the current task.',
        '',
    ]
    for sm in skills:
        flat = ' '.join(sm.description.split())
        lines.append(f'- **{sm.name}** — {flat}')
    lines.append('')
    return '\n'.join(lines)
