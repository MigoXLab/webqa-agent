"""Unit tests for CaseJsonSynchronizer (Phase 1 - P1 + Phase 3 - P3).

Tests cases.json synchronization logic and step hierarchy tracking.
"""

import json

import pytest

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
        assert 'completed_steps' in case_1
        assert len(case_1['completed_steps']) == 3

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
        import logging

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

    def test_extract_executed_steps_with_expansion(self, temp_cases_json, sample_test_cases, sample_recorded_cases):
        """Test extraction of executed steps (P3 key test)."""
        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(sample_test_cases, sample_recorded_cases)

        with open(temp_cases_json, encoding='utf-8') as f:
            synced_cases = json.load(f)

        case_1 = synced_cases[0]

        # P3: Should have executed_steps field
        assert 'executed_steps' in case_1
        executed_steps = case_1['executed_steps']
        assert len(executed_steps) == 3  # UI Agent expanded 2 planned steps into 3 executed steps

        # Verify executed step structure
        assert executed_steps[0]['description'] == 'Navigate to login page'
        assert executed_steps[0]['status'] == 'passed'
        assert executed_steps[0]['timestamp'] == '2026-01-30T10:00:05'
        assert executed_steps[0]['step_type'] == 'action'
        assert executed_steps[0]['screenshot'] == 'screenshot1.png'  # First screenshot

        # Second executed step (sub-step)
        assert executed_steps[1]['description'] == 'Locate login button'
        assert 'screenshot' not in executed_steps[1]  # No screenshots

        # Third executed step with multiple screenshots (only first preserved)
        assert executed_steps[2]['screenshot'] == 'screenshot2.png'

    def test_step_expansion_ratio_calculation(self, temp_cases_json, sample_test_cases, sample_recorded_cases):
        """Test step expansion ratio calculation (P3 key test)."""
        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(sample_test_cases, sample_recorded_cases)

        with open(temp_cases_json, encoding='utf-8') as f:
            synced_cases = json.load(f)

        case_1 = synced_cases[0]

        # P3: Should calculate step_expansion_ratio
        assert 'step_expansion_ratio' in case_1
        # 3 executed steps / 2 planned steps = 1.5
        assert case_1['step_expansion_ratio'] == 1.5

    def test_planned_steps_preserved(self, temp_cases_json, sample_test_cases, sample_recorded_cases):
        """Test original planned steps are preserved (P3)."""
        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(sample_test_cases, sample_recorded_cases)

        with open(temp_cases_json, encoding='utf-8') as f:
            synced_cases = json.load(f)

        case_1 = synced_cases[0]

        # P3: Should preserve original planned steps
        assert 'planned_steps' in case_1
        assert len(case_1['planned_steps']) == 2
        assert case_1['planned_steps'][0]['action'] == 'Navigate to login page'

    def test_backward_compatibility_completed_steps(self, temp_cases_json, sample_test_cases, sample_recorded_cases):
        """Test backward compatibility - legacy completed_steps field (P3)."""
        synchronizer = CaseJsonSynchronizer(temp_cases_json)
        synchronizer.sync_cases(sample_test_cases, sample_recorded_cases)

        with open(temp_cases_json, encoding='utf-8') as f:
            synced_cases = json.load(f)

        case_1 = synced_cases[0]

        # P3: Should maintain legacy completed_steps for backward compatibility
        assert 'completed_steps' in case_1
        assert len(case_1['completed_steps']) == 3

        # Legacy format has less detail
        assert 'description' in case_1['completed_steps'][0]
        assert 'status' in case_1['completed_steps'][0]
        assert 'timestamp' in case_1['completed_steps'][0]


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
        assert synced_cases[0]['executed_steps'] == []
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
