# SPDX-License-Identifier: Apache-2.0
# Portions adapted from cc-mini (https://github.com/e10nMa2k/cc-mini)
# Original author: e10nMa2k. Modifications © 2026 WebQA Agent contributors.
"""Skill discovery and lazy loading.

A minimal implementation of the Claude Code skill pattern adapted for the
cc-mini engine:

* Skills live in a directory tree rooted at ``skills_dir``.
* Each skill is a subdirectory containing a ``SKILL.md`` file with YAML
  frontmatter (``name`` + ``description`` required).
* At engine start, :meth:`SkillRegistry.discover` parses every frontmatter
  block — cheap, ~100 tokens per skill injected into the system prompt.
* The full SKILL.md body is loaded on demand via
  :meth:`SkillRegistry.load_full_content`, typically invoked by the LLM
  through the ``load_skill`` tool. This is the Progressive Disclosure
  principle — skills scale without inflating every startup.
* **Reference files** (``references/*.md``) extend skills with
  supplementary material. Claude Code loads these via the Read/Bash
  tools; cc-mini lacks general filesystem access, so
  :meth:`SkillRegistry.load_reference` serves the same role, exposed
  to the LLM through the optional ``reference`` parameter of
  ``load_skill``.

The YAML parser is a minimal hand-rolled subset (key-value lines + simple
single-line values) to preserve the zero-dependency property of cc-mini.
Multi-line YAML values, lists, and nested mappings are NOT supported — if
a skill needs richer metadata, put it in the body, not the frontmatter.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SkillMetadata:
    """Lightweight descriptor loaded at discovery time.

    Always loaded — injected into the system prompt. Keep this small.
    """

    name: str
    description: str
    skill_dir: Path
    when_to_use: str = ''
    extra: dict[str, str] = field(default_factory=dict)


class SkillRegistry:
    """Discover and lazy-load skills from a directory tree.

    Lifecycle:
        registry = SkillRegistry(Path("skills"))
        registry.discover()                 # cheap, parses frontmatter only
        registry.list_metadata()            # all discovered skills
        registry.load_full_content("plan")  # lazy, returns SKILL.md body
    """

    SKILL_FILE = 'SKILL.md'

    REFERENCES_DIR = 'references'
    _VALID_REF_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$')

    def __init__(self, skills_dir: Path):
        self.skills_dir = Path(skills_dir)
        self._metadata: dict[str, SkillMetadata] = {}
        self._content_cache: dict[str, str] = {}
        self._ref_cache: dict[tuple[str, str], str] = {}

    def discover(self) -> None:
        """Scan ``skills_dir`` and load frontmatter for every skill.

        Silently skips:
            - Missing ``skills_dir``
            - Subdirectories without ``SKILL.md``
            - Files that fail to parse (logged but not raised)
        """
        self._metadata.clear()
        if not self.skills_dir.exists() or not self.skills_dir.is_dir():
            return
        for child in sorted(self.skills_dir.iterdir()):
            if not child.is_dir():
                continue
            skill_md = child / self.SKILL_FILE
            if not skill_md.is_file():
                continue
            try:
                metadata = self._parse_frontmatter(skill_md)
            except ValueError as exc:
                # Skill has malformed frontmatter — skip rather than break
                # the whole engine start. Log the reason so authors can
                # diagnose "why does my skill not appear" without hunting.
                logger.warning(
                    'Skipping skill %s (invalid frontmatter): %s',
                    child.name,
                    exc,
                )
                continue
            self._metadata[metadata.name] = metadata

    def list_metadata(self) -> list[SkillMetadata]:
        return list(self._metadata.values())

    def has_skill(self, name: str) -> bool:
        return name in self._metadata

    def load_full_content(self, name: str) -> str:
        """Return the full SKILL.md text for *name*, cached after first load.

        Raises:
            KeyError: if *name* is not a discovered skill.
        """
        if name not in self._metadata:
            raise KeyError(f'unknown skill: {name}')
        if name not in self._content_cache:
            md_path = self._metadata[name].skill_dir / self.SKILL_FILE
            self._content_cache[name] = md_path.read_text(encoding='utf-8')
        return self._content_cache[name]

    def list_references(self, skill_name: str) -> list[str]:
        """Return sorted reference names (without ``.md``) for *skill_name*.

        Returns an empty list when the skill has no ``references/``
        subdirectory. Raises :exc:`KeyError` for unknown skills.
        """
        if skill_name not in self._metadata:
            raise KeyError(f'unknown skill: {skill_name}')
        ref_dir = self._metadata[skill_name].skill_dir / self.REFERENCES_DIR
        if not ref_dir.is_dir():
            return []
        return sorted(
            p.stem for p in ref_dir.iterdir()
            if p.is_file() and p.suffix == '.md'
        )

    def load_reference(self, skill_name: str, ref_name: str) -> str:
        """Load a single reference file from *skill_name*'s references dir.

        Raises:
            KeyError: if *skill_name* is not a discovered skill.
            ValueError: if *ref_name* fails validation.
            FileNotFoundError: if the reference file does not exist.
        """
        if skill_name not in self._metadata:
            raise KeyError(f'unknown skill: {skill_name}')
        if not self._VALID_REF_NAME.match(ref_name):
            raise ValueError(
                f'invalid reference name: {ref_name!r} '
                f'(must match [A-Za-z0-9][A-Za-z0-9_-]{{0,127}})'
            )

        cache_key = (skill_name, ref_name)
        if cache_key in self._ref_cache:
            return self._ref_cache[cache_key]

        ref_path = (
            self._metadata[skill_name].skill_dir
            / self.REFERENCES_DIR
            / f'{ref_name}.md'
        )
        if not ref_path.is_file():
            raise FileNotFoundError(f'reference not found: {ref_name}')
        content = ref_path.read_text(encoding='utf-8')
        self._ref_cache[cache_key] = content
        return content

    def get_skill_dir(self, name: str) -> Path:
        if name not in self._metadata:
            raise KeyError(f'unknown skill: {name}')
        return self._metadata[name].skill_dir

    # ------------------------------------------------------------------
    # Frontmatter parsing — intentionally minimal
    # ------------------------------------------------------------------

    def _parse_frontmatter(self, skill_md: Path) -> SkillMetadata:
        text = skill_md.read_text(encoding='utf-8')
        if not text.startswith('---'):
            raise ValueError(f'{skill_md}: missing YAML frontmatter')
        # Find the closing --- on its own line.
        # Accept both "---\n" opener and later "---" on own line.
        lines = text.splitlines()
        if not lines or lines[0].strip() != '---':
            raise ValueError(f'{skill_md}: frontmatter must start with --- on line 1')
        end_idx = next(
            (i for i, line in enumerate(lines[1:], start=1)
             if line.strip() == '---'),
            None,
        )
        if end_idx is None:
            raise ValueError(f'{skill_md}: unterminated frontmatter')

        fields: dict[str, str] = {}
        for raw in lines[1:end_idx]:
            line = raw.rstrip()
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            if ':' not in line:
                continue  # skip continuation / list lines silently
            key, _, value = line.partition(':')
            key = key.strip()
            value = value.strip()
            # Strip surrounding quotes if present.
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            # Reject obvious multi-line block indicators. The parser does not
            # support them, and accepting them silently would store the raw
            # '|' / '>' character as the field value.
            if value in ('|', '>', '|-', '>-', '|+', '>+'):
                raise ValueError(
                    f'{skill_md}: key {key!r} uses unsupported multi-line block '
                    f'syntax ({value!r}); use a single-line value instead'
                )
            fields[key] = value

        name = fields.pop('name', None)
        description = fields.pop('description', None)
        if not name or not description:
            raise ValueError(f'{skill_md}: frontmatter requires name + description')
        when_to_use = fields.pop('when_to_use', '')
        return SkillMetadata(
            name=name,
            description=description,
            skill_dir=skill_md.parent,
            when_to_use=when_to_use,
            extra=fields,
        )
