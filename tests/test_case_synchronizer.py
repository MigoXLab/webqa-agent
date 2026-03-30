"""Unit tests for CaseJsonSynchronizer (Phase 1 - P1 + Phase 3 - P3).

Tests cases.json synchronization logic, step hierarchy tracking,
and run-mode YAML generation.
"""

import json
import logging

import pytest
import yaml

from webqa_agent.executor.gen.utils.case_synchronizer import \
    CaseJsonSynchronizer


@pytest.fixture
def temp_cases_json(tmp_path):
    """Provide temporary cases.json path."""
    return tmp_path / 'cases.json'


@pytest.fixture
def sample_test_cases():
    """Provide sample test cases (planning stage)."""
    return [
        {
            'case_id': 'case_1',
            'name': 'Test_Login',
            'status': 'pending',
            'objective': 'Test login functionality',
            'steps': [
                {'action': 'Navigate to login page'},
                {'action': 'Click login button'}
            ]
        },
        {
            'case_id': 'case_2',
            'name': 'Test_Signup',
            'status': 'pending',
            'objective': 'Test signup functionality',
            'steps': [
                {'action': 'Fill registration form'}
            ]
        }
    ]


@pytest.fixture
def sample_recorded_cases():
    """Provide sample recorded cases (execution stage)."""
    return [
        {
            'case_id': 'case_1',
            'status': 'passed',
            'start_time': '2026-01-30T10:00:00',
            'end_time': '2026-01-30T10:00:15',
            'duration': 15.2,
            'steps': [
                {
                    'description': 'Navigate to login page',
                    'status': 'passed',
                    'timestamp': '2026-01-30T10:00:05',
                    'step_type': 'action',
                    'screenshots': ['screenshot1.png']
                },
                {
                    'description': 'Locate login button',
                    'status': 'passed',
                    'timestamp': '2026-01-30T10:00:08',
                    'step_type': 'action'
                },
                {
                    'description': 'Click login button',
                    'status': 'passed',
                    'timestamp': '2026-01-30T10:00:12',
                    'step_type': 'action',
                    'screenshots': ['screenshot2.png', 'screenshot3.png']
                }
            ]
        },
        {
            'case_id': 'case_2',
            'status': 'failed',
            'start_time': '2026-01-30T10:00:20',
            'end_time': '2026-01-30T10:00:35',
            'duration': 15.8,
            'error': 'Element not found',
            'failure_type': 'element_not_found',
            'steps': [
                {
                    'description': 'Fill registration form',
                    'status': 'failed',
                    'timestamp': '2026-01-30T10:00:30'
                }
            ]
        }
    ]


class TestCaseJsonSynchronizerInit:
    """Test CaseJsonSynchronizer initialization."""

    def test_init_valid_path(self, temp_cases_json):
        """Test initialization with valid path."""
        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        assert synchronizer.cases_json_path == temp_cases_json

    def test_init_invalid_path_none(self):
        """Test initialization fails with None path."""
        with pytest.raises(ValueError, match='cannot be None or empty'):
            CaseJsonSynchronizer(None)

    def test_init_invalid_path_empty(self):
        """Test initialization fails with empty path."""
        with pytest.raises(ValueError, match='cannot be None or empty'):
            CaseJsonSynchronizer('')


