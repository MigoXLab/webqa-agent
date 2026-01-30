"""Unit tests for StateRestorer (Phase 2 - P2).

Tests state restoration logic for replanned test cases.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from webqa_agent.executor.gen.utils.state_restorer import StateRestorer


@pytest.fixture
def sample_completed_cases():
    """Provide sample completed cases with execution history."""
    return [
        {
            'case_name': 'Verify_Header_Try_Now_Button',
            'recorded_case': {
                'status': 'passed',
                'steps': [
                    {
                        'description': 'Navigate to homepage',
                        'current_url': 'https://discovery.intern-ai.org.cn/home'
                    },
                    {
                        'description': 'Click Try Now button',
                        'current_url': 'https://discovery.intern-ai.org.cn/login'
                    }
                ]
            }
        },
        {
            'case_name': 'Verify_Login_Form',
            'recorded_case': {
                'status': 'passed',
                'steps': [
                    {
                        'description': 'Fill login form',
                        'current_url': 'https://discovery.intern-ai.org.cn/login'
                    },
                    {
                        'description': 'Submit form',
                        'url': 'https://discovery.intern-ai.org.cn/dashboard'  # Using 'url' field
                    }
                ]
            }
        },
        {
            'case_name': 'Verify_Search_Functionality',
            'recorded_case': {
                'status': 'failed',
                'steps': []  # No steps, no URL
            }
        }
    ]


@pytest.fixture
def mock_ui_tester():
    """Provide mock UITester instance."""
    mock = MagicMock()
    mock_page = AsyncMock()
    mock_page.url = 'https://discovery.intern-ai.org.cn/home'
    mock_page.goto = AsyncMock()
    mock.get_current_page = AsyncMock(return_value=mock_page)
    return mock


class TestStateRestorerInit:
    """Test StateRestorer initialization."""

    def test_init_with_valid_cases(self, sample_completed_cases, mock_ui_tester):
        """Test initialization with valid completed cases."""
        restorer = StateRestorer(sample_completed_cases, mock_ui_tester)

        assert restorer.completed_cases == sample_completed_cases
        assert restorer.ui_tester == mock_ui_tester
        assert isinstance(restorer.state_map, dict)
        # Should build state map with 2 cases (third has no URL)
        assert len(restorer.state_map) == 2

    def test_init_with_empty_cases(self, mock_ui_tester):
        """Test initialization with empty completed cases."""
        restorer = StateRestorer([], mock_ui_tester)

        assert restorer.state_map == {}
        assert len(restorer.state_map) == 0


class TestStateRestorerStateMap:
    """Test state map building logic."""

    def test_build_state_map_from_completed_cases(self, sample_completed_cases, mock_ui_tester):
        """Test state map construction from completed cases (P2 key test)."""
        restorer = StateRestorer(sample_completed_cases, mock_ui_tester)

        # Verify state map structure
        assert 'Verify_Header_Try_Now_Button' in restorer.state_map
        assert 'Verify_Login_Form' in restorer.state_map
        assert 'Verify_Search_Functionality' not in restorer.state_map  # No URL

        # Verify last URLs extracted correctly
        assert restorer.state_map['Verify_Header_Try_Now_Button'] == \
            'https://discovery.intern-ai.org.cn/login'
        assert restorer.state_map['Verify_Login_Form'] == \
            'https://discovery.intern-ai.org.cn/dashboard'

    def test_build_state_map_with_missing_case_name(self, mock_ui_tester):
        """Test state map handles cases without case_name."""
        completed_cases = [
            {
                # Missing case_name
                'recorded_case': {
                    'steps': [{'current_url': 'https://example.com'}]
                }
            }
        ]

        restorer = StateRestorer(completed_cases, mock_ui_tester)
        assert restorer.state_map == {}

    def test_build_state_map_with_missing_recorded_case(self, mock_ui_tester):
        """Test state map handles cases without recorded_case."""
        completed_cases = [
            {
                'case_name': 'Test_Case',
                # Missing recorded_case
            }
        ]

        restorer = StateRestorer(completed_cases, mock_ui_tester)
        assert 'Test_Case' not in restorer.state_map


class TestStateRestorerUrlExtraction:
    """Test URL extraction from recorded cases."""

    def test_extract_last_url_current_url_field(self, mock_ui_tester):
        """Test extraction from 'current_url' field."""
        completed_cases = [
            {
                'case_name': 'Test_Case',
                'recorded_case': {
                    'steps': [
                        {'description': 'Step 1', 'current_url': 'https://example.com/page1'},
                        {'description': 'Step 2', 'current_url': 'https://example.com/page2'}
                    ]
                }
            }
        ]

        restorer = StateRestorer(completed_cases, mock_ui_tester)
        assert restorer.state_map['Test_Case'] == 'https://example.com/page2'

    def test_extract_last_url_url_field_fallback(self, mock_ui_tester):
        """Test fallback to 'url' field when 'current_url' missing."""
        completed_cases = [
            {
                'case_name': 'Test_Case',
                'recorded_case': {
                    'steps': [
                        {'description': 'Step 1', 'url': 'https://example.com/page1'},
                        {'description': 'Step 2', 'url': 'https://example.com/page2'}
                    ]
                }
            }
        ]

        restorer = StateRestorer(completed_cases, mock_ui_tester)
        assert restorer.state_map['Test_Case'] == 'https://example.com/page2'

    def test_extract_last_url_backwards_iteration(self, mock_ui_tester):
        """Test backwards iteration to find first URL (P2 key test)."""
        completed_cases = [
            {
                'case_name': 'Test_Case',
                'recorded_case': {
                    'steps': [
                        {'description': 'Step 1', 'current_url': 'https://example.com/page1'},
                        {'description': 'Step 2', 'current_url': 'https://example.com/page2'},
                        {'description': 'Step 3'}  # No URL
                    ]
                }
            }
        ]

        restorer = StateRestorer(completed_cases, mock_ui_tester)
        # Should find page2 (last step with URL)
        assert restorer.state_map['Test_Case'] == 'https://example.com/page2'

    def test_extract_last_url_no_url_in_steps(self, mock_ui_tester):
        """Test extraction returns None when no URL found."""
        completed_cases = [
            {
                'case_name': 'Test_Case',
                'recorded_case': {
                    'steps': [
                        {'description': 'Step 1'},
                        {'description': 'Step 2'}
                    ]
                }
            }
        ]

        restorer = StateRestorer(completed_cases, mock_ui_tester)
        assert 'Test_Case' not in restorer.state_map

    def test_extract_last_url_empty_steps(self, mock_ui_tester):
        """Test extraction handles empty steps list."""
        completed_cases = [
            {
                'case_name': 'Test_Case',
                'recorded_case': {
                    'steps': []
                }
            }
        ]

        restorer = StateRestorer(completed_cases, mock_ui_tester)
        assert 'Test_Case' not in restorer.state_map


class TestStateRestorerStateRestoration:
    """Test state restoration for replanned cases."""

    @pytest.mark.asyncio
    async def test_restore_state_replanned_case(self, sample_completed_cases, mock_ui_tester):
        """Test state restoration for replanned case (P2 key test)."""
        restorer = StateRestorer(sample_completed_cases, mock_ui_tester)

        # Replanned case referencing "Verify_Header_Try_Now_Button"
        replanned_case = {
            'name': 'Verify_Login_Language_Switcher',
            '_is_replanned': True,
            '_replan_source': 'Verify_Header_Try_Now_Button'
        }

        restored_url = await restorer.restore_state_if_needed(replanned_case)

        # Should restore to login page (last URL of source case)
        assert restored_url == 'https://discovery.intern-ai.org.cn/login'

        # Verify navigation was called
        mock_page = await mock_ui_tester.get_current_page()
        mock_page.goto.assert_called_once_with(
            'https://discovery.intern-ai.org.cn/login',
            wait_until='networkidle',
            timeout=30000
        )

    @pytest.mark.asyncio
    async def test_restore_state_not_replanned_case(self, sample_completed_cases, mock_ui_tester):
        """Test restoration skipped for non-replanned case."""
        restorer = StateRestorer(sample_completed_cases, mock_ui_tester)

        # Normal case (not replanned)
        normal_case = {
            'name': 'Verify_Footer_Links',
            '_is_replanned': False
        }

        restored_url = await restorer.restore_state_if_needed(normal_case)

        # Should return None (no restoration)
        assert restored_url is None

        # Verify no navigation occurred
        mock_page = await mock_ui_tester.get_current_page()
        mock_page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_restore_state_missing_source_case(self, sample_completed_cases, mock_ui_tester):
        """Test restoration handles missing source case gracefully."""
        restorer = StateRestorer(sample_completed_cases, mock_ui_tester)

        # Replanned case with non-existent source
        replanned_case = {
            'name': 'Verify_Nonexistent_Feature',
            '_is_replanned': True,
            '_replan_source': 'Nonexistent_Source_Case'
        }

        restored_url = await restorer.restore_state_if_needed(replanned_case)

        # Should return None and log warning
        assert restored_url is None

        # Verify no navigation occurred
        mock_page = await mock_ui_tester.get_current_page()
        mock_page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_restore_state_missing_replan_source_field(self, sample_completed_cases, mock_ui_tester):
        """Test restoration handles missing _replan_source field."""
        restorer = StateRestorer(sample_completed_cases, mock_ui_tester)

        # Replanned case without _replan_source
        replanned_case = {
            'name': 'Verify_Login_Language_Switcher',
            '_is_replanned': True
            # Missing _replan_source
        }

        restored_url = await restorer.restore_state_if_needed(replanned_case)

        # Should return None and log warning
        assert restored_url is None

    @pytest.mark.asyncio
    async def test_restore_state_already_at_target_url(self, sample_completed_cases, mock_ui_tester):
        """Test restoration skips navigation if already at target URL."""
        restorer = StateRestorer(sample_completed_cases, mock_ui_tester)

        # Set current page URL to target URL
        mock_page = await mock_ui_tester.get_current_page()
        mock_page.url = 'https://discovery.intern-ai.org.cn/login'

        replanned_case = {
            'name': 'Verify_Login_Language_Switcher',
            '_is_replanned': True,
            '_replan_source': 'Verify_Header_Try_Now_Button'
        }

        restored_url = await restorer.restore_state_if_needed(replanned_case)

        # Should return URL but skip navigation
        assert restored_url == 'https://discovery.intern-ai.org.cn/login'

        # Verify navigation was NOT called
        mock_page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_restore_state_navigation_failure(self, sample_completed_cases, mock_ui_tester):
        """Test restoration handles navigation failure gracefully."""
        restorer = StateRestorer(sample_completed_cases, mock_ui_tester)

        # Configure page.goto to raise exception
        mock_page = await mock_ui_tester.get_current_page()
        mock_page.goto.side_effect = Exception('Navigation timeout')

        replanned_case = {
            'name': 'Verify_Login_Language_Switcher',
            '_is_replanned': True,
            '_replan_source': 'Verify_Header_Try_Now_Button'
        }

        restored_url = await restorer.restore_state_if_needed(replanned_case)

        # Should return None and log error
        assert restored_url is None

        # Verify navigation was attempted
        mock_page.goto.assert_called_once()

    @pytest.mark.asyncio
    async def test_restore_state_no_current_page(self, sample_completed_cases, mock_ui_tester):
        """Test restoration handles missing current page."""
        restorer = StateRestorer(sample_completed_cases, mock_ui_tester)

        # Configure get_current_page to return None
        mock_ui_tester.get_current_page = AsyncMock(return_value=None)

        replanned_case = {
            'name': 'Verify_Login_Language_Switcher',
            '_is_replanned': True,
            '_replan_source': 'Verify_Header_Try_Now_Button'
        }

        restored_url = await restorer.restore_state_if_needed(replanned_case)

        # Should return None and log error
        assert restored_url is None


class TestStateRestorerHelperMethods:
    """Test StateRestorer helper methods."""

    def test_get_restorable_cases(self, sample_completed_cases, mock_ui_tester):
        """Test get_restorable_cases returns correct list."""
        restorer = StateRestorer(sample_completed_cases, mock_ui_tester)

        restorable = restorer.get_restorable_cases()

        assert 'Verify_Header_Try_Now_Button' in restorable
        assert 'Verify_Login_Form' in restorable
        assert 'Verify_Search_Functionality' not in restorable  # No URL
        assert len(restorable) == 2

    def test_has_restoration_for_existing_case(self, sample_completed_cases, mock_ui_tester):
        """Test has_restoration_for returns True for existing case."""
        restorer = StateRestorer(sample_completed_cases, mock_ui_tester)

        assert restorer.has_restoration_for('Verify_Header_Try_Now_Button') is True
        assert restorer.has_restoration_for('Verify_Login_Form') is True

    def test_has_restoration_for_nonexistent_case(self, sample_completed_cases, mock_ui_tester):
        """Test has_restoration_for returns False for nonexistent case."""
        restorer = StateRestorer(sample_completed_cases, mock_ui_tester)

        assert restorer.has_restoration_for('Nonexistent_Case') is False
        assert restorer.has_restoration_for('Verify_Search_Functionality') is False


class TestStateRestorerEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_restore_state_with_query_parameters(self, mock_ui_tester):
        """Test restoration preserves query parameters in URL."""
        completed_cases = [
            {
                'case_name': 'Test_Case',
                'recorded_case': {
                    'steps': [
                        {'current_url': 'https://example.com/search?q=test&lang=en'}
                    ]
                }
            }
        ]

        restorer = StateRestorer(completed_cases, mock_ui_tester)

        replanned_case = {
            'name': 'Replanned_Case',
            '_is_replanned': True,
            '_replan_source': 'Test_Case'
        }

        restored_url = await restorer.restore_state_if_needed(replanned_case)

        # Should preserve query parameters
        assert restored_url == 'https://example.com/search?q=test&lang=en'

    @pytest.mark.asyncio
    async def test_restore_state_with_url_fragment(self, mock_ui_tester):
        """Test restoration preserves URL fragments."""
        completed_cases = [
            {
                'case_name': 'Test_Case',
                'recorded_case': {
                    'steps': [
                        {'current_url': 'https://example.com/page#section'}
                    ]
                }
            }
        ]

        restorer = StateRestorer(completed_cases, mock_ui_tester)

        replanned_case = {
            'name': 'Replanned_Case',
            '_is_replanned': True,
            '_replan_source': 'Test_Case'
        }

        restored_url = await restorer.restore_state_if_needed(replanned_case)

        # Should preserve fragment
        assert restored_url == 'https://example.com/page#section'

    def test_state_map_with_duplicate_case_names(self, mock_ui_tester):
        """Test state map handles duplicate case names (last one wins)."""
        completed_cases = [
            {
                'case_name': 'Duplicate_Case',
                'recorded_case': {
                    'steps': [{'current_url': 'https://example.com/page1'}]
                }
            },
            {
                'case_name': 'Duplicate_Case',
                'recorded_case': {
                    'steps': [{'current_url': 'https://example.com/page2'}]
                }
            }
        ]

        restorer = StateRestorer(completed_cases, mock_ui_tester)

        # Last one should win
        assert restorer.state_map['Duplicate_Case'] == 'https://example.com/page2'

    def test_state_map_with_mixed_url_fields(self, mock_ui_tester):
        """Test state map handles mixed 'current_url' and 'url' fields."""
        completed_cases = [
            {
                'case_name': 'Test_Case',
                'recorded_case': {
                    'steps': [
                        {'current_url': 'https://example.com/page1'},
                        {'url': 'https://example.com/page2'},  # 'url' field
                        {'current_url': 'https://example.com/page3'}
                    ]
                }
            }
        ]

        restorer = StateRestorer(completed_cases, mock_ui_tester)

        # Should get last URL (current_url preferred if both exist)
        assert restorer.state_map['Test_Case'] == 'https://example.com/page3'

    @pytest.mark.asyncio
    async def test_restore_state_with_special_characters_in_url(self, mock_ui_tester):
        """Test restoration handles URLs with special characters."""
        completed_cases = [
            {
                'case_name': 'Test_Case',
                'recorded_case': {
                    'steps': [
                        {'current_url': 'https://example.com/search?q=测试&category=AI%20Models'}
                    ]
                }
            }
        ]

        restorer = StateRestorer(completed_cases, mock_ui_tester)

        replanned_case = {
            'name': 'Replanned_Case',
            '_is_replanned': True,
            '_replan_source': 'Test_Case'
        }

        restored_url = await restorer.restore_state_if_needed(replanned_case)

        # Should preserve special characters
        assert restored_url == 'https://example.com/search?q=测试&category=AI%20Models'
