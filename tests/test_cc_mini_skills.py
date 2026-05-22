"""Tests for the cc-mini skills infrastructure.

Covers:
* :class:`SkillRegistry` — frontmatter parsing, discovery, lazy loading
* :class:`LoadSkillTool` — tool contract, error cases, caching
* :func:`build_web_agent_system_prompt` — skill-metadata injection
"""
from __future__ import annotations

from pathlib import Path

import pytest

from webqa_agent.executor.flash.core.context import \
    build_web_agent_system_prompt
from webqa_agent.executor.flash.core.skill_registry import (SkillMetadata,
                                                            SkillRegistry)
from webqa_agent.executor.flash.tools.load_skill_tool import LoadSkillTool

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_skill(root: Path, name: str, *, description: str = 'Test skill.',
                 body: str = '# Body\n', extra_fm: str = '') -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    fm = f'name: {name}\ndescription: {description}\n'
    if extra_fm:
        fm += extra_fm
    (skill_dir / 'SKILL.md').write_text(f'---\n{fm}---\n\n{body}', encoding='utf-8')
    return skill_dir


# ---------------------------------------------------------------------------
# SkillRegistry.discover
# ---------------------------------------------------------------------------

class TestSkillRegistryDiscover:
    def test_missing_directory_is_silent_no_op(self, tmp_path):
        reg = SkillRegistry(tmp_path / 'does-not-exist')
        reg.discover()
        assert reg.list_metadata() == []

    def test_empty_directory_yields_no_skills(self, tmp_path):
        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert reg.list_metadata() == []

    def test_single_skill_discovered(self, tmp_path):
        _write_skill(tmp_path, 'plan', description='Plan tests.')
        reg = SkillRegistry(tmp_path)
        reg.discover()
        metas = reg.list_metadata()
        assert len(metas) == 1
        assert metas[0].name == 'plan'
        assert metas[0].description == 'Plan tests.'

    def test_multiple_skills_sorted_alphabetically(self, tmp_path):
        _write_skill(tmp_path, 'zzz', description='Z.')
        _write_skill(tmp_path, 'aaa', description='A.')
        _write_skill(tmp_path, 'mmm', description='M.')
        reg = SkillRegistry(tmp_path)
        reg.discover()
        names = [m.name for m in reg.list_metadata()]
        assert names == ['aaa', 'mmm', 'zzz']

    def test_subdirectory_without_skill_md_is_skipped(self, tmp_path):
        _write_skill(tmp_path, 'valid')
        (tmp_path / 'no-skill-file').mkdir()
        reg = SkillRegistry(tmp_path)
        reg.discover()
        names = [m.name for m in reg.list_metadata()]
        assert names == ['valid']

    def test_malformed_frontmatter_skipped(self, tmp_path):
        _write_skill(tmp_path, 'good')
        bad = tmp_path / 'bad'
        bad.mkdir()
        (bad / 'SKILL.md').write_text('no frontmatter here', encoding='utf-8')
        reg = SkillRegistry(tmp_path)
        reg.discover()
        names = [m.name for m in reg.list_metadata()]
        assert names == ['good']  # bad silently skipped

    def test_missing_required_fields_skipped(self, tmp_path):
        # Missing 'description'
        partial = tmp_path / 'partial'
        partial.mkdir()
        (partial / 'SKILL.md').write_text(
            '---\nname: partial\n---\n\nbody', encoding='utf-8'
        )
        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert reg.list_metadata() == []

    def test_multiline_block_scalar_is_rejected(self, tmp_path):
        """description: | must be rejected (parser doesn't support blocks)."""
        bad = tmp_path / 'multi'
        bad.mkdir()
        (bad / 'SKILL.md').write_text(
            '---\nname: multi\ndescription: |\n  line one\n  line two\n---\n',
            encoding='utf-8',
        )
        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert reg.list_metadata() == []

    def test_malformed_frontmatter_emits_warning(self, tmp_path, caplog):
        bad = tmp_path / 'broken'
        bad.mkdir()
        (bad / 'SKILL.md').write_text('---\nname: broken\n---\n', encoding='utf-8')
        reg = SkillRegistry(tmp_path)
        with caplog.at_level('WARNING'):
            reg.discover()
        assert any('Skipping skill' in rec.message for rec in caplog.records)

    def test_when_to_use_is_recognized(self, tmp_path):
        _write_skill(
            tmp_path, 'planner',
            extra_fm='when_to_use: Use when user requests structured plans.\n',
        )
        reg = SkillRegistry(tmp_path)
        reg.discover()
        meta = reg.list_metadata()[0]
        assert meta.when_to_use == 'Use when user requests structured plans.'
        # when_to_use is NOT bucketed into extra.
        assert 'when_to_use' not in meta.extra

    def test_quoted_values_unquoted(self, tmp_path):
        _write_skill(
            tmp_path, 'quoted',
            extra_fm='author: "John Doe"\nversion: \'1.0\'\n'
        )
        reg = SkillRegistry(tmp_path)
        reg.discover()
        meta = reg.list_metadata()[0]
        assert meta.extra['author'] == 'John Doe'
        assert meta.extra['version'] == '1.0'

    def test_rediscovery_replaces_cached_metadata(self, tmp_path):
        _write_skill(tmp_path, 's', description='original')
        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert reg.list_metadata()[0].description == 'original'

        _write_skill(tmp_path, 's', description='updated')
        reg.discover()
        assert reg.list_metadata()[0].description == 'updated'


