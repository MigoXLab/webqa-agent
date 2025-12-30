"""Dynamic link detection tool for WebQA Agent.

This tool detects new links that appear after user interactions (clicks, form
submissions, dynamic content loading) and validates them for HTTPS compliance
and accessibility.

Key Features:
- Reuses CrawlHandler.extract_links() for consistency with WebAccessibilityTest
- Tracks link history via ui_tester_instance.last_action_context
- Performs HTTPS certificate validation and HTTP status checks
- Returns validated results for newly discovered links

Usage in test plans:
    LLM autonomously chooses when to invoke this tool based on:
    - Page features (SPA frameworks, dynamic content indicators)
    - Test objectives mentioning navigation/links
    - Actions that may reveal new content (clicks, dropdowns, forms)

Example test step:
    {"action": "Click the navigation dropdown"},
    {"action": "detect_dynamic_links", "description": "Check for new links in dropdown"}
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, Type

from pydantic import BaseModel, Field

from webqa_agent.crawler.crawl import CrawlHandler
from webqa_agent.testers.basic_tester import WebAccessibilityTest
from webqa_agent.testers.case_gen.tools.base import (WebQABaseTool,
                                                     WebQAToolMetadata)
from webqa_agent.testers.case_gen.tools.registry import register_tool


class DynamicLinkDetectionSchema(BaseModel):
    """Schema for dynamic link detection tool arguments.

    LLM uses these Field descriptions to understand parameter usage.
    """

    check_https: bool = Field(
        default=True,
        description=(
            'Whether to validate HTTPS certificates for discovered links. '
            'Set to False to skip certificate validation for faster execution.'
        )
    )
    check_status: bool = Field(
        default=True,
        description=(
            'Whether to check HTTP status codes for discovered links. '
            'Set to False to skip status checks for faster execution.'
        )
    )
    timeout: int = Field(
        default=10,
        description=(
            'Request timeout in seconds for validation checks. '
            'Increase for slow networks, decrease for faster execution.'
        )
    )


@register_tool  # Automatically registers to global registry on import
class DynamicLinkDetectionTool(WebQABaseTool):
    """Tool for detecting dynamically loaded links after user interactions.

    This action-category tool tracks link history and identifies newly appeared
    links during test execution. It integrates with the test execution context
    to maintain state across multiple invocations within the same test case.

    Architecture:
    - Category: 'custom' - Custom user-defined tool
    - Trigger: Explicit step_type for LLM planning prompt inclusion
    - Browser Access: Requires ui_tester_instance for page interaction
    - Validation: Reuses WebAccessibilityTest methods for consistency

    Context Tracking:
    - Stores 'all_links_snapshot' in last_action_context
    - Compares current links vs previous snapshot to find new links
    - Context cleared between test cases (graph.py:602)

    Performance:
    - Set difference: O(n) operation, very fast
    - Validation: Optional via check_https and check_status flags
    - Parallel validation: Uses asyncio.gather() for multiple links
    """

    name: str = 'detect_dynamic_links'
    description: str = (
        'Detects new links that appear after user interactions '
        '(clicks, dropdowns, form submissions, dynamic content loading). '
        'Validates HTTPS compliance and HTTP status codes for discovered links.'
    )
    args_schema: Type[BaseModel] = DynamicLinkDetectionSchema

    # Requires browser access via ui_tester_instance
    ui_tester_instance: Any = Field(
        ...,
        description='UITester instance for accessing browser page and context'
    )

    # Requires case_recorder for step recording
    case_recorder: Any | None = Field(
        default=None,
        description='Optional CentralCaseRecorder to record detection steps'
    )

    @classmethod
    def get_metadata(cls) -> WebQAToolMetadata:
        """Return tool metadata for registration and prompt generation."""
        return WebQAToolMetadata(
            name='detect_dynamic_links',
            category='custom',  # Custom tool - marks as user-defined
            step_type='detect_dynamic_links',  # Explicit step type for planning
            description_short='Detects new links appearing after user interactions',
            description_long=(
                'Identifies and validates new links that appear dynamically after user '
                'interactions such as clicking navigation menus, submitting forms, or '
                'triggering content updates in Single Page Applications.\n\n'
                'Features:\n'
                '  - Tracks link history to identify newly appeared links\n'
                '  - HTTPS certificate validation (optional)\n'
                '  - HTTP status code checking (optional)\n'
                '  - Reuses WebAccessibilityTest validation methods for consistency\n\n'
                'Parameters:\n'
                '  - check_https: Validate HTTPS certificates (default: True)\n'
                '  - check_status: Check HTTP status codes (default: True)\n'
                '  - timeout: Request timeout in seconds (default: 10)'
            ),
            examples=[
                ('{{"action": "detect_dynamic_links", "params": '
                 '{{"check_https": true, "check_status": true, "timeout": 10}}}}'),
                '{{"action": "detect_dynamic_links", "params": {{"check_https": false, "check_status": true}}}}',
                '{{"action": "detect_dynamic_links", "params": {{}}}}'
            ],
            use_when=[
                # Dynamic link discovery scenarios (SPA & interactive content)
                'After clicking navigation menus, dropdowns, or tabs that reveal new links',
                'After form submissions that may display new pages or confirmation screens with links',
                'In Single Page Applications (SPAs) where links appear dynamically after routing',
                'When testing dynamic navigation features (e.g., infinite scroll pagination with page links)',
                'After interactions that trigger DOM updates revealing previously hidden links',

                # Comprehensive link quality testing (QA perspective)
                'At the start of testing to establish baseline link inventory for the page',
                'When conducting accessibility audits to verify all links are valid and reachable',
                'During security testing to validate HTTPS compliance and certificate validity',
                'When evaluating link quality (descriptive text, ARIA labels, broken links)',

                # Systematic link validation scenarios
                'After major page changes to detect broken internal links',
                'When testing external integrations to verify third-party links are accessible',
                'During regression testing to ensure previously working links remain functional',
                'When validating navigation paths to confirm all routes are accessible',

                # Specific use cases
                'After authentication/login to detect member-only or role-specific links',
                'When testing multi-step workflows to track navigation options at each step',
                'In content-heavy pages to audit all embedded hyperlinks and resources'
            ],
            dont_use_when=[
                # Non-link-related actions
                'After non-navigation actions like typing, hovering, or scrolling that do not reveal new content',
                'When testing non-link functionality (e.g., form validation, search results content)',
                'During performance-critical operations where link validation would add unnecessary overhead',

                # Redundant or inefficient scenarios
                'Immediately after another link detection (avoid duplicate checks within same page state)',
                'When the page has no links or only static content that was already validated',
                'In the middle of multi-step forms before reaching confirmation/result pages with links'
            ],
            priority=45,  # Medium-high priority (between core tools 70-90 and standalone custom 30-40)
            dependencies=[]  # No external dependencies, uses built-in modules
        )

    @classmethod
    def get_required_params(cls) -> Dict[str, str]:
        """Specify required initialization parameters.

        This tool requires:
        - ui_tester_instance: For browser access
        - case_recorder: For recording detection steps to test report
        """
        return {
            'ui_tester_instance': 'ui_tester_instance',
            'case_recorder': 'case_recorder'
        }

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        """Convert any value to JSON-serializable form.

        Args:
            value: Any value, potentially an Exception object.

        Returns:
            String representation if value is Exception, otherwise original value.
        """
        if isinstance(value, Exception):
            return str(value)
        return value

    async def _arun(
        self,
        check_https: bool = True,
        check_status: bool = True,
        timeout: int = 10
    ) -> str:
        """Execute dynamic link detection.

        Workflow:
        1. Extract current links using CrawlHandler
        2. Retrieve previous links from execution context
        3. Identify new links via set difference
        4. Validate new links (HTTPS + status checks)
        5. Update context with current link snapshot
        6. Return formatted results

        Args:
            check_https: Whether to validate HTTPS certificates
            check_status: Whether to check HTTP status codes
            timeout: Request timeout in seconds

        Returns:
            Formatted response with detected links and validation results
        """
        try:
            # Step 1: Get current page and extract all links
            page = await self.ui_tester_instance.get_current_page()
            current_url = page.url

            logging.debug(f'Dynamic Link Detection: Extracting links from {current_url}')

            # Use CrawlHandler for consistency with WebAccessibilityTest
            crawl_handler = CrawlHandler(base_url=current_url)
            current_links = await crawl_handler.extract_links(page)

            logging.debug(f'Dynamic Link Detection: Found {len(current_links)} total links on page')

            # Step 2: Retrieve previous links from context
            # Note: get_execution_context() returns None when there's no prior action
            previous_context = self.get_execution_context(self.ui_tester_instance)

            # Handle first invocation: initialize empty set if no context exists
            if previous_context:
                previous_links = set(
                    previous_context.get('last_action', {}).get('all_links_snapshot', [])
                )
            else:
                previous_links = set()

            if not previous_links:
                logging.debug('Dynamic Link Detection: First invocation - no previous link history')
            else:
                logging.debug(f'Dynamic Link Detection: Previous snapshot had {len(previous_links)} links')

            # Step 3: Identify new links using set difference
            current_links_set = set(current_links)
            new_links = current_links_set - previous_links

            logging.debug(f'Dynamic Link Detection: Detected {len(new_links)} new links')

            # Step 4: Validate new links (if requested and links exist)
            validated_links = []
            if new_links:
                for link in list(new_links)[:20]:  # Limit to first 20 for performance
                    link_result = {'url': link, 'https_valid': None, 'status_code': None}

                    # HTTPS certificate validation
                    if check_https:
                        try:
                            https_valid, reason, expiry = await WebAccessibilityTest.check_https_expiry(
                                link, timeout=timeout
                            )
                            link_result['https_valid'] = https_valid
                            # Ensure reason is always a string (it may be an Exception object)
                            link_result['https_reason'] = self._serialize_value(reason) if reason else None
                            if expiry:
                                link_result['https_expiry'] = expiry
                        except Exception as e:
                            logging.debug(f'HTTPS validation failed for {link}: {e}')
                            link_result['https_valid'] = False
                            link_result['https_reason'] = f'Validation error: {str(e)}'

                    # HTTP status code check
                    if check_status:
                        try:
                            status_code = await WebAccessibilityTest.check_page_status(
                                link, timeout=timeout
                            )
                            link_result['status_code'] = status_code
                        except Exception as e:
                            logging.debug(f'Status check failed for {link}: {e}')
                            link_result['status_code'] = 'error'

                    validated_links.append(link_result)

            # Step 5: Update context with current link snapshot for next invocation
            # IMPORTANT: This context enables subsequent assertion steps to verify link quality
            # Fields align with UITool pattern (element_action_tool.py:222-231) to ensure
            # function_tester.py:_format_execution_context() can extract all required data

            # Build result message for LLM and assertions
            result_message = f'Detected {len(new_links)} new links on page'
            if check_https or check_status:
                passed_count = sum(
                    1 for link in validated_links
                    if (not check_https or link.get('https_valid') is True)
                    and (not check_status or str(link.get('status_code', '')).startswith('2'))
                )
                result_message += f' (validated {len(validated_links)}: {passed_count} passed)'

            self.update_action_context(
                self.ui_tester_instance,
                {
                    # Core fields (required by assertion tools)
                    'description': f'Detect dynamic links (found {len(new_links)} new)',
                    'action_type': 'DynamicLinkCheck',
                    'status': 'success',  # Detection succeeded even if some links failed validation
                    'result': {
                        'message': result_message,  # CRITICAL: Used by LLM prompts as "Result: ..."
                        'validated_links': validated_links,  # CRITICAL: Enables link quality assertions
                        'total_links_on_page': len(current_links_set),
                        'new_links_count': len(new_links),
                        'check_https': check_https,
                        'check_status': check_status,
                    },
                    'timestamp': datetime.now().isoformat(),

                    # DynamicLinkCheck-specific fields (backward compatibility + state tracking)
                    'detected_new_links_count': len(new_links),  # Keep for backward compatibility
                    'all_links_snapshot': list(current_links_set),  # Required for next invocation comparison
                }
            )

            # Step 6: Format response
            if not new_links:
                # Record step even when no new links found
                if self.case_recorder:
                    self.case_recorder.add_step(
                        description='Detect dynamic links (no new links found)',
                        screenshots=[],
                        model_io=f'Total links on page: {len(current_links)}. No new links since last check.',
                        actions=[],
                        status='passed',
                        step_type='action',
                    )

                # Update context even when no new links (enables proper assertion context)
                self.update_action_context(
                    self.ui_tester_instance,
                    {
                        # Core fields (required by assertion tools)
                        'description': 'Detect dynamic links (no new links found)',
                        'action_type': 'DynamicLinkCheck',
                        'status': 'success',  # No new links is a successful detection result
                        'result': {
                            'message': f'No new links detected. Total links on page: {len(current_links)}',
                            'validated_links': [],  # Empty list (no new links to validate)
                            'total_links_on_page': len(current_links),
                            'new_links_count': 0,
                            'check_https': check_https,
                            'check_status': check_status,
                        },
                        'timestamp': datetime.now().isoformat(),

                        # DynamicLinkCheck-specific fields (backward compatibility + state tracking)
                        'detected_new_links_count': 0,
                        'all_links_snapshot': list(current_links_set),
                    }
                )

                return self.format_success(
                    'No new links detected since last check',
                    page_state=f'Total links on page: {len(current_links)}'
                )

            # Build detailed summary of first 10 validated links
            link_details = []
            for i, link_data in enumerate(validated_links[:10], 1):
                url = link_data['url']
                details = f'{i}. {url}'

                # Add validation status
                if check_https and link_data.get('https_valid') is not None:
                    https_status = '✓ HTTPS valid' if link_data['https_valid'] else '✗ HTTPS invalid'
                    details += f' | {https_status}'

                if check_status and link_data.get('status_code'):
                    status = link_data['status_code']
                    status_symbol = (
                        '✓' if str(status).startswith('2')
                        else '⚠' if str(status).startswith(('3', '4'))
                        else '✗'
                    )
                    details += f' | {status_symbol} Status: {status}'

                link_details.append(details)

            summary = '\n'.join(link_details)
            if len(new_links) > 10:
                summary += f'\n... and {len(new_links) - 10} more links'

            # Record step when new links are detected
            if self.case_recorder:
                # Build detailed model_io with all validation results
                # Ensure all data is JSON serializable using helper method
                serializable_links = [
                    {k: self._serialize_value(v) for k, v in link_data.items()}
                    for link_data in validated_links[:20]
                ]

                model_io_data = {
                    'detected_count': len(new_links),
                    'validated_links': serializable_links,
                    'check_https': check_https,
                    'check_status': check_status,
                }

                try:
                    self.case_recorder.add_step(
                        description=f'Detect dynamic links (found {len(new_links)} new)',
                        screenshots=[],
                        model_io=json.dumps(model_io_data, ensure_ascii=False, indent=2),
                        actions=[],
                        status='passed',
                        step_type='action',
                    )
                except (TypeError, ValueError) as json_err:
                    # Fallback: record minimal info if JSON serialization still fails
                    logging.warning(f'JSON serialization failed for link validation data: {json_err}')
                    self.case_recorder.add_step(
                        description=f'Detect dynamic links (found {len(new_links)} new)',
                        screenshots=[],
                        model_io=(f'Detected {len(new_links)} new links. '
                                  f'Detailed validation data could not be serialized.'),
                        actions=[],
                        status='passed',
                        step_type='action',
                    )

            return self.format_success(
                f'Detected {len(new_links)} new links',
                page_state=summary
            )

        except Exception as e:
            # Record failed step
            if self.case_recorder:
                try:
                    self.case_recorder.add_step(
                        description='Detect dynamic links (failed)',
                        screenshots=[],
                        model_io=json.dumps({
                            'error': self._serialize_value(e),
                            'error_type': type(e).__name__
                        }, ensure_ascii=False),
                        actions=[],
                        status='failed',
                        step_type='action',
                    )
                except (TypeError, ValueError) as json_err:
                    # Fallback: use plain text if JSON serialization fails
                    logging.warning(f'JSON serialization failed for error data: {json_err}')
                    self.case_recorder.add_step(
                        description='Detect dynamic links (failed)',
                        screenshots=[],
                        model_io=f'Error: {str(e)} (Type: {type(e).__name__})',
                        actions=[],
                        status='failed',
                        step_type='action',
                    )

            # Update context to indicate detection failure (enables proper assertion skip logic)
            # This ensures subsequent assertion steps know about the failure and can handle it appropriately
            self.update_action_context(
                self.ui_tester_instance,
                {
                    # Core fields (required by assertion tools)
                    'description': 'Detect dynamic links (failed)',
                    'action_type': 'DynamicLinkCheck',
                    'status': 'failed',  # Marks execution as failed for verification strategy determination
                    'result': {
                        'message': f'Link detection failed: {str(e)}',
                        'error_details': {  # Nested structure to match function_tester.py:417 expectations
                            'error_type': type(e).__name__,
                        }
                    },
                    'timestamp': datetime.now().isoformat(),

                    # DynamicLinkCheck-specific fields
                    'all_links_snapshot': [],  # No snapshot available on failure
                }
            )

            logging.error(f'Dynamic Link Detection: Unexpected error: {e}', exc_info=True)
            return self.format_failure(
                f'Link detection failed: {str(e)}',
                recovery_hints=[
                    'Ensure the page has finished loading',
                    'Check if the page is accessible (not PDF/plugin)',
                    'Verify network connectivity for validation checks',
                    'Try disabling validation (check_https=False, check_status=False) for faster execution'
                ]
            )