class TestCaseJsonSynchronizerSyncCases:
    """Test cases.json synchronization (P1)."""

    def test_sync_cases_success(self, temp_cases_json, sample_test_cases, sample_recorded_cases):
        """Test successful synchronization of execution results."""
        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(sample_test_cases, sample_recorded_cases)

        # Read synchronized cases.json
        with open(temp_cases_json, encoding='utf-8') as f:
            synced_cases = json.load(f)

        # Verify case_1 (passed)
        case_1 = synced_cases[0]
        assert case_1['status'] == 'passed'
        assert case_1['start_time'] == '2026-01-30T10:00:00'
        assert case_1['duration'] == 15.2
        assert 'execution_steps' in case_1
        assert len(case_1['execution_steps']) == 3

        # Verify case_2 (failed)
        case_2 = synced_cases[1]
        assert case_2['status'] == 'failed'
        assert case_2['error'] == 'Element not found'
        assert case_2['failure_type'] == 'element_not_found'

    def test_sync_cases_empty_recorded(self, temp_cases_json, sample_test_cases):
        """Test synchronization with empty recorded cases."""
        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(sample_test_cases, [])

        # Should not crash, just log warning
        # Cases should remain unchanged
        assert not temp_cases_json.exists()

    def test_sync_cases_missing_case_id(self, temp_cases_json, sample_test_cases, caplog):
        """Test synchronization handles missing case_id gracefully."""
        recorded_cases = [
            {
                # Missing case_id
                'status': 'passed',
                'steps': []
            }
        ]

        synchronizer = CaseJsonSynchronizer(temp_cases_json)

        # Capture warning logs
        with caplog.at_level(logging.WARNING):
            synchronizer.sync_cases(sample_test_cases, recorded_cases)

        # Should log warning about no valid recorded cases
        assert 'No valid recorded cases' in caplog.text

        # File should not be created when all recorded cases are invalid
        assert not temp_cases_json.exists()

    def test_sync_cases_creates_parent_dir(self, tmp_path, sample_test_cases, sample_recorded_cases):
        """Test synchronization creates parent directory if missing."""
        nested_path = tmp_path / 'reports' / 'test_session' / 'cases.json'

        synchronizer = CaseJsonSynchronizer(nested_path)
        synchronizer.sync_cases(sample_test_cases, sample_recorded_cases)

        assert nested_path.exists()
        assert nested_path.parent.exists()


class TestCaseJsonSynchronizerStepHierarchy:
    """Test step hierarchy tracking (P3)."""

    def test_execution_steps_structure(self, temp_cases_json, sample_test_cases, sample_recorded_cases):
        """Test execution_steps extraction contains correct step summaries."""
        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(sample_test_cases, sample_recorded_cases)

        with open(temp_cases_json, encoding='utf-8') as f:
            synced_cases = json.load(f)

        case_1 = synced_cases[0]

        # Should have execution_steps field with step summaries
        assert 'execution_steps' in case_1
        execution_steps = case_1['execution_steps']
        assert len(execution_steps) == 3  # UI Agent expanded 2 planned steps into 3 completed steps

        # Verify completed step structure (description, status, timestamp)
        assert execution_steps[0]['description'] == 'Navigate to login page'
        assert execution_steps[0]['status'] == 'passed'
        assert execution_steps[0]['timestamp'] == '2026-01-30T10:00:05'

        # Second completed step (sub-step generated by agent)
        assert execution_steps[1]['description'] == 'Locate login button'

        # Third completed step
        assert execution_steps[2]['description'] == 'Click login button'

        # executed_steps field should NOT be present (removed)
        assert 'executed_steps' not in case_1

    def test_step_expansion_ratio_calculation(self, temp_cases_json, sample_test_cases, sample_recorded_cases):
        """Test step expansion ratio calculation (P3 key test)."""
        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(sample_test_cases, sample_recorded_cases)

        with open(temp_cases_json, encoding='utf-8') as f:
            synced_cases = json.load(f)

        case_1 = synced_cases[0]

        # Should calculate step_expansion_ratio (completed / planned)
        assert 'step_expansion_ratio' in case_1
        # 3 completed steps / 2 planned steps = 1.5
        assert case_1['step_expansion_ratio'] == 1.5

    def test_planned_steps_preserved_fallback(self, temp_cases_json, sample_test_cases, sample_recorded_cases):
        """Test planned_steps falls back to current steps when original not in
        recorded data."""
        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(sample_test_cases, sample_recorded_cases)

        with open(temp_cases_json, encoding='utf-8') as f:
            synced_cases = json.load(f)

        case_1 = synced_cases[0]

        # Should preserve original planned steps (fallback to case['steps'])
        assert 'planned_steps' in case_1
        assert len(case_1['planned_steps']) == 2
        assert case_1['planned_steps'][0]['action'] == 'Navigate to login page'

    def test_planned_steps_from_original_planned_steps(self, temp_cases_json):
        """Test planned_steps uses original_planned_steps from recorded data
        when available."""
        test_cases = [
            {
                'case_id': 'case_1',
                'name': 'Test_Login',
                'status': 'pending',
                # steps may have been modified by adaptive recovery
                'steps': [
                    {'action': 'MODIFIED by adaptive recovery'},
                    {'action': 'Click login button'}
                ]
            }
        ]
        recorded_cases = [
            {
                'case_id': 'case_1',
                'status': 'passed',
                'steps': [{'description': 'Click login', 'status': 'passed'}],
                # original_planned_steps captured before adaptive recovery
                'original_planned_steps': [
                    {'action': 'Navigate to login page'},
                    {'action': 'Click login button'}
                ]
            }
        ]

        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(test_cases, recorded_cases)

        with open(temp_cases_json, encoding='utf-8') as f:
            synced_cases = json.load(f)

        case_1 = synced_cases[0]

        # planned_steps should come from original_planned_steps, NOT from modified steps
        assert case_1['planned_steps'][0]['action'] == 'Navigate to login page'
        assert case_1['planned_steps'][0]['action'] != 'MODIFIED by adaptive recovery'

    def test_execution_steps_field_structure(self, temp_cases_json, sample_test_cases, sample_recorded_cases):
        """Test execution_steps field contains summary-level step data."""
        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(sample_test_cases, sample_recorded_cases)

        with open(temp_cases_json, encoding='utf-8') as f:
            synced_cases = json.load(f)

        case_1 = synced_cases[0]

        # Should have execution_steps with summary fields
        assert 'execution_steps' in case_1
        assert len(case_1['execution_steps']) == 3

        # Each step has description, status, timestamp
        assert 'description' in case_1['execution_steps'][0]
        assert 'status' in case_1['execution_steps'][0]
        assert 'timestamp' in case_1['execution_steps'][0]


class TestCaseJsonSynchronizerEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_sync_cases_no_steps(self, temp_cases_json):
        """Test synchronization with recorded case having no steps."""
        test_cases = [{'case_id': 'case_1', 'name': 'Test', 'status': 'pending'}]
        recorded_cases = [{'case_id': 'case_1', 'status': 'passed', 'steps': []}]

        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(test_cases, recorded_cases)

        with open(temp_cases_json, encoding='utf-8') as f:
            synced_cases = json.load(f)

        assert synced_cases[0]['status'] == 'passed'
        assert synced_cases[0]['execution_steps'] == []
        assert synced_cases[0]['step_expansion_ratio'] == 1.0  # Default when no planned steps

    def test_sync_cases_duplicate_case_id(self, temp_cases_json, sample_test_cases, caplog):
        """Test synchronization with duplicate case IDs in recorded cases."""
        recorded_cases = [
            {'case_id': 'case_1', 'status': 'passed', 'steps': []},
            {'case_id': 'case_1', 'status': 'failed', 'steps': []}  # Duplicate
        ]

        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(sample_test_cases, recorded_cases)

        # Should log warning about duplicate
        assert 'Duplicate case_id' in caplog.text

    def test_sync_cases_with_replanned_cases(self, temp_cases_json):
        """Test synchronization works with replanned cases metadata."""
        test_cases = [
            {
                'case_id': 'case_1',
                'name': 'Test_Original',
                'status': 'pending',
                'steps': [{'action': 'Click button'}]
            },
            {
                'case_id': 'case_2',
                'name': 'Test_Replanned',
                'status': 'pending',
                '_is_replanned': True,
                '_replan_source': 'case_1',
                'steps': [{'action': 'Verify element'}]
            }
        ]

        recorded_cases = [
            {'case_id': 'case_1', 'status': 'passed', 'steps': [{'description': 'Click button', 'status': 'passed'}]},
            {'case_id': 'case_2', 'status': 'passed', 'steps': [{'description': 'Verify element', 'status': 'passed'}]}
        ]

        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(test_cases, recorded_cases)

        with open(temp_cases_json, encoding='utf-8') as f:
            synced_cases = json.load(f)

        # Both should sync successfully
        assert synced_cases[0]['status'] == 'passed'
        assert synced_cases[1]['status'] == 'passed'
        # Replanned metadata should be preserved
        assert synced_cases[1]['_is_replanned'] is True

    def test_sync_cases_warning_status(self, temp_cases_json):
        """Test synchronization with warning status."""
        test_cases = [{'case_id': 'case_1', 'name': 'Test', 'status': 'pending'}]
        recorded_cases = [
            {
                'case_id': 'case_1',
                'status': 'warning',
                'steps': [
                    {'description': 'Step 1', 'status': 'passed'},
                    {'description': 'Step 2', 'status': 'warning'}
                ]
            }
        ]

        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(test_cases, recorded_cases)

        with open(temp_cases_json, encoding='utf-8') as f:
            synced_cases = json.load(f)

        assert synced_cases[0]['status'] == 'warning'