# ---------------------------------------------------------------------------
# SkillRegistry lazy loading
# ---------------------------------------------------------------------------

class TestSkillRegistryLazyLoad:
    def test_load_full_content_returns_body(self, tmp_path):
        _write_skill(tmp_path, 'demo', body='# Demo\n\nFull instructions here.')
        reg = SkillRegistry(tmp_path)
        reg.discover()
        body = reg.load_full_content('demo')
        assert '# Demo' in body
        assert 'Full instructions here' in body

    def test_load_unknown_skill_raises_keyerror(self, tmp_path):
        reg = SkillRegistry(tmp_path)
        reg.discover()
        with pytest.raises(KeyError):
            reg.load_full_content('nonexistent')

    def test_content_cached_after_first_load(self, tmp_path):
        skill_dir = _write_skill(tmp_path, 'cached')
        reg = SkillRegistry(tmp_path)
        reg.discover()
        first = reg.load_full_content('cached')

        # Delete the file — cached load should still work
        (skill_dir / 'SKILL.md').unlink()
        second = reg.load_full_content('cached')
        assert first == second

    def test_get_skill_dir_returns_correct_path(self, tmp_path):
        _write_skill(tmp_path, 'x')
        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert reg.get_skill_dir('x') == tmp_path / 'x'

    def test_has_skill(self, tmp_path):
        _write_skill(tmp_path, 'known')
        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert reg.has_skill('known')
        assert not reg.has_skill('unknown')


# ---------------------------------------------------------------------------
# LoadSkillTool
# ---------------------------------------------------------------------------

class TestLoadSkillTool:
    def test_tool_metadata_matches_contract(self, tmp_path):
        reg = SkillRegistry(tmp_path)
        reg.discover()
        tool = LoadSkillTool(reg)
        assert tool.name == 'load_skill'
        assert isinstance(tool.description, str) and tool.description
        assert tool.is_read_only() is True
        schema = tool.input_schema
        assert schema['type'] == 'object'
        assert 'skill_name' in schema['properties']
        assert schema['required'] == ['skill_name']

    def test_execute_returns_skill_body(self, tmp_path):
        _write_skill(tmp_path, 's', body='full body xyz')
        reg = SkillRegistry(tmp_path)
        reg.discover()
        tool = LoadSkillTool(reg)
        result = tool.execute(skill_name='s')
        assert not result.is_error
        assert 'full body xyz' in result.content

    def test_execute_unknown_skill_lists_available(self, tmp_path):
        _write_skill(tmp_path, 'alpha')
        _write_skill(tmp_path, 'beta')
        reg = SkillRegistry(tmp_path)
        reg.discover()
        result = LoadSkillTool(reg).execute(skill_name='missing')
        assert result.is_error
        assert 'missing' in result.content
        assert 'alpha' in result.content and 'beta' in result.content

    def test_execute_missing_argument_is_error(self, tmp_path):
        reg = SkillRegistry(tmp_path)
        reg.discover()
        result = LoadSkillTool(reg).execute()
        assert result.is_error
        assert 'missing skill_name' in result.content

    def test_execute_empty_argument_is_error(self, tmp_path):
        reg = SkillRegistry(tmp_path)
        reg.discover()
        result = LoadSkillTool(reg).execute(skill_name='   ')
        assert result.is_error

    @pytest.mark.parametrize('bad_name', [
        '../etc/passwd',
        'a/b',
        'name with space',
        '!malicious',
        '-leading-dash',
        'x' * 100,  # too long
    ])
    def test_execute_rejects_invalid_skill_names(self, tmp_path, bad_name):
        reg = SkillRegistry(tmp_path)
        reg.discover()
        result = LoadSkillTool(reg).execute(skill_name=bad_name)
        assert result.is_error
        assert 'invalid skill_name' in result.content

    def test_activity_description_mentions_skill_name(self, tmp_path):
        reg = SkillRegistry(tmp_path)
        tool = LoadSkillTool(reg)
        desc = tool.get_activity_description(skill_name='my-skill')
        assert desc is not None
        assert 'my-skill' in desc

    def test_api_schema_shape(self, tmp_path):
        reg = SkillRegistry(tmp_path)
        tool = LoadSkillTool(reg)
        schema = tool.to_api_schema()
        assert schema['name'] == 'load_skill'
        assert 'description' in schema
        assert 'input_schema' in schema


