"""Tests for webqa_agent.executor.flash features/report.py."""
from __future__ import annotations

from dataclasses import dataclass, field

from webqa_agent.executor.flash.features.report import render_html_report


@dataclass
class _Step:
    tool: str = 'nav'
    input: dict = field(default_factory=dict)
    result: str = 'ok'
    is_error: bool = False


@dataclass
class _RunResult:
    final_text: str = ''
    steps: list = field(default_factory=list)
    aborted: bool = False
    input_tokens: int = 0
    output_tokens: int = 0


# ---------------------------------------------------------------------------
# Core rendering
# ---------------------------------------------------------------------------

class TestRenderBasic:
    def test_empty_result_produces_valid_html(self, tmp_path):
        path = render_html_report(_RunResult(), tmp_path / 'report.html')
        content = path.read_text(encoding='utf-8')
        assert content.startswith('<!DOCTYPE html>')
        assert content.rstrip().endswith('</html>')
        assert 'No tool steps were executed' in content

    def test_output_path_resolved_to_absolute(self, tmp_path):
        rel = tmp_path / 'sub' / 'report.html'
        path = render_html_report(_RunResult(), rel)
        assert path.is_absolute()
        assert path.exists()

    def test_creates_parent_directories(self, tmp_path):
        nested = tmp_path / 'a' / 'b' / 'c' / 'report.html'
        path = render_html_report(_RunResult(), nested)
        assert path.exists()
        assert path.parent.is_dir()

    def test_utf8_title_and_task_preserved(self, tmp_path):
        path = render_html_report(
            _RunResult(final_text='全部通过'),
            tmp_path / 'report.html',
            title='中文测试',
            task='验证登录流程',
            url='https://example.com/登录',
        )
        content = path.read_text(encoding='utf-8')
        assert '中文测试' in content
        assert '全部通过' in content
        assert '验证登录流程' in content
        assert 'https://example.com/登录' in content


class TestStepRendering:
    def test_steps_rendered_with_tool_names(self, tmp_path):
        result = _RunResult(steps=[
            _Step(tool='navigate', result='done'),
            _Step(tool='snapshot', result='<html>...'),
        ])
        content = render_html_report(result, tmp_path / 'r.html').read_text()
        assert 'Step 1 · navigate' in content
        assert 'Step 2 · snapshot' in content
        assert 'Steps (2)' in content

    def test_error_step_gets_error_class_and_tag(self, tmp_path):
        result = _RunResult(steps=[
            _Step(tool='click', result='missing', is_error=True),
        ])
        content = render_html_report(result, tmp_path / 'r.html').read_text()
        assert 'panel error' in content
        assert 'tag err' in content

    def test_ok_step_gets_ok_tag(self, tmp_path):
        result = _RunResult(steps=[_Step(tool='snapshot', result='x')])
        content = render_html_report(result, tmp_path / 'r.html').read_text()
        assert 'tag ok' in content
        assert 'tag err' not in content

    def test_input_rendered_as_json(self, tmp_path):
        result = _RunResult(steps=[
            _Step(tool='click', input={'selector': '#login', 'ts': 123}),
        ])
        content = render_html_report(result, tmp_path / 'r.html').read_text()
        # JSON is HTML-escaped inside the <pre> block for safety
        assert '&quot;selector&quot;' in content
        assert '#login' in content
        assert '123' in content


class TestStats:
    def test_step_and_error_counts(self, tmp_path):
        result = _RunResult(steps=[
            _Step(is_error=False),
            _Step(is_error=True),
            _Step(is_error=True),
        ])
        content = render_html_report(result, tmp_path / 'r.html').read_text()
        # Steps: 3, Errors: 2
        assert '>3<' in content  # step count value
        assert '>2<' in content  # error count value
        assert 'stat err' in content  # errors styled as error

    def test_status_ok_when_no_errors(self, tmp_path):
        result = _RunResult(steps=[_Step(is_error=False)])
        content = render_html_report(result, tmp_path / 'r.html').read_text()
        assert '>ok<' in content

    def test_status_aborted(self, tmp_path):
        result = _RunResult(aborted=True, steps=[_Step()])
        content = render_html_report(result, tmp_path / 'r.html').read_text()
        assert '>aborted<' in content
        assert 'aborted-banner' in content
        assert 'Run was aborted' in content

    def test_large_token_counts_formatted_with_commas(self, tmp_path):
        result = _RunResult(input_tokens=1234567, output_tokens=8900)
        content = render_html_report(result, tmp_path / 'r.html').read_text()
        assert '1,234,567' in content
        assert '8,900' in content

    def test_small_token_counts_no_commas(self, tmp_path):
        result = _RunResult(input_tokens=42, output_tokens=7)
        content = render_html_report(result, tmp_path / 'r.html').read_text()
        # Raw values present, no comma-formatting applied
        assert '>42<' in content
        assert '>7<' in content


class TestSecurity:
    def test_html_special_chars_escaped_in_final_text(self, tmp_path):
        result = _RunResult(final_text='<script>alert(1)</script>')
        content = render_html_report(result, tmp_path / 'r.html').read_text()
        assert '<script>alert(1)</script>' not in content
        assert '&lt;script&gt;' in content

    def test_html_special_chars_escaped_in_tool_name(self, tmp_path):
        result = _RunResult(steps=[_Step(tool='<img onerror=x>')])
        content = render_html_report(result, tmp_path / 'r.html').read_text()
        assert '<img onerror=x>' not in content
        assert '&lt;img' in content

    def test_html_special_chars_escaped_in_url_and_task(self, tmp_path):
        path = render_html_report(
            _RunResult(),
            tmp_path / 'r.html',
            url='<b>bad</b>',
            task='"><script>x</script>',
        )
        content = path.read_text()
        assert '<b>bad</b>' not in content
        assert '<script>x</script>' not in content


class TestMissingFields:
    def test_missing_final_text_omits_section(self, tmp_path):
        content = render_html_report(_RunResult(), tmp_path / 'r.html').read_text()
        assert '<h2>Final message</h2>' not in content

    def test_none_steps_renders_zero(self, tmp_path):
        class _R:
            final_text = 'done'
            steps = None
            aborted = False
            input_tokens = 0
            output_tokens = 0
        content = render_html_report(_R(), tmp_path / 'r.html').read_text()
        assert 'Steps (0)' in content

    def test_non_serializable_input_falls_back_to_repr(self, tmp_path):
        class _NoJson:
            def __repr__(self) -> str:
                return 'CustomObj(42)'

        result = _RunResult(steps=[_Step(input={'obj': _NoJson()})])
        content = render_html_report(result, tmp_path / 'r.html').read_text()
        # default=str kicks in for non-JSON-serializable → contains 'CustomObj(42)'
        assert 'CustomObj(42)' in content