class TestGenerateRunModeSteps:
    """Test _generate_run_mode_steps() parsing logic (unit tests)."""

    @pytest.fixture
    def synchronizer(self, temp_cases_json):
        """Provide a synchronizer instance for unit testing."""
        return CaseJsonSynchronizer(temp_cases_json)

    def test_action_prefix_parsed(self, synchronizer):
        """Test action-prefixed descriptions are parsed correctly."""
        steps = [
            {'description': 'action: Click the login button', 'status': 'passed'},
            {'description': 'action: Type username in the input field', 'status': 'passed'},
        ]
        result = synchronizer._generate_run_mode_steps(steps)
        assert result == [
            {'action': 'Click the login button'},
            {'action': 'Type username in the input field'},
        ]

    def test_verify_prefix_parsed(self, synchronizer):
        """Test verify-prefixed descriptions are parsed correctly."""
        steps = [{'description': 'verify: The page title should be Dashboard', 'status': 'passed'}]
        result = synchronizer._generate_run_mode_steps(steps)
        assert result == [{'verify': 'The page title should be Dashboard'}]

    def test_ux_verify_prefix_parsed(self, synchronizer):
        """Test ux_verify-prefixed descriptions are parsed correctly."""
        steps = [{'description': 'ux_verify: The layout should be responsive', 'status': 'passed'}]
        result = synchronizer._generate_run_mode_steps(steps)
        assert result == [{'ux_verify': 'The layout should be responsive'}]

    def test_mixed_prefixes_parsed(self, synchronizer):
        """Test mixed prefix types are all parsed correctly."""
        steps = [
            {'description': 'action: Navigate to the login page', 'status': 'passed'},
            {'description': 'verify: Dashboard page is displayed', 'status': 'passed'},
            {'description': 'ux_verify: Navigation menu is visually consistent', 'status': 'passed'},
        ]
        result = synchronizer._generate_run_mode_steps(steps)
        assert result == [
            {'action': 'Navigate to the login page'},
            {'verify': 'Dashboard page is displayed'},
            {'ux_verify': 'Navigation menu is visually consistent'},
        ]

    def test_no_prefix_falls_back_to_custom(self, synchronizer):
        """Test descriptions without prefix fall back to custom type."""
        steps = [
            {'description': 'Click the login button', 'status': 'passed'},
            {'description': 'Navigate to dashboard', 'status': 'passed'},
        ]
        result = synchronizer._generate_run_mode_steps(steps)
        assert result == [
            {'custom': 'Click the login button'},
            {'custom': 'Navigate to dashboard'},
        ]

    def test_unknown_prefix_falls_back_to_custom(self, synchronizer):
        """Test unknown prefixes (custom tools) fall back to custom type."""
        steps = [
            {'description': 'lighthouse: Run performance audit', 'status': 'passed'},
            {'description': 'nuclei: Scan for vulnerabilities', 'status': 'passed'},
        ]
        result = synchronizer._generate_run_mode_steps(steps)
        assert result == [
            {'custom': 'lighthouse: Run performance audit'},
            {'custom': 'nuclei: Scan for vulnerabilities'},
        ]

    def test_empty_description_skipped(self, synchronizer):
        """Test steps with empty or missing description are skipped."""
        steps = [
            {'description': 'action: Click button', 'status': 'passed'},
            {'description': '', 'status': 'passed'},
            {'status': 'passed'},
            {'description': 'verify: Check result', 'status': 'passed'},
        ]
        result = synchronizer._generate_run_mode_steps(steps)
        assert result == [
            {'action': 'Click button'},
            {'verify': 'Check result'},
        ]

    def test_empty_input_returns_empty(self, synchronizer):
        """Test empty execution_steps returns empty list."""
        assert synchronizer._generate_run_mode_steps([]) == []

    def test_multiple_colons_in_description(self, synchronizer):
        """Test descriptions with multiple colons (e.g., URLs) are parsed
        correctly."""
        steps = [
            {'description': 'action: Navigate to URL: https://example.com/path?q=1', 'status': 'passed'},
            {'description': 'verify: Title should be: "Welcome: Home"', 'status': 'passed'},
        ]
        result = synchronizer._generate_run_mode_steps(steps)
        assert result == [
            {'action': 'Navigate to URL: https://example.com/path?q=1'},
            {'verify': 'Title should be: "Welcome: Home"'},
        ]

    def test_case_insensitive_prefix(self, synchronizer):
        """Test prefix matching is case-insensitive."""
        steps = [
            {'description': 'Action: Click button', 'status': 'passed'},
            {'description': 'VERIFY: Check result', 'status': 'passed'},
            {'description': 'UX_Verify: Check layout', 'status': 'passed'},
        ]
        result = synchronizer._generate_run_mode_steps(steps)
        assert result == [
            {'action': 'Click button'},
            {'verify': 'Check result'},
            {'ux_verify': 'Check layout'},
        ]