# ---------------------------------------------------------------------------
# SkillRegistry reference files
# ---------------------------------------------------------------------------


def _write_skill_with_refs(
    root: Path, name: str, refs: dict[str, str], *,
    description: str = 'Test skill.', body: str = '# Body\n',
) -> Path:
    skill_dir = _write_skill(root, name, description=description, body=body)
    ref_dir = skill_dir / 'references'
    ref_dir.mkdir(exist_ok=True)
    for ref_name, content in refs.items():
        (ref_dir / f'{ref_name}.md').write_text(content, encoding='utf-8')
    return skill_dir


class TestSkillRegistryReferences:
    def test_list_references_returns_sorted_names(self, tmp_path):
        _write_skill_with_refs(tmp_path, 's', {
            'zzz-nav': 'nav content',
            'aaa-access': 'access content',
            'mmm-style': 'style content',
        })
        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert reg.list_references('s') == ['aaa-access', 'mmm-style', 'zzz-nav']

    def test_list_references_empty_when_no_dir(self, tmp_path):
        _write_skill(tmp_path, 's')
        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert reg.list_references('s') == []

    def test_list_references_unknown_skill_raises(self, tmp_path):
        reg = SkillRegistry(tmp_path)
        reg.discover()
        with pytest.raises(KeyError):
            reg.list_references('nonexistent')

    def test_list_references_ignores_non_md_files(self, tmp_path):
        skill_dir = _write_skill_with_refs(tmp_path, 's', {'valid': 'ok'})
        (skill_dir / 'references' / 'readme.txt').write_text('skip me')
        (skill_dir / 'references' / 'data.json').write_text('{}')
        reg = SkillRegistry(tmp_path)
        reg.discover()
        assert reg.list_references('s') == ['valid']

    def test_load_reference_returns_content(self, tmp_path):
        _write_skill_with_refs(tmp_path, 's', {
            '27-patterns-accessibility': '# Accessibility\nKeyboard nav...',
        })
        reg = SkillRegistry(tmp_path)
        reg.discover()
        content = reg.load_reference('s', '27-patterns-accessibility')
        assert '# Accessibility' in content
        assert 'Keyboard nav' in content

    def test_load_reference_cached(self, tmp_path):
        skill_dir = _write_skill_with_refs(tmp_path, 's', {'cached-ref': 'data'})
        reg = SkillRegistry(tmp_path)
        reg.discover()
        first = reg.load_reference('s', 'cached-ref')
        (skill_dir / 'references' / 'cached-ref.md').unlink()
        second = reg.load_reference('s', 'cached-ref')
        assert first == second

    def test_load_reference_unknown_skill_raises(self, tmp_path):
        reg = SkillRegistry(tmp_path)
        reg.discover()
        with pytest.raises(KeyError):
            reg.load_reference('ghost', 'any')

    def test_load_reference_missing_file_raises(self, tmp_path):
        _write_skill_with_refs(tmp_path, 's', {'exists': 'ok'})
        reg = SkillRegistry(tmp_path)
        reg.discover()
        with pytest.raises(FileNotFoundError):
            reg.load_reference('s', 'does-not-exist')

    @pytest.mark.parametrize('bad_name', [
        '../etc/passwd',
        'a/b',
        'name with space',
        '!malicious',
        '-leading-dash',
    ])
    def test_load_reference_rejects_path_traversal(self, tmp_path, bad_name):
        _write_skill_with_refs(tmp_path, 's', {'ok': 'fine'})
        reg = SkillRegistry(tmp_path)
        reg.discover()
        with pytest.raises(ValueError, match='invalid reference name'):
            reg.load_reference('s', bad_name)


