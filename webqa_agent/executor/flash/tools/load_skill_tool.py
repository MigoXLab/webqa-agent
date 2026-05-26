"""The ``load_skill`` tool — LLM-side entry point for Progressive Disclosure.

At engine start, :class:`SkillRegistry` injects a short summary of every
discovered skill into the system prompt (name + one-line description).
When the LLM decides a skill is relevant, it calls this tool to fetch the
full SKILL.md body (detailed instructions, examples, decision guides).

Skills may bundle supplementary **reference files** under a ``references/``
subdirectory. The optional ``reference`` parameter lets the LLM load a
single reference file on demand — the third tier of progressive disclosure.
The SKILL.md body lists available references so the LLM knows what to ask
for without inflating the system prompt.

Why this design:
    * Keeps the system prompt stable and small — adding skills does not
      inflate every API call's input_tokens.
    * The full skill body only enters context on demand, once, when needed.
    * Reference files are loaded individually, only when a specific
      procedure step calls for them.
    * Scripts inside the skill directory can be invoked via whatever
      execute-code tools the engine is configured with; this tool just
      surfaces the instructions.
"""
from __future__ import annotations

import re

from ..core.skill_registry import SkillRegistry
from ..core.tool import Tool, ToolResult

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
            'Load a skill or one of its reference files. Call with just '
            'skill_name to get the full SKILL.md instructions. Add the '
            'optional reference parameter to load a specific reference '
            'file listed in the skill body (e.g. reference="27-patterns-'
            'accessibility"). The system prompt lists available skills '
            'with short descriptions.'
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
                'reference': {
                    'type': 'string',
                    'description': (
                        'Optional. Name of a reference file to load from '
                        'the skill\'s references/ directory (without .md '
                        'extension). When omitted, the full SKILL.md body '
                        'is returned instead.'
                    ),
                },
            },
            'required': ['skill_name'],
        }

    def is_read_only(self) -> bool:
        return True

    def get_activity_description(self, **kwargs) -> str | None:
        skill_name = kwargs.get('skill_name', '?')
        ref = kwargs.get('reference')
        if ref:
            return f'Loading skill reference: {skill_name}/{ref}'
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

        ref_name = (kwargs.get('reference') or '').strip()

        if ref_name:
            return self._load_reference(skill_name, ref_name)
        return self._load_body(skill_name)

    def _unknown_skill_error(self, skill_name: str) -> ToolResult:
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

    def _load_body(self, skill_name: str) -> ToolResult:
        try:
            body = self._registry.load_full_content(skill_name)
        except KeyError:
            return self._unknown_skill_error(skill_name)
        except OSError as exc:
            return ToolResult(
                content=f'[FAILURE: could not read skill file] {exc}',
                is_error=True,
            )
        return ToolResult(content=body, is_error=False)

    def _load_reference(self, skill_name: str, ref_name: str) -> ToolResult:
        if not _VALID_SKILL_NAME.match(ref_name):
            return ToolResult(
                content=(
                    f'[FAILURE: invalid reference name {ref_name!r}] '
                    f'Reference names must match [A-Za-z0-9][A-Za-z0-9_-]{{0,63}}'
                ),
                is_error=True,
            )
        try:
            content = self._registry.load_reference(skill_name, ref_name)
        except KeyError:
            return self._unknown_skill_error(skill_name)
        except ValueError as exc:
            return ToolResult(content=f'[FAILURE] {exc}', is_error=True)
        except FileNotFoundError:
            available_refs = self._registry.list_references(skill_name)
            refs_str = ', '.join(available_refs) if available_refs else '(none)'
            return ToolResult(
                content=(
                    f'[FAILURE: reference {ref_name!r} not found in '
                    f'skill {skill_name!r}]\n'
                    f'Available references: {refs_str}'
                ),
                is_error=True,
            )
        except OSError as exc:
            return ToolResult(
                content=f'[FAILURE: could not read reference file] {exc}',
                is_error=True,
            )
        return ToolResult(content=content, is_error=False)