class TestCasesYamlGeneration:
    """Test run-mode cases.yaml file generation."""

    def test_yaml_file_generated_alongside_json(self, temp_cases_json, sample_test_cases, sample_recorded_cases):
        """Test cases.yaml is generated in the same directory as cases.json."""
        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(sample_test_cases, sample_recorded_cases)

        yaml_path = temp_cases_json.parent / 'cases.yaml'
        assert yaml_path.exists()

    def test_yaml_structure_matches_run_mode(self, temp_cases_json, sample_test_cases, sample_recorded_cases):
        """Test YAML content has correct structure for config_run.yaml."""
        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(sample_test_cases, sample_recorded_cases)

        yaml_path = temp_cases_json.parent / 'cases.yaml'
        with open(yaml_path, encoding='utf-8') as f:
            data = yaml.safe_load(f)

        # Top-level key should be 'cases'
        assert 'cases' in data
        cases = data['cases']

        # Both cases have execution_steps, so both should be in YAML
        assert len(cases) == 2

        # Each case has name and steps
        assert cases[0]['name'] == 'Test_Login'
        assert 'steps' in cases[0]
        assert len(cases[0]['steps']) == 3  # 3 execution steps

        assert cases[1]['name'] == 'Test_Signup'
        assert len(cases[1]['steps']) == 1

    def test_yaml_step_format_with_prefixes(self, temp_cases_json):
        """Test YAML steps are properly formatted from prefixed
        descriptions."""
        test_cases = [{'case_id': 'case_1', 'name': 'Test_Flow', 'status': 'pending'}]
        recorded_cases = [
            {
                'case_id': 'case_1',
                'status': 'passed',
                'steps': [
                    {'description': 'action: Click login button', 'status': 'passed'},
                    {'description': 'verify: Dashboard is displayed', 'status': 'passed'},
                    {'description': 'ux_verify: Layout is responsive', 'status': 'passed'},
                    {'description': 'lighthouse: Run audit', 'status': 'passed'},
                ]
            }
        ]

        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(test_cases, recorded_cases)

        yaml_path = temp_cases_json.parent / 'cases.yaml'
        with open(yaml_path, encoding='utf-8') as f:
            data = yaml.safe_load(f)

        steps = data['cases'][0]['steps']
        assert steps[0] == {'action': 'Click login button'}
        assert steps[1] == {'verify': 'Dashboard is displayed'}
        assert steps[2] == {'ux_verify': 'Layout is responsive'}
        assert steps[3] == {'custom': 'lighthouse: Run audit'}

    def test_yaml_not_generated_when_no_executed_cases(self, temp_cases_json, sample_test_cases):
        """Test cases.yaml is not generated when no cases have
        execution_steps."""
        # All recorded cases have empty steps → no execution_steps after sync
        recorded_cases = [
            {'case_id': 'case_1', 'status': 'passed', 'steps': []},
            {'case_id': 'case_2', 'status': 'passed', 'steps': []},
        ]

        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(sample_test_cases, recorded_cases)

        yaml_path = temp_cases_json.parent / 'cases.yaml'
        assert not yaml_path.exists()

    def test_yaml_preserves_unicode(self, temp_cases_json):
        """Test YAML output preserves Unicode characters (Chinese, etc.)."""
        test_cases = [
            {
                'case_id': 'case_1',
                'name': '免登录-新对话',
                'status': 'pending',
            }
        ]
        recorded_cases = [
            {
                'case_id': 'case_1',
                'status': 'passed',
                'steps': [
                    {'description': 'verify: 校验可以查看首页内容', 'status': 'passed'},
                    {'description': 'action: 点击左侧边栏的"新对话"', 'status': 'passed'},
                ]
            }
        ]

        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(test_cases, recorded_cases)

        yaml_path = temp_cases_json.parent / 'cases.yaml'
        with open(yaml_path, encoding='utf-8') as f:
            content = f.read()
            data = yaml.safe_load(content)

        # Unicode should be preserved, not escaped
        assert data['cases'][0]['name'] == '免登录-新对话'
        assert data['cases'][0]['steps'][0] == {'verify': '校验可以查看首页内容'}
        assert data['cases'][0]['steps'][1] == {'action': '点击左侧边栏的"新对话"'}

        # Content should not contain Unicode escape sequences
        assert '\\u' not in content

    def test_yaml_indentation_is_readable(self, temp_cases_json):
        """Test YAML output uses proper indentation for readability."""
        test_cases = [{'case_id': 'case_1', 'name': 'Test', 'status': 'pending'}]
        recorded_cases = [
            {
                'case_id': 'case_1',
                'status': 'passed',
                'steps': [{'description': 'action: Click button', 'status': 'passed'}]
            }
        ]

        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(test_cases, recorded_cases)

        yaml_path = temp_cases_json.parent / 'cases.yaml'
        with open(yaml_path, encoding='utf-8') as f:
            content = f.read()

        # Should start with 'cases:'
        assert content.startswith('cases:')
        # List items should be indented (not at root level)
        assert '  - name:' in content
        # Steps should be further indented
        assert '      - action:' in content


class TestCaseJsonSynchronizerFileIO:
    """Test file I/O operations."""

    def test_write_preserves_unicode(self, temp_cases_json):
        """Test writing preserves Unicode characters."""
        test_cases = [
            {
                'case_id': 'case_1',
                'name': '测试用例',  # Chinese characters
                'objective': '验证登录功能',
                'status': 'pending'
            }
        ]
        recorded_cases = [
            {'case_id': 'case_1', 'status': 'passed', 'steps': []}
        ]

        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(test_cases, recorded_cases)

        with open(temp_cases_json, encoding='utf-8') as f:
            content = f.read()
            synced_cases = json.loads(content)

        # Unicode should be preserved
        assert synced_cases[0]['name'] == '测试用例'
        assert synced_cases[0]['objective'] == '验证登录功能'

    def test_write_formatting(self, temp_cases_json, sample_test_cases, sample_recorded_cases):
        """Test JSON is written with proper formatting."""
        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(sample_test_cases, sample_recorded_cases)

        with open(temp_cases_json) as f:
            content = f.read()

        # Should be indented (not minified)
        assert '    ' in content  # 4-space indentation
        assert '\n' in content