# ---------------------------------------------------------------------------
# LoadSkillTool — reference parameter
# ---------------------------------------------------------------------------

class TestLoadSkillToolReference:
    def test_schema_has_optional_reference(self, tmp_path):
        reg = SkillRegistry(tmp_path)
        tool = LoadSkillTool(reg)
        schema = tool.input_schema
        assert 'reference' in schema['properties']
        assert 'reference' not in schema.get('required', [])

    def test_execute_with_reference_returns_content(self, tmp_path):
        _write_skill_with_refs(tmp_path, 's', {'my-ref': '# Reference\nContent.'})
        reg = SkillRegistry(tmp_path)
        reg.discover()
        result = LoadSkillTool(reg).execute(skill_name='s', reference='my-ref')
        assert not result.is_error
        assert '# Reference' in result.content

    def test_execute_without_reference_returns_body(self, tmp_path):
        _write_skill_with_refs(tmp_path, 's', {'ref': 'ref content'},
                               body='# Body content')
        reg = SkillRegistry(tmp_path)
        reg.discover()
        result = LoadSkillTool(reg).execute(skill_name='s')
        assert not result.is_error
        assert '# Body content' in result.content
        assert 'ref content' not in result.content

    def test_execute_missing_reference_lists_available(self, tmp_path):
        _write_skill_with_refs(tmp_path, 's', {
            'alpha-ref': 'a', 'beta-ref': 'b',
        })
        reg = SkillRegistry(tmp_path)
        reg.discover()
        result = LoadSkillTool(reg).execute(skill_name='s', reference='missing')
        assert result.is_error
        assert 'alpha-ref' in result.content
        assert 'beta-ref' in result.content

    def test_execute_invalid_reference_name_rejects(self, tmp_path):
        _write_skill_with_refs(tmp_path, 's', {'ok': 'fine'})
        reg = SkillRegistry(tmp_path)
        reg.discover()
        result = LoadSkillTool(reg).execute(
            skill_name='s', reference='../evil',
        )
        assert result.is_error
        assert 'invalid reference name' in result.content

    def test_activity_description_includes_reference(self, tmp_path):
        reg = SkillRegistry(tmp_path)
        tool = LoadSkillTool(reg)
        desc = tool.get_activity_description(
            skill_name='ui-audit', reference='27-patterns-accessibility',
        )
        assert 'ui-audit/27-patterns-accessibility' in desc


# ---------------------------------------------------------------------------
# System prompt injection
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Real skills in webqa-cc-mini/skills/ — integration smoke tests
# ---------------------------------------------------------------------------

_REAL_SKILLS_DIR = Path(__file__).resolve().parent.parent / 'webqa_agent' / 'executor' / 'flash' / 'skills'


class TestPlanSkillIntegration:
    @pytest.fixture()
    def reg(self):
        if not _REAL_SKILLS_DIR.is_dir():
            pytest.skip('webqa-cc-mini/skills/ not found')
        r = SkillRegistry(_REAL_SKILLS_DIR)
        r.discover()
        return r

    def test_plan_skill_discovered(self, reg):
        names = [m.name for m in reg.list_metadata()]
        assert 'plan' in names

    def test_plan_skill_has_no_references(self, reg):
        refs = reg.list_references('plan')
        assert refs == []

    def test_plan_skill_body_contains_key_sections(self, reg):
        body = reg.load_full_content('plan')
        for section in (
            'Planning Phases',
            'Observation Batching',
            'Re-planning',
            'Completion',
            'Error Handling',
        ):
            assert section in body, f'missing section: {section}'

    def test_plan_skill_has_completion_checkpoints(self, reg):
        body = reg.load_full_content('plan')
        assert 'Completion Checkpoints' in body or 'completion condition' in body.lower()

    def test_plan_error_handling_references_recovery(self, reg):
        body = reg.load_full_content('plan')
        assert 'load_skill(skill_name="recovery")' in body

    def test_plan_no_longer_has_error_taxonomy_reference(self, reg):
        refs = reg.list_references('plan')
        assert 'error-taxonomy' not in refs


