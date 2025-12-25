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
import logging
from typing import Any, Type

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
    - Category: 'action' - Updates last_action_context for state tracking
    - Trigger: LLM autonomous choice (step_type=None) for effectiveness
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

    @classmethod
    def get_metadata(cls) -> WebQAToolMetadata:
        """Return tool metadata for registration and prompt generation."""
        return WebQAToolMetadata(
            name='detect_dynamic_links',
            category='action',  # Updates last_action_context
            step_type=None,  # LLM autonomous choice for effectiveness
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
                'detect_dynamic_links(check_https=True, check_status=True, timeout=10)',
                'detect_dynamic_links(check_https=False, check_status=True, timeout=5)'
            ],
            use_when=[
                'After clicking navigation menus, dropdowns, or tabs that reveal new links',
                'After form submissions that may display new pages or confirmation screens with links',
                'In Single Page Applications (SPAs) where links appear dynamically after routing',
                'When testing dynamic navigation features (e.g., infinite scroll pagination with page links)',
                'After interactions that trigger DOM updates revealing previously hidden links'
            ],
            dont_use_when=[
                'At initial page load (use WebAccessibilityTest for static link scanning)',
                'After non-navigation actions like typing, hovering, or scrolling that do not reveal new content',
                'On static HTML pages with no dynamic content loading',
                'When testing non-link functionality (e.g., form validation, search results content)',
                'After actions that navigate away from current page (links already checked on new page load)'
            ],
            priority=45,  # Medium-high priority (between core tools 70-90 and standalone custom 30-40)
            dependencies=[]  # No external dependencies, uses built-in modules
        )

    @classmethod
    def get_required_params(cls) -> dict:
        """Specify required initialization parameters.

        This tool requires ui_tester_instance for browser access.
        """
        return {'ui_tester_instance': 'UITester instance for browser page access'}

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

            # Step 2: Retrieve previous links from context (handle first invocation)
            previous_context = self.get_execution_context(self.ui_tester_instance)
            previous_links = set(
                previous_context.get('last_action', {}).get('all_links_snapshot', [])
            )

            if not previous_links:
                logging.debug('Dynamic Link Detection: First invocation - no previous link history')
            else:
                logging.debug(f'Dynamic Link Detection: Previous snapshot had {len(previous_links)} links')

            # Step 3: Identify new links using set difference
            current_links_set = set(current_links)
            new_links = current_links_set - previous_links

            logging.info(f'Dynamic Link Detection: Detected {len(new_links)} new links')

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
                            link_result['https_reason'] = reason
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
            self.update_action_context(
                self.ui_tester_instance,
                {
                    'action_type': 'DynamicLinkCheck',
                    'detected_new_links_count': len(new_links),
                    'all_links_snapshot': list(current_links_set),  # Store for next comparison
                }
            )

            # Step 6: Format response
            if not new_links:
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
                    status_symbol = '✓' if str(status).startswith('2') else '⚠' if str(status).startswith(('3', '4')) else '✗'
                    details += f' | {status_symbol} Status: {status}'

                link_details.append(details)

            summary = '\n'.join(link_details)
            if len(new_links) > 10:
                summary += f'\n... and {len(new_links) - 10} more links'

            return self.format_success(
                f'Detected {len(new_links)} new links',
                page_state=summary
            )

        except Exception as e:
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
