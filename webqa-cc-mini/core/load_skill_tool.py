"""The ``load_skill`` tool — LLM-side entry point for Progressive Disclosure.

At engine start, :class:`SkillRegistry` injects a short summary of every
discovered skill into the system prompt (name + one-line description).
When the LLM decides a skill is relevant, it calls this tool to fetch the
full SKILL.md body (detailed instructions, examples, decision guides).

Why this design:
    * Keeps the system prompt stable and small — adding skills does not
      inflate every API call's input_tokens.
    * The full skill body only enters context on demand, once, when needed.
    * Scripts inside the skill directory can be invoked via whatever
      execute-code tools the engine is configured with; this tool just
      surfaces the instructions.
"""
from __future__ import annotations

import re

from .skill_registry import SkillRegistry
from .tool import Tool, ToolResult

# Defensive regex for skill_name values coming from the LLM. Discovered
# skill names are filesystem directory names — restricting to this
# character class also prevents path-traversal attempts like '../..' even
# though the registry is a dict lookup today.
_VALID_SKILL_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')


class LoadSkillTool(Tool):
    """Let the LLM load a skill's full SKILL.md body on demand."""

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    @property
    def name(self) -> str:
        return 'load_skill'

    @property
    def description(self) -> str:
        return (
            'Load the full instructions for a named skill. The system prompt '
            'lists available skills with short descriptions; call this tool '
            'to retrieve the detailed procedure, decision guide, and examples '
            'for one specific skill before using it.'
        )

    @property
    def input_schema(self) -> dict:
        return {
            'type': 'object',
            'properties': {
                'skill_name': {
                    'type': 'string',
                    'description': (
                        'Name of the skill to load, as listed in the system '
                        'prompt skills section.'
                    ),
                },
            },
            'required': ['skill_name'],
        }

    def is_read_only(self) -> bool:
        return True

    def get_activity_description(self, **kwargs) -> str | None:
        skill_name = kwargs.get('skill_name', '?')
        return f'Loading skill: {skill_name}'

    def execute(self, **kwargs) -> ToolResult:
        skill_name = kwargs.get('skill_name', '').strip()
        if not skill_name:
            return ToolResult(
                content='[FAILURE: missing skill_name argument]',
                is_error=True,
            )
        if not _VALID_SKILL_NAME.match(skill_name):
            return ToolResult(
                content=(
                    f'[FAILURE: invalid skill_name {skill_name!r}] '
                    f'Skill names must match [A-Za-z0-9][A-Za-z0-9_-]{{0,63}}'
                ),
                is_error=True,
            )
        try:
            body = self._registry.load_full_content(skill_name)
        except KeyError:
            available = ', '.join(
                m.name for m in self._registry.list_metadata()
            ) or '(none)'
            return ToolResult(
                content=(
                    f'[FAILURE: unknown skill {skill_name!r}]\n'
                    f'Available skills: {available}'
                ),
                is_error=True,
            )
        except OSError as exc:
            return ToolResult(
                content=f'[FAILURE: could not read skill file] {exc}',
                is_error=True,
            )
        return ToolResult(content=body, is_error=False)