# ---------------------------------------------------------------------------
# Real recovery skill in webqa-cc-mini/skills/ — integration smoke tests
# ---------------------------------------------------------------------------

class TestRecoverySkillIntegration:
    @pytest.fixture()
    def reg(self):
        if not _REAL_SKILLS_DIR.is_dir():
            pytest.skip('webqa-cc-mini/skills/ not found')
        r = SkillRegistry(_REAL_SKILLS_DIR)
        r.discover()
        return r

    def test_recovery_skill_discovered(self, reg):
        names = [m.name for m in reg.list_metadata()]
        assert 'recovery' in names

    def test_recovery_skill_has_when_to_use(self, reg):
        meta = next(m for m in reg.list_metadata() if m.name == 'recovery')
        assert meta.when_to_use
        assert 'error' in meta.when_to_use.lower()

    def test_recovery_skill_references(self, reg):
        refs = reg.list_references('recovery')
        assert 'error-taxonomy' in refs
        assert 'recovery-strategies' in refs
        assert 'verification-patterns' in refs

    def test_recovery_skill_body_contains_key_sections(self, reg):
        body = reg.load_full_content('recovery')
        for section in (
            'When to Use',
            'OBSERVE',
            'DIAGNOSE',
            'RECOVER',
            'Loop Control',
        ):
            assert section in body, f'missing section: {section}'

    def test_recovery_error_taxonomy_loadable(self, reg):
        content = reg.load_reference('recovery', 'error-taxonomy')
        assert 'ELEMENT_NOT_FOUND' in content
        assert 'ACTION_INEFFECTIVE' in content
        assert 'PAGE_CRASHED' in content

    def test_recovery_strategies_loadable(self, reg):
        content = reg.load_reference('recovery', 'recovery-strategies')
        assert 'Re-observe' in content
        assert 'evaluate_script' in content
        assert 'Escalation' in content or 'escalat' in content.lower()


# ---------------------------------------------------------------------------
# System prompt injection
# ---------------------------------------------------------------------------

class TestSystemPromptSkillInjection:
    def test_no_skills_omits_section(self):
        prompt = build_web_agent_system_prompt('https://x', 'do things')
        assert '## Available Skills' not in prompt

    def test_empty_skills_list_omits_section(self):
        prompt = build_web_agent_system_prompt('https://x', 'do things', skills=[])
        assert '## Available Skills' not in prompt

    def test_skill_metadata_injected(self, tmp_path):
        metas = [
            SkillMetadata(name='plan', description='Plan things.', skill_dir=tmp_path),
            SkillMetadata(name='report', description='Render reports.', skill_dir=tmp_path),
        ]
        prompt = build_web_agent_system_prompt('https://x', 'task', skills=metas)
        assert '## Available Skills' in prompt
        assert '**plan**' in prompt and 'Plan things.' in prompt
        assert '**report**' in prompt and 'Render reports.' in prompt
        assert 'load_skill' in prompt

    def test_prompt_has_identity_and_methodology(self):
        prompt = build_web_agent_system_prompt('https://x', 'test search')
        assert 'web testing specialist' in prompt
        assert '## Mission' in prompt
        assert '## Methodology' in prompt
        assert '## Quality Standards' in prompt
        assert '## Final Report Format' in prompt

    def test_prompt_lists_capability_categories(self):
        prompt = build_web_agent_system_prompt('https://x', 'test search')
        for capability in (
            'list_console_messages', 'list_network_requests',
            'evaluate_script', 'lighthouse_audit', 'wait_for', 'verify',
        ):
            assert capability in prompt, f'missing capability: {capability}'

    def test_prompt_describes_risk_based_verification_strategy(self):
        prompt = build_web_agent_system_prompt('https://x', 'test search')
        assert 'Deterministic checks first' in prompt
        assert 'Use `verify(assertion="...")` when the conclusion is ambiguous' in prompt
        assert 'If you want to report **passed** after any timeout' in prompt
        assert 'call `verify` once for the primary success assertion or downgrade to warning' in prompt

    def test_prompt_omits_verify_when_has_verify_tool_false(self):
        prompt = build_web_agent_system_prompt(
            'https://x', 'test search', has_verify_tool=False,
        )
        assert 'Independent verification' not in prompt
        assert 'verify(assertion=' not in prompt
        assert 'call `verify`' not in prompt
        assert 'Risk-based final assessment' in prompt

    def test_skill_section_encourages_loading(self, tmp_path):
        metas = [SkillMetadata(name='s', description='d.', skill_dir=tmp_path)]
        prompt = build_web_agent_system_prompt('u', 't', skills=metas)
        skill_section = prompt.split('## Available Skills', 1)[1]
        assert 'BEFORE starting' in skill_section
        assert 'Skip' not in skill_section

    def test_plan_skill_referenced_in_methodology_when_available(self, tmp_path):
        metas = [SkillMetadata(name='plan', description='Plan.', skill_dir=tmp_path)]
        prompt = build_web_agent_system_prompt('u', 't', skills=metas)
        assert 'load the `plan` skill' in prompt

    def test_no_plan_reference_when_plan_skill_absent(self, tmp_path):
        metas = [SkillMetadata(name='other', description='Other.', skill_dir=tmp_path)]
        prompt = build_web_agent_system_prompt('u', 't', skills=metas)
        assert 'load the `plan` skill' not in prompt
        assert 'outline your approach' in prompt

    def test_no_plan_reference_when_no_skills(self):
        prompt = build_web_agent_system_prompt('u', 't')
        assert 'load the `plan` skill' not in prompt
        assert 'outline your approach' in prompt

    def test_multiline_description_flattened(self, tmp_path):
        metas = [SkillMetadata(
            name='multi',
            description='Line one.\nLine two.\n\nLine three.',
            skill_dir=tmp_path,
        )]
        prompt = build_web_agent_system_prompt('u', 't', skills=metas)
        # The rendered line for this skill must be on one logical line
        skill_lines = [line for line in prompt.splitlines() if '**multi**' in line]
        assert len(skill_lines) == 1
        assert '\n' not in skill_lines[0]
        assert 'Line one. Line two. Line three.' in skill_lines[0]

    def test_when_to_use_appended_when_present(self, tmp_path):
        metas = [SkillMetadata(
            name='plan',
            description='Generate test cases.',
            skill_dir=tmp_path,
            when_to_use='when user asks for a structured plan',
        )]
        prompt = build_web_agent_system_prompt('u', 't', skills=metas)
        bullet = next(line for line in prompt.splitlines() if '**plan**' in line)
        assert 'Generate test cases.' in bullet
        assert '(when user asks for a structured plan)' in bullet

    def test_when_to_use_omitted_when_blank(self, tmp_path):
        metas = [SkillMetadata(
            name='plan',
            description='Generate test cases.',
            skill_dir=tmp_path,
            when_to_use='',
        )]
        prompt = build_web_agent_system_prompt('u', 't', skills=metas)
        bullet = next(line for line in prompt.splitlines() if '**plan**' in line)
        # No trailing parenthetical when when_to_use is empty
        assert bullet.rstrip().endswith('Generate test cases.')


# ---------------------------------------------------------------------------
# System prompt verification methodology
# ---------------------------------------------------------------------------

class TestSystemPromptVerification:
    """Verify post-action verification methodology is present in prompt."""

    def test_step4_contains_outcome_comparison(self):
        prompt = build_web_agent_system_prompt('https://x', 'test')
        assert 'compare the actual outcome against what you expected' in prompt.lower() or \
               'compare the actual' in prompt.lower()

    def test_semantic_failure_coverage(self):
        prompt = build_web_agent_system_prompt('https://x', 'test')
        assert 'does not guarantee the intended effect' in prompt

    def test_anomalous_check_coverage(self):
        prompt = build_web_agent_system_prompt('https://x', 'test')
        assert 'anomalously fast' in prompt

    def test_recovery_protocol_embedded(self):
        prompt = build_web_agent_system_prompt('https://x', 'test')
        assert '### Recovery Protocol' in prompt
        assert 'Re-observe' in prompt
        assert 'Diagnose' in prompt
        assert 'escalation ladder' in prompt.lower()

    def test_recovery_protocol_references_skill_when_available(self, tmp_path):
        metas = [SkillMetadata(name='recovery', description='d.', skill_dir=tmp_path)]
        prompt = build_web_agent_system_prompt('u', 't', skills=metas)
        assert 'load_skill(skill_name="recovery")' in prompt

    def test_recovery_protocol_omits_skill_when_unavailable(self):
        prompt = build_web_agent_system_prompt('https://x', 'test')
        assert 'load_skill(skill_name="recovery")' not in prompt
