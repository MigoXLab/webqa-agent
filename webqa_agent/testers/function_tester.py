import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from webqa_agent.actions.action_executor import ActionExecutor
from webqa_agent.actions.action_handler import ActionHandler
from webqa_agent.actions.action_types import (ActionType,
                                              get_page_agnostic_keywords)
from webqa_agent.browser import BrowserSession
from webqa_agent.browser.check import ConsoleCheck, NetworkCheck
from webqa_agent.crawler.deep_crawler import DeepCrawler, ElementKey
from webqa_agent.llm.llm_api import LLMAPI
from webqa_agent.llm.prompt import LLMPrompt

# from webqa_agent.testers.case_gen.utils.case_recorder import CentralCaseRecorder


class UITester:

    def __init__(self, llm_config: Dict[str, Any], browser_session: BrowserSession = None, ignore_rules: Optional[Dict[str, List[Dict]]] = None):
        self.llm_config = llm_config
        self.browser_session = browser_session
        self.page = None
        self.network_check = None
        self.console_check = None
        self.ignore_rules = ignore_rules or {}

        # Create component instances
        self._actions = ActionHandler()
        self._action_executor = ActionExecutor(self._actions)
        self.llm = LLMAPI(llm_config)

        # Execution status
        self.is_initialized = False
        self.test_results = []

        # Data storage related properties
        self.current_test_name: Optional[str] = None
        self.current_case_data: Optional[Dict[str, Any]] = None
        self.current_case_steps: List[Dict[str, Any]] = []
        self.all_cases_data: List[Dict[str, Any]] = []  # Store complete data for all cases
        self.step_counter: int = 0  # Used to generate step ID
        # Central recorder for unified case storage (used by LangGraph path and tools)
        # self.central_case_recorder: Optional[CentralCaseRecorder] = None

        # Context tracking for enhanced verification (backward compatible)
        self.last_action_context: Optional[Dict[str, Any]] = None
        self.execution_history: List[Dict[str, Any]] = []
        self.current_test_objective: Optional[str] = None
        self.current_success_criteria: List[str] = []  # Store test success criteria

    async def initialize(self, browser_session: BrowserSession = None):
        if browser_session:
            self.browser_session = browser_session

        if not self.browser_session:
            raise ValueError('Browser session is required')

        self.page = self.browser_session.page

        await self._actions.initialize(page=self.page)
        await self._action_executor.initialize()
        await self.llm.initialize()

        self.is_initialized = True
        return self

    async def start_session(self, url: str, cookies=None):
        if not self.is_initialized:
            raise RuntimeError('ParallelUITester not initialized')

        # Get ignore rules from config
        network_ignore_rules = self.ignore_rules.get('network', [])
        console_ignore_rules = self.ignore_rules.get('console', [])

        self.network_check = NetworkCheck(self.page, ignore_rules=network_ignore_rules)
        self.console_check = ConsoleCheck(self.page, ignore_rules=console_ignore_rules)

        await self._actions.go_to_page(self.page, url, cookies=cookies)

    async def action(self, test_step: str, file_path: str = None, viewport_only: bool = False, full_page: bool = True) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Execute AI-driven test instructions and return (step_dict,
        summary_dict)

        Args:
            test_step: Test step description
            file_path: File path (for upload operations)

        Returns:
            Tuple (step_dict, summary_dict)
        """
        if not self.is_initialized:
            raise RuntimeError('ParallelUITester not initialized')

        start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        all_execution_steps = []
        all_plans = []  # Collect all planning iterations for modelIO
        all_ordered_screenshots = []  # Collect all screenshots in chronological order
        final_execution_result = {'success': False, 'message': 'No execution performed'}
        last_check_thought = None
        global_before_screenshot = None  # Will be assigned in the first iteration

        try:
            logging.debug(f'Executing AI instruction: {test_step}')
            self.page = self.browser_session.page

            # Pre-check if operation is page-agnostic before crawling
            # This allows page-agnostic operations to execute on PDF/plugin pages
            is_likely_page_agnostic = self._is_instruction_page_agnostic(test_step)

            # # Remove any existing markers before taking the global before screenshot
            # dp_pre = DeepCrawler(self.page)
            # await dp_pre.remove_marker()

            # Take global before screenshot (not included in action step screenshots)
            global_before_screenshot = await self._actions.b64_page_screenshot(
                full_page=full_page,
                file_name='global_before_screenshot',
                context='verify'
            )

            # Iterative planning loop for tasks that need check actions
            max_iterations = 5
            for iteration in range(max_iterations):
                if iteration > 0:
                    logging.debug(f'Iterative planning loop - iteration {iteration + 1}')

                # Crawl current page state
                dp = DeepCrawler(self.page)
                prev = await dp.crawl(highlight=True, viewport_only=viewport_only, cache_dom=True)

                # Extract page status information for LLM context
                page_status = getattr(prev, 'page_status', 'SUPPORTED')
                page_type = getattr(prev, 'page_type', 'html')

                # Enhanced unsupported page handling with page-agnostic differentiation
                # Check for unsupported page types (PDF, plugins, etc.)
                if hasattr(prev, 'page_status') and prev.page_status == 'UNSUPPORTED_PAGE':
                    page_type = getattr(prev, 'page_type', 'unknown')

                    # Smart differentiation: page-agnostic operations can continue
                    if is_likely_page_agnostic:
                        logging.warning(
                            f"[WARNING] Executing '{test_step}' on {page_type} page. "
                            f'Operation is page-agnostic and will continue in degraded mode (no DOM interaction).'
                        )
                        # Page-agnostic operations don't need DOM data, allow execution to continue
                        # Note: prev will have minimal data, but that's acceptable for browser-level operations
                    else:
                        # DOM-dependent operation on unsupported page: must abort
                        error_msg = f"Cannot execute action: current page type '{page_type}' is unsupported"
                        logging.error(f'[CRITICAL] {error_msg}')

                        end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                        # Build error step structure
                        error_steps_dict = {
                            'description': f'action: {test_step}',
                            'actions': all_execution_steps,
                            'screenshots': [],
                            'modelIO': '',
                            'status': 'failed',
                            'error': error_msg,
                            'start_time': start_time,
                            'end_time': end_time,
                            'dom_diff': {}
                        }

                        # Build error result
                        error_result = {
                            'success': False,
                            'unsupported_page': True,
                            'page_type': page_type,
                            'message': error_msg,
                            'before_screenshot': global_before_screenshot,
                            'dom_diff': {}
                        }

                        return error_steps_dict, error_result

                await self._actions.update_element_buffer(prev.raw_dict())

                # Take screenshot
                marker_screenshot = await self._actions.b64_page_screenshot(
                    full_page=full_page,
                    file_name=f'action_planning_marker_iter_{iteration}',
                    context='test'
                )
                all_ordered_screenshots.append(marker_screenshot)

                # Remove marker
                await dp.remove_marker()

                # Prepare LLM input with comprehensive element data for better planning
                # Include ATTRIBUTES for input types, placeholders, and other action-relevant info
                planning_template = [
                    str(ElementKey.TAG_NAME),
                    str(ElementKey.INNER_TEXT),
                    str(ElementKey.ATTRIBUTES),
                    str(ElementKey.CENTER_X),
                    str(ElementKey.CENTER_Y)
                ]

                # If we are in an iteration, add some context about what happened before
                iterative_context = ''
                if iteration > 0 and all_execution_steps:
                    done_actions = [s.get('description', '') for s in all_execution_steps]
                    iterative_context = f"\n\n**Progress**: We have already performed these actions: {', '.join(done_actions)}."
                    if last_check_thought:
                        iterative_context += f'\n**Last Observation**: {last_check_thought}'
                    iterative_context += '\nNow continuing with the task.'

                user_prompt = self._prepare_prompt_action(
                    test_step + iterative_context,
                    prev.to_llm_json(template=planning_template),
                    LLMPrompt.planner_output_prompt,
                    page_status=page_status,
                    page_type=page_type,
                    is_page_agnostic=is_likely_page_agnostic
                )
                logging.debug(f'User prompt (iteration {iteration + 1}): {test_step + iterative_context}')

                # Generate plan
                plan_json = await self._generate_plan(LLMPrompt.planner_system_prompt, user_prompt, marker_screenshot)
                all_plans.append({
                    'iteration': iteration + 1,
                    'plan': plan_json
                })

                logging.debug(f'Generated plan (iteration {iteration + 1}): {plan_json}')

                # Execute plan
                execution_steps, execution_result = await self._execute_plan(plan_json=plan_json, file_path=file_path, viewport_only=viewport_only, full_page=full_page)

                # Aggregate steps
                all_execution_steps.extend(execution_steps)
                final_execution_result = execution_result

                # Add check LLM outputs to modelIO trace
                for step in execution_steps:
                    if step.get('raw_output'):
                        all_plans.append({
                            'iteration': iteration + 1,
                            'check': step.get('raw_output')
                        })

                # Add action screenshots from this iteration to the ordered list
                for step in execution_steps:
                    if step.get('screenshot'):
                        all_ordered_screenshots.append(step.get('screenshot'))

                # Check if we should continue iterating
                if execution_result.get('check_result') == 'continue':
                    last_check_thought = execution_result.get('thought')
                    logging.debug(f"Check action result is 'continue'. Iterating planning for task: {test_step}")
                    continue
                else:
                    break

            execution_steps = all_execution_steps
            execution_result = final_execution_result

            # Ensure the before_screenshot is the global one from the very beginning
            if global_before_screenshot:
                execution_result['before_screenshot'] = global_before_screenshot

            end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Re-fetch page after execution
            # This ensures DOM diff is computed on the correct page
            self.page = self.browser_session.page
            dp.page = self.page
            curr = await dp.crawl(highlight=True, viewport_only=viewport_only, cache_dom=True)
            diff_elems = curr.diff_dict([str(ElementKey.TAG_NAME), str(ElementKey.INNER_TEXT), str(ElementKey.ATTRIBUTES), str(ElementKey.CENTER_X), str(ElementKey.CENTER_Y)])
            if diff_elems:
                logging.debug(f'Diff element map after action: {diff_elems}')

            # Aggregate screenshots: include only valid (non-None) images in the correct chronological order
            screenshots_list = [{'type': 'base64', 'data': ss} for ss in all_ordered_screenshots if ss]

            # Build structure for case step format
            status_str = 'passed' if execution_result.get('success') else 'failed'
            execution_steps_dict = {
                # id and number will be filled by outer process (e.g. LangGraph node)
                'description': f'action: {test_step}',
                'actions': execution_steps,  # All actions aggregated together
                'screenshots': screenshots_list,  # All screenshots aggregated together
                'modelIO': json.dumps(all_plans, indent=2, ensure_ascii=False) if all_plans else '',
                'status': status_str,
                'start_time': start_time,
                'end_time': end_time,
                'dom_diff': diff_elems,  # DOM difference information
            }

            # 在execution_result中也添加DOM差异信息
            execution_result['dom_diff'] = diff_elems

            # Automatically store step data
            # self.add_step_data(execution_steps_dict, step_type="action")

            # Update execution history for context-aware verification
            self.execution_history.append({
                'description': test_step,
                'success': execution_result.get('success'),
                'timestamp': end_time,
                'dom_diff': diff_elems,
                'actions': execution_steps
            })

            # Clean up markers before returning to ensure clean state for next step
            await dp.remove_marker()

            return execution_steps_dict, execution_result

        except Exception as e:
            error_msg = f'AI instruction failed: {str(e)}'
            logging.error(error_msg)

            end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Safely get possibly undefined variables
            safe_all_ordered_screenshots = locals().get('all_ordered_screenshots', [])
            safe_plan_json = locals().get('plan_json', {})

            # Build error case execution step dictionary structure
            error_screenshots = [{'type': 'base64', 'data': ss} for ss in safe_all_ordered_screenshots if ss]

            error_execution_steps = {
                'description': f'action: {test_step}',
                'actions': locals().get('all_execution_steps', []),
                'screenshots': error_screenshots,
                'modelIO': '',  # No valid model interaction output
                'status': 'failed',
                'error': str(e),
                'start_time': start_time,
                'end_time': end_time,
            }

            self.execution_history.append({
                'description': test_step,
                'success': False,
                'timestamp': end_time,
                'dom_diff': {},
                'actions': []
            })

            # Automatically store error step data
            # self.add_step_data(error_execution_steps, step_type="action")

            return error_execution_steps, {'success': False, 'message': f'An exception occurred in action: {str(e)}'}

    def _format_execution_context(self, execution_context: Dict[str, Any]) -> str:
        """Format execution context for LLM prompt."""
        if not execution_context:
            return ''

        context_parts = []

        # Last action information
        if 'last_action' in execution_context and execution_context['last_action']:
            last_action = execution_context['last_action']
            context_parts.append(f"""**Last Action:**
                - Description: {last_action.get('description', 'N/A')}
                - Type: {last_action.get('action_type', 'N/A')}
                - Target: {last_action.get('target', 'N/A')}
                - Status: {last_action.get('status', 'unknown').upper()}
                - Result: {last_action.get('result', {}).get('message', 'N/A')}""")

            # DOM changes
            dom_diff = last_action.get('dom_diff', {})
            if dom_diff:
                context_parts.append(f'- DOM Changes: {len(dom_diff)} elements added/modified')

        # Test objective
        if 'test_objective' in execution_context and execution_context['test_objective']:
            context_parts.append(f"\n**Test Objective:** {execution_context['test_objective']}")

        # Success criteria
        if 'success_criteria' in execution_context and execution_context['success_criteria']:
            criteria_str = '; '.join(execution_context['success_criteria'])
            context_parts.append(f'**Success Criteria:** {criteria_str}')

        # Execution history
        completed = execution_context.get('completed_steps', [])
        failed = execution_context.get('failed_steps', [])
        if completed or failed:
            context_parts.append('\n**Execution History:**')
            if completed:
                context_parts.append(f'- Completed steps: {len(completed)}')
            if failed:
                context_parts.append(f'- Failed steps: {len(failed)}')

        return '\n'.join(context_parts) if context_parts else ''

    def _determine_verification_strategy(self, execution_context: Optional[Dict[str, Any]]) -> str:
        """Determine verification strategy based on execution context.

        Returns:
            "maintain" - Use original assertion (default)
            "skip" - Skip verification (prerequisite action failed)
        """
        if not execution_context:
            return 'maintain'

        last_action = execution_context.get('last_action')
        if not last_action:
            return 'maintain'

        action_status = last_action.get('status', 'unknown')

        # If last action failed with critical error, skip verification
        if action_status == 'failed':
            result = last_action.get('result', {})
            error_details = result.get('error_details', {})
            error_type = error_details.get('error_type', '')

            # Critical errors that prevent meaningful verification
            critical_errors = ['element_not_found', 'playwright_error', 'scroll_failed']
            if error_type in critical_errors:
                return 'skip'

        return 'maintain'

    def _build_context_aware_prompt(self, assertion: str, page_info: str, page_structure: str, execution_context: Dict[str, Any]) -> str:
        """Build context-aware verification prompt."""
        context_str = self._format_execution_context(execution_context)

        # Use enhanced prompt with context
        enhanced_prompt = LLMPrompt.verification_prompt_with_context.format(
            execution_context=context_str
        )

        return self._prepare_prompt_verify(
            f'assertion: {assertion}', page_info, enhanced_prompt, page_structure
        )

    async def verify(
        self,
        assertion: str,
        execution_context: Optional[Dict[str, Any]] = None,
        focus_region: Optional[str] = None,
        viewport_only: bool = False,
        full_page: bool = True,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Execute AI-driven assertion verification.

        Args:
            assertion: Assertion description
            execution_context: Optional execution context for context-aware verification
                             {
                                 "last_action": {...},
                                 "test_objective": "...",
                                 "success_criteria": [...],
                                 "completed_steps": [...],
                                 "failed_steps": [...]
                             }
            focus_region: Optional page region to focus verification on (e.g., "header navigation", "main content")

        Returns:
            Tuple (step_dict, model_output)
        """
        if not self.is_initialized:
            raise RuntimeError('ParallelUITester not initialized')

        start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        try:
            logging.debug(f'Executing AI assertion: {assertion}')

            # Use instance context if not provided as parameter
            if execution_context is None and self.last_action_context is not None:
                execution_context = {
                    'last_action': self.last_action_context,
                    'test_objective': self.current_test_objective,
                }
                logging.debug('Using instance-stored execution context for verification')

            # Determine verification strategy
            verification_strategy = self._determine_verification_strategy(execution_context)
            logging.debug(f'Verification strategy: {verification_strategy}')

            # Handle skip strategy (prerequisite action failed)
            if verification_strategy == 'skip':
                last_action = execution_context.get('last_action', {})
                skip_result = {
                    'Validation Result': 'Cannot Verify',
                    'Failure Type': 'ACTION_EXECUTION_FAILURE',
                    'Details': [
                        f"Previous action '{last_action.get('description', 'unknown')}' failed: {last_action.get('result', {}).get('message', 'unknown error')}",
                        'Verification cannot proceed without successful action execution'
                    ],
                    'Recommendation': 'Fix the action execution issue before attempting verification'
                }

                end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                skip_step = {
                    'description': f'verify: {assertion}',
                    'actions': [],
                    'screenshots': [],
                    'modelIO': json.dumps(skip_result, ensure_ascii=False),
                    'status': 'failed',
                    'start_time': start_time,
                    'end_time': end_time,
                }
                # self.add_step_data(skip_step, step_type="assertion")
                return skip_step, skip_result

            # ========================================================================
            # SCREENSHOT EXTRACTION AND MODE DETECTION
            # ========================================================================

            # Extract before/after screenshots from execution_context
            before_screenshot = None
            after_screenshot = None

            if execution_context and execution_context.get('last_action'):
                result = execution_context['last_action'].get('result', {})
                before_screenshot = result.get('before_screenshot')
                after_screenshot = result.get('after_screenshot')

            # Validate screenshots if present
            if before_screenshot and not isinstance(before_screenshot, str):
                logging.warning('before_screenshot is not a string, treating as missing')
                before_screenshot = None
            if after_screenshot and not isinstance(after_screenshot, str):
                logging.warning('after_screenshot is not a string, treating as missing')
                after_screenshot = None

            # Determine mode: comparison (both available) or fallback (either missing)
            if before_screenshot and after_screenshot:
                mode = 'comparison'
                logging.debug('Screenshot comparison mode: ENABLED (both before/after screenshots available)')
            else:
                mode = 'fallback'
                if before_screenshot:
                    logging.debug('Screenshot comparison mode: FALLBACK (only before screenshot available)')
                elif after_screenshot:
                    logging.debug('Screenshot comparison mode: FALLBACK (only after screenshot available)')
                else:
                    logging.debug('Screenshot comparison mode: FALLBACK (no before/after screenshots available)')

            # Normalize focus_region: treat empty string as None
            if focus_region is not None and not focus_region.strip():
                focus_region = None
                logging.debug('Empty focus_region provided, treating as None')

            # ========================================================================
            # MODE EXECUTION: COMPARISON vs FALLBACK
            # ========================================================================

            if mode == 'comparison':
                # ====================================================================
                # COMPARISON MODE: Use before + after screenshots
                # ====================================================================
                logging.debug('Using comparison mode with before/after screenshots')

                # Prepare images list for LLM (chronological order: before, then after)
                images_for_llm = [before_screenshot, after_screenshot]

                # Use saved context from action execution time (time-consistent verification)
                result = execution_context['last_action'].get('result', {})
                saved_url = result.get('after_action_url')
                saved_title = result.get('after_action_title')
                saved_page_structure = result.get('after_action_page_structure')

                # Fallback to current page if saved context not available (backward compatibility)
                if saved_url and saved_page_structure:
                    page_url = saved_url
                    page_title = saved_title
                    page_structure = saved_page_structure
                    logging.debug(f'Using saved action-time context: {page_url}')
                else:
                    page_url, page_title = await self.browser_session.get_url()
                    dp = DeepCrawler(self.page)
                    await dp.crawl(highlight=False, filter_text=True, viewport_only=viewport_only)
                    page_structure = dp.get_text()
                    logging.warning('Saved action context not available, using current page state (may cause time mismatch)')

                # Prepare LLM input with comparison instructions
                page_info = f'url: {page_url}, title: {page_title}'

                # Add focus region guidance if specified
                region_guidance = ''
                if focus_region:
                    region_guidance = f"\n\n**FOCUS REGION**: {focus_region}\n**INSTRUCTION**: Pay primary attention to elements within the '{focus_region}' region when evaluating the assertion."
                    logging.debug(f'Adding focus region guidance: {focus_region}')

                # Build prompt using dedicated comparison prompts
                if execution_context:
                    # Use context-aware comparison prompt
                    comparison_base_prompt = LLMPrompt.verification_prompt_with_context_comparison.format(
                        execution_context=self._format_execution_context(execution_context)
                    )
                    user_prompt = self._prepare_prompt_verify(
                        f'assertion: {assertion}', page_info, comparison_base_prompt, page_structure
                    )
                else:
                    # Use standard comparison prompt
                    comparison_base_prompt = LLMPrompt.verification_prompt_comparison
                    user_prompt = self._prepare_prompt_verify(
                        f'assertion: {assertion}', page_info, comparison_base_prompt, page_structure
                    )

                # Add region guidance if specified
                if region_guidance:
                    user_prompt = user_prompt + region_guidance

                # Store screenshots for step data
                verification_screenshots = [
                    {'type': 'base64', 'data': before_screenshot, 'label': 'Before Action'},
                    {'type': 'base64', 'data': after_screenshot, 'label': 'After Action'}
                ]

            else:
                # ====================================================================
                # FALLBACK MODE: Capture new screenshot (existing behavior)
                # ====================================================================
                logging.debug('Using fallback mode - capturing new screenshot')

                # Get page info
                page_url, page_title = await self.browser_session.get_url()
                logging.debug(f'verification page url: {page_url}, title: {page_title}')

                # Crawl current page
                dp = DeepCrawler(self.page)
                await dp.crawl(highlight=False, filter_text=True, viewport_only=viewport_only)

                # Capture new screenshot
                screenshot = await self._actions.b64_page_screenshot(
                    full_page=full_page,
                    file_name='verification_clean',
                    context='test'
                )

                # Prepare images for LLM (single screenshot)
                images_for_llm = [screenshot] if screenshot else None

                # Get page structure
                page_structure = dp.get_text()

                # Prepare LLM input (standard or context-aware, NO comparison instructions)
                page_info = f'url: {page_url}, title: {page_title}'

                # Add focus region guidance if specified
                region_guidance = ''
                if focus_region:
                    region_guidance = f"\n\n**FOCUS REGION**: {focus_region}\n**INSTRUCTION**: Pay primary attention to elements within the '{focus_region}' region when evaluating the assertion. While you should maintain awareness of the full page context, prioritize verification of elements and content specifically within this region."
                    logging.debug(f'Adding focus region guidance: {focus_region}')

                if execution_context:
                    logging.debug('Using context-aware verification prompt')
                    user_prompt = self._build_context_aware_prompt(assertion, page_info, page_structure, execution_context)
                    if region_guidance:
                        user_prompt = user_prompt + region_guidance
                else:
                    logging.debug('Using standard verification prompt')
                    base_prompt = LLMPrompt.verification_prompt
                    if region_guidance:
                        base_prompt = base_prompt + region_guidance
                    user_prompt = self._prepare_prompt_verify(
                        f'assertion: {assertion}', page_info, base_prompt, page_structure
                    )

                # Store screenshot for step data
                verification_screenshots = [{'type': 'base64', 'data': screenshot}] if screenshot else []

            # ========================================================================
            # LLM CALL (unified for both modes)
            # ========================================================================
            # Select appropriate system prompt based on mode
            if mode == 'comparison':
                system_prompt = LLMPrompt.verification_system_prompt_comparison
                logging.debug('Using comparison-specific system prompt')
            else:
                system_prompt = LLMPrompt.verification_system_prompt
                logging.debug('Using standard system prompt')

            result = await self.llm.get_llm_response(
                system_prompt, user_prompt, images=images_for_llm
            )

            # Process result
            if isinstance(result, str):
                try:
                    model_output = json.loads(result)
                except json.JSONDecodeError:
                    model_output = {
                        'Validation Result': 'Validation Failed',
                        'Details': f'LLM returned invalid JSON: {result}',
                    }
            elif isinstance(result, dict):
                model_output = result
            else:
                model_output = {
                    'Validation Result': 'Validation Failed',
                    'Details': f'LLM returned unexpected type: {type(result)}',
                }

            # Determine status
            is_passed = model_output.get('Validation Result') == 'Validation Passed'

            end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Build verification result
            status_str = 'passed' if is_passed else 'failed'
            verify_action_list = [{
                'description': 'Verify',
                'success': is_passed,
                'index': 1,
            }]
            verification_step = {
                'description': f'verify: {assertion}',
                'actions': verify_action_list,
                'screenshots': verification_screenshots,  # Use mode-specific screenshots
                'modelIO': result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                'status': status_str,
                'start_time': start_time,
                'end_time': end_time,
            }

            # Automatically store assertion step data
            # self.add_step_data(verification_step, step_type="assertion")

            return verification_step, model_output

        except Exception as e:
            error_msg = f'AI assertion failed: {str(e)}'
            logging.error(error_msg)

            # Try to get basic page information even if it fails
            try:
                basic_screenshot = await self._actions.b64_page_screenshot(
                    full_page=full_page,
                    file_name='assertion_failed',
                    context='error'
                )
            except:
                basic_screenshot = None

            end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            error_step = {
                'description': f'verify: {assertion}',
                'actions': [],
                'screenshots': [{'type': 'base64', 'data': basic_screenshot}] if basic_screenshot else [],
                'modelIO': '',
                'status': 'failed',
                'error': str(e),
                'start_time': start_time,
                'end_time': end_time,
            }

            # Error assertion step data
            # self.add_step_data(error_step, step_type="assertion")

            # Return error_step and a failed model output
            return error_step, {'Validation Result': 'Validation Failed', 'Details': error_msg}

    def _prepare_prompt_action(
        self,
        test_step: str,
        browser_elements: str,
        prompt_template: str,
        page_status: str = 'SUPPORTED',
        page_type: str = 'html',
        is_page_agnostic: bool = False
    ) -> str:
        """Prepare LLM prompt with tab context and page status awareness.

        Args:
            test_step: The test step instruction
            browser_elements: Interactive elements description
            prompt_template: The prompt template
            page_status: Page status (SUPPORTED or UNSUPPORTED_PAGE)
            page_type: Type of page content (html, pdf, plugin, etc.)
            is_page_agnostic: Whether this is a page-agnostic browser-level operation
        """
        prompt_parts = [
            f'test step: {test_step}',
            '===================='
        ]

        # Check if DOM is empty or minimal
        dom_is_empty = (
            not browser_elements or
            browser_elements.strip() in ['{}', ''] or
            browser_elements.strip() == 'null'
        )

        # Add special guidance if:
        # 1. Page is unsupported (PDF, plugin, etc.) - always show guidance
        # 2. Operation is page-agnostic - ALWAYS show guidance (regardless of DOM state)
        # Rationale: Page-agnostic operations (GoBack, GoToPage, Sleep)
        # fundamentally don't require DOM elements, so guidance should always be shown
        should_add_guidance = (
            page_status == 'UNSUPPORTED_PAGE' or
            is_page_agnostic  # Removed dom_is_empty check - always guide for page-agnostic ops
        )

        if should_add_guidance:
            # Determine appropriate status message based on actual page state
            if page_status == 'UNSUPPORTED_PAGE':
                status_message = f'Current page is {page_type} content (non-HTML). DOM interaction not possible.'
            elif dom_is_empty:
                status_message = 'Current page has no interactive elements (empty DOM or minimal content).'
            else:
                # Safety fallback (shouldn't reach here due to condition logic)
                status_message = 'Note: This is a browser-level operation.'

            # Log diagnostic information for debugging
            logging.debug(
                f'Adding page-agnostic guidance: page_status={page_status}, '
                f'is_page_agnostic={is_page_agnostic}, dom_is_empty={dom_is_empty}, '
                f"instruction='{test_step[:60]}...'"
            )

            prompt_parts.extend([
                '⚠️ **OPERATION TYPE**: Page-agnostic browser-level operation',
                f'**PAGE STATUS**: {page_status}',
                f'**IMPORTANT**: {status_message}',
                '',
                '**ALLOWED ACTIONS** (work at browser level, no DOM needed):',
                '  - GoBack, GoToPage: Browser navigation',
                '  - Sleep: Utility operations',
                '',
                '**FORBIDDEN ACTIONS** (require DOM elements):',
                '  - Tap, Input, Hover, Scroll, SelectDropdown',
                '',
                '**CRITICAL**: Plan the page-agnostic action even when pageDescription is empty!',
                '**DO NOT**: Return empty actions array for browser-level operations.',
                '===================='
            ])

        prompt_parts.append(f'pageDescription (interactive elements): {browser_elements}')
        prompt_parts.append('====================')
        prompt_parts.append(prompt_template)

        return '\n'.join(prompt_parts)

    def _prepare_prompt_verify(self, test_step: str, page_info: str, prompt_template: str, page_structure: str) -> str:
        """Prepare LLM prompt."""
        return (
            f'test step: {test_step}\n'
            f'====================\n'
            f'page info: {page_info}\n'
            f'page_structure (full text content): {page_structure}\n'
            f'====================\n'
            f'{prompt_template}'
        )

    async def _generate_plan(self, system_prompt: str, prompt: str, browser_screenshot: str) -> Dict[str, Any]:
        """Generate test plan."""
        max_retries = 2

        for attempt in range(max_retries):
            try:
                # Get LLM response
                test_plan = await self.llm.get_llm_response(system_prompt, prompt, images=browser_screenshot)

                # Process API error
                if isinstance(test_plan, dict) and 'error' in test_plan:
                    raise ValueError(f"LLM API error: {test_plan['error']}")

                # Verify response
                if not test_plan or not (isinstance(test_plan, str) and test_plan.strip()):
                    raise ValueError(f'Empty response from LLM: {test_plan}')

                try:
                    plan_json = json.loads(test_plan)
                except json.JSONDecodeError as je:
                    raise ValueError(f'Invalid JSON response: {str(je)}')

                if not plan_json.get('actions'):
                    logging.error(f'No valid actions found in plan: {test_plan}')
                    raise ValueError('No valid actions found in plan')

                return plan_json

            except (ValueError, json.JSONDecodeError) as e:
                if attempt == max_retries - 1:
                    raise ValueError(f'Failed to generate valid plan after {max_retries} attempts: {str(e)}')

                logging.warning(f'Plan generation attempt {attempt + 1} failed: {str(e)}, retrying...')
                await asyncio.sleep(1)

    async def _execute_plan(self, plan_json: Dict[str, Any], file_path: str = None, viewport_only: bool = False, full_page: bool = True) -> Dict[str, Any]:
        """Execute test plan."""
        execute_results = []
        action_count = len(plan_json.get('actions', []))

        # Capture initial screenshot BEFORE any actions (plan-level before state)
        initial_screenshot = await self._actions.b64_page_screenshot(
            full_page=full_page,
            file_name='plan_initial_screenshot',
            context='verify'
        )

        for index, action in enumerate(plan_json.get('actions', []), 1):
            action_desc = f"{action.get('type', 'Unknown')}"
            logging.debug(f'Executing step {index}/{action_count}: {action_desc}')

            try:
                # Execute action
                if action.get('type') == 'Upload' and file_path:
                    execution_result = await self._action_executor._execute_upload(action, file_path)
                elif action.get('type') == 'Check':
                    execution_result = await self._execute_plan_check(action, viewport_only=True, full_page=False)
                else:
                    execution_result = await self._action_executor.execute(action)

                # Process execution result
                if isinstance(execution_result, dict):
                    success = execution_result.get('success', False)
                    message = execution_result.get('message', 'No message provided')
                    check_result = execution_result.get('check_result')
                else:
                    success = bool(execution_result)
                    message = 'Legacy boolean result'
                    check_result = None

                # Wait for page to stabilize
                self.page = self.browser_session.page
                try:
                    await self.page.wait_for_load_state('networkidle', timeout=10000)
                    await asyncio.sleep(1.5)
                except Exception as e:
                    logging.warning(f'Page did not become network idle: {e}')
                    await asyncio.sleep(1)

                # Take screenshot
                # Optimization: If Check action already returned a screenshot with markers, use it
                if action.get('type') == 'Check' and execution_result.get('screenshot'):
                    post_action_ss = execution_result.get('screenshot')
                else:
                    post_action_ss = await self._actions.b64_page_screenshot(
                        file_name=f'action_{action_desc}_{index}',
                        context='test'
                    )

                action_result = {
                    'description': action_desc,
                    'success': success,
                    'message': message,
                    'screenshot': post_action_ss,
                    'index': index,
                }
                if check_result:
                    action_result['check_result'] = check_result
                    action_result['thought'] = execution_result.get('thought')
                    if execution_result.get('raw_output'):
                        action_result['raw_output'] = execution_result.get('raw_output')

                execute_results.append(action_result)

                if not success:
                    logging.error(f'Action {index} failed: {message}')
                    # Capture final screenshot even on failure
                    final_screenshot = await self._actions.b64_page_screenshot(
                        full_page=full_page,
                        file_name='plan_final_screenshot_failed',
                        context='verify'
                    )
                    # Capture page context at failure time (for time-consistent verification)
                    try:
                        after_action_url, after_action_title = await self.browser_session.get_url()
                    except Exception:
                        after_action_url, after_action_title = '', ''
                    # Add plan-level screenshots and context to failure result
                    action_result['before_screenshot'] = initial_screenshot
                    action_result['after_screenshot'] = final_screenshot
                    action_result['after_action_url'] = after_action_url
                    action_result['after_action_title'] = after_action_title
                    action_result['after_action_page_structure'] = ''  # 失败场景可为空
                    return execute_results, action_result

                # If Check action returned 'stop', always stop the current plan immediately
                # If it returned 'continue', we continue executing the rest of the current plan
                # (e.g., executing a 'Sleep' that was planned after the 'Check')
                if action.get('type') == 'Check' and check_result == 'stop':
                    logging.info('Check action returned stop, finishing current plan')
                    break

            except Exception as e:
                error_msg = f'Action {index} failed with error: {str(e)}'
                logging.error(error_msg)
                # Capture final screenshot even on exception
                try:
                    final_screenshot = await self._actions.b64_page_screenshot(
                        full_page=full_page,
                        file_name='plan_final_screenshot_exception',
                        context='verify'
                    )
                except:
                    final_screenshot = None

                # Capture page context at exception time (for time-consistent verification)
                try:
                    after_action_url, after_action_title = await self.browser_session.get_url()
                except Exception:
                    after_action_url, after_action_title = '', ''

                failure_result = {
                    'success': False,
                    'message': f'Exception occurred: {str(e)}',
                    'screenshot': None,
                    'before_screenshot': initial_screenshot,
                    'after_screenshot': final_screenshot,
                    'after_action_url': after_action_url,
                    'after_action_title': after_action_title,
                    'after_action_page_structure': ''  # 异常场景可为空
                }
                return execute_results, failure_result

        logging.debug('All actions executed successfully')
        # Capture final screenshot AFTER all actions (plan-level after state)
        # Optimization: Reuse the screenshot from the last executed action if possible
        if execute_results and execute_results[-1].get('screenshot'):
            final_screenshot = execute_results[-1].get('screenshot')
        else:
            final_screenshot = await self._actions.b64_page_screenshot(
                full_page=full_page,
                file_name='plan_final_screenshot',
                context='verify'
            )

        # Capture page context at action completion time (for time-consistent verification)
        try:
            after_action_url, after_action_title = await self.browser_session.get_url()
            dp_after = DeepCrawler(self.page)
            await dp_after.crawl(highlight=False, filter_text=True, viewport_only=viewport_only)
            after_action_page_structure = dp_after.get_text()[:5000]  # 限制长度避免内存开销
        except Exception as e:
            logging.warning(f'Failed to capture action-time context: {str(e)}')
            after_action_url, after_action_title = '', ''
            after_action_page_structure = ''

        post_action_ss = await self._actions.b64_page_screenshot(
            file_name='final_success',
            context='test'
        )

        final_result = {
            'success': True,
            'message': 'All actions executed successfully',
            'screenshot': post_action_ss,
            'before_screenshot': initial_screenshot,
            'after_screenshot': final_screenshot,
            'after_action_url': after_action_url,
            'after_action_title': after_action_title,
            'after_action_page_structure': after_action_page_structure,
        }

        # Find the latest Check action's result in the execution history of this plan
        for step in reversed(execute_results):
            if 'check_result' in step:
                final_result['check_result'] = step['check_result']
                final_result['thought'] = step.get('thought')
                break

        return execute_results, final_result

    async def _execute_plan_check(self, action: Dict[str, Any], viewport_only: bool = False, full_page: bool = True) -> Dict[str, Any]:
        """Execute check action to determine if the plan should continue.

        The Check action asks LLM to evaluate if a completion condition is met.
        LLM directly returns "stop" (condition met) or "continue" (condition
        not met).
        """
        condition = action.get('param', {}).get('condition', '')
        if not condition:
            return {'success': False, 'message': 'Missing condition for Check action'}

        try:
            # Capture current state for checking
            dp = DeepCrawler(self.page)
            curr = await dp.crawl(highlight=True, viewport_only=viewport_only, cache_dom=True)

            # Extract page status information
            page_status = getattr(curr, 'page_status', 'SUPPORTED')
            page_type = getattr(curr, 'page_type', 'html')

            # Take screenshot with markers
            marker_screenshot = await self._actions.b64_page_screenshot(
                full_page=full_page,
                file_name='check_action_marker',
                context='test'
            )

            # Remove markers
            await dp.remove_marker()

            # Prepare prompt for check
            check_template = [
                str(ElementKey.TAG_NAME),
                str(ElementKey.INNER_TEXT),
                str(ElementKey.ATTRIBUTES),
                str(ElementKey.CENTER_X),
                str(ElementKey.CENTER_Y)
            ]

            prompt = (
                f'Condition: {condition}\n'
                f'====================\n'
                f'PAGE STATUS: {page_status} ({page_type})\n'
                f'pageDescription: {curr.to_llm_json(template=check_template)}'
            )

            # Call LLM
            response = await self.llm.get_llm_response(LLMPrompt.check_system_prompt, prompt, images=marker_screenshot)

            if isinstance(response, str):
                try:
                    result_json = json.loads(response)
                except json.JSONDecodeError:
                    # Try to extract JSON from markdown if necessary
                    match = re.search(r'\{.*\}', response, re.DOTALL)
                    if match:
                        result_json = json.loads(match.group())
                    else:
                        raise ValueError(f'Invalid JSON response from LLM: {response}')
            else:
                result_json = response

            # Parse LLM result - LLM directly decides "stop" or "continue"
            check_result = result_json.get('result', 'stop')
            thought = result_json.get('thought', 'No thought provided')

            logging.debug(f'Check action result: {check_result} (Thought: {thought})')

            return {
                'success': True,
                'message': f'Check completed: {check_result}. {thought}',
                'check_result': check_result,
                'thought': thought,
                'raw_output': result_json
            }

        except Exception as e:
            logging.error(f'Check action failed: {str(e)}')
            return {'success': False, 'message': f'Check action failed: {str(e)}'}

    def get_monitoring_results(self) -> Dict[str, Any]:
        """Get monitoring results."""
        results = {}

        if self.network_check:
            results['network'] = self.network_check.get_messages()

        if self.console_check:
            results['console'] = self.console_check.get_messages()

        return results

    async def end_session(self) -> Dict[str, Any]:
        """End session: close monitoring, recycle resources.

        This method **must not** propagate exceptions. Any errors during gathering
        monitoring data or listener cleanup are logged, and an (possibly empty)
        results dict is always returned so that callers don't need to wrap it in
        their own try/except blocks.
        """

        results: dict = {}

        try:
            results = self.get_monitoring_results() or {}
        except BaseException as e:
            logging.warning(
                f'ParallelUITester end_session monitoring warning: {e!r} (type: {type(e)})'
            )

        for listener_name in ('console_check', 'network_check'):
            listener = getattr(self, listener_name, None)
            if listener:
                try:
                    listener.remove_listeners()
                except BaseException as e:
                    logging.warning(
                        f'ParallelUITester end_session cleanup warning while removing {listener_name}: {e!r} (type: {type(e)})'
                    )

        return results

    async def cleanup(self):
        """Comprehensive cleanup of all resources.

        This method ensures proper cleanup of:
        - Event listeners (NetworkCheck, ConsoleCheck)
        - LLM API HTTP client connections
        - Internal data structures and caches
        - Object references
        """
        # 1. End session (remove event listeners, get monitoring data)
        try:
            await self.end_session()
        except Exception as e:
            logging.warning(f'UITester.end_session error during cleanup: {e}')

        # # 2. Close LLM API client (critical for preventing connection leaks)
        # try:
        #     if self.llm:
        #         await self.llm.close()
        #         logging.debug('LLM API client closed')
        # except Exception as e:
        #     logging.warning(f'Failed to close LLM client: {e}')

        # 3. Clear references to browser objects
        self.page = None
        self.network_check = None
        self.console_check = None

        # 4. Clear data structures to free memory
        self.test_results = []
        self.all_cases_data = []
        self.current_case_steps = []
        self.execution_history = []
        self.last_action_context = None
        self.current_case_data = None

        # 5. Mark as not initialized
        self.is_initialized = False

        logging.debug('UITester cleanup completed')

    def set_current_test_name(self, name: str):
        """Set the current test case name (stub for compatibility with
        LangGraph workflow)."""
        self.current_test_name = name

    # def start_case(self, case_name: str, case_data: Optional[Dict[str, Any]] = None):
    #     """Start a new test case (deprecated in LangGraph case execution).

    #     Note: LangGraph execution now records steps via CentralCaseRecorder. This legacy
    #     storage remains for backward compatibility with non-LangGraph paths.
    #     """
    #     # Set current_test_name to ensure compatibility
    #     self.current_test_name = case_name

    #     # If there is existing case data, finish it first
    #     if self.current_case_data:
    #         logging.warning(
    #             f"Starting new case '{case_name}' while previous case '{self.current_case_data.get('name')}' is still active. Finishing previous case."
    #         )
    #         self.finish_case("interrupted", "Case was interrupted by new case start")

    #     # Calculate case index (1-based)
    #     case_index = len(self.all_cases_data) + 1
    #     formatted_case_name = f"{case_index}: {case_name}"

    #     self.current_case_data = {
    #         "name": formatted_case_name,
    #         "original_name": case_name,
    #         "case_index": case_index,
    #         "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    #         "case_info": case_data or {},
    #         "steps": [],
    #         "status": "running",
    #         "report": [],
    #     }
    #     self.current_case_steps = []
    #     self.step_counter = 0
    #     logging.debug(f"Started tracking case: {formatted_case_name} (step counter reset)")

    #     # # Initialize/Reset central recorder as primary store as well
    #     # try:
    #     #     self.central_case_recorder = CentralCaseRecorder()
    #     #     self.central_case_recorder.start_case(case_name, case_data=case_data or {})
    #     # except Exception:
    #     #     pass

    # def add_step_data(self, step_data: Dict[str, Any], step_type: str = "action"):
    #     """Add step data to current case."""
    #     # Process actions data, remove screenshots
    #     original_actions = step_data.get("actions", [])
    #     cleaned_actions = []

    #     for action in original_actions:
    #         # Copy action data, but remove screenshot field
    #         cleaned_action = {}
    #         for key, value in action.items():
    #             if key != "screenshot":  # Remove screenshot field
    #                 cleaned_action[key] = value
    #         cleaned_actions.append(cleaned_action)

    #     # Prepare formatted step (for both legacy and central recorder)
    #     self.step_counter += 1

    #     formatted_step = {
    #         "id": self.step_counter,
    #         "number": self.step_counter,
    #         "description": step_data.get("description", ""),
    #         "screenshots": step_data.get("screenshots", []),
    #         "modelIO": (
    #             step_data.get("modelIO", "")
    #             if isinstance(step_data.get("modelIO", ""), str)
    #             else json.dumps(step_data.get("modelIO", ""), ensure_ascii=False)
    #         ),
    #         "actions": cleaned_actions,  # Use cleaned actions
    #         "status": step_data.get("status", "passed"),
    #         "end_time": step_data.get("end_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    #     }

    #     # If there is error information, add to step
    #     if "error" in step_data:
    #         formatted_step["error"] = step_data["error"]

    #     # Record to legacy storage if available (for backward compatibility)
    #     if self.current_case_data:
    #         self.current_case_steps.append(formatted_step)
    #         self.current_case_data["steps"].append(formatted_step)
    #         logging.debug(f"Added step {formatted_step['id']} to legacy case storage: {self.current_test_name}")
    #     else:
    #         logging.debug(f"No active legacy case storage, skipping legacy recording")

    #     # ALWAYS record to central recorder if available (primary recording mechanism)
    #     if self.central_case_recorder:
    #         try:
    #             self.central_case_recorder.add_step(
    #                 description=formatted_step["description"],
    #                 screenshots=formatted_step["screenshots"],
    #                 model_io=formatted_step["modelIO"],
    #                 actions=formatted_step["actions"],
    #                 status=formatted_step["status"],
    #                 step_type=step_type,
    #                 end_time=formatted_step["end_time"],
    #             )
    #             logging.debug(f"✅ Step recorded to CentralCaseRecorder (type={step_type}): {formatted_step['description'][:50]}...")
    #         except Exception as e:
    #             logging.error(f"❌ Failed to record step to CentralCaseRecorder: {e}")
    #     else:
    #         logging.warning("⚠️ No CentralCaseRecorder available, step not recorded to central storage")

    # def finish_case(self, final_status: str = "completed", final_summary: Optional[str] = None):
    #     """Finish current case and save data."""
    #     if not self.current_case_data:
    #         logging.warning("No active case to finish")
    #         return

    #     case_name = self.current_case_data.get("name", "Unknown")
    #     original_name = self.current_case_data.get("original_name", case_name)
    #     steps_count = len(self.current_case_steps)

    #     # Get monitoring data
    #     # monitoring_data = self.get_monitoring_results()

    #     self.current_case_data.update(
    #         {
    #             "end_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    #             "status": final_status,
    #             "final_summary": final_summary or "",
    #             "total_steps": steps_count,
    #         }
    #     )

    #     # # Sync to central recorder if available
    #     # try:
    #     #     if self.central_case_recorder:
    #     #         self.central_case_recorder.finish_case(final_status=final_status, final_summary=final_summary or "")
    #     # except Exception:
    #     #     pass

    #     # # Update monitoring data
    #     # if monitoring_data:
    #     #     if "network" in monitoring_data:
    #     #         self.current_case_data["messages"]["network"] = monitoring_data["network"]
    #     #         logging.debug(f"Added network monitoring data for case '{case_name}'")
    #     #     if "console" in monitoring_data:
    #     #         self.current_case_data["messages"]["console"] = monitoring_data["console"]
    #     #         logging.debug(f"Added console monitoring data for case '{case_name}'")

    #     # Verify steps data
    #     stored_steps = self.current_case_data.get("steps", [])
    #     if len(stored_steps) != steps_count:
    #         logging.error(
    #             f"Steps count mismatch for case '{case_name}': stored={len(stored_steps)}, tracked={steps_count}"
    #         )

    #     # Save to all cases data
    #     self.all_cases_data.append(self.current_case_data.copy())
    #     logging.debug(
    #         f"Finished case: '{case_name}' with status: {final_status}, {steps_count} steps, total cases: {len(self.all_cases_data)}"
    #     )

    #     # Clean up current case data
    #     self.current_case_data = None
    #     self.current_case_steps = []
    #     self.step_counter = 0

    async def get_current_page(self):
        return self.browser_session.page

    def _is_instruction_page_agnostic(self, test_step: str) -> bool:
        """Check if instruction likely represents a page-agnostic operation.

        Uses priority-based detection to prevent false positives:
        1. DOM operations (HIGHEST PRIORITY) → NOT page-agnostic
        2. Action type names → page-agnostic
        3. Page-agnostic phrases → page-agnostic

        Page-agnostic operations work at browser level and don't require DOM elements:
        - Browser navigation: GoBack, GoForward, GoToPage
        - Utility: Sleep

        Args:
            test_step: The test step instruction

        Returns:
            True if operation is likely page-agnostic, False otherwise

        Examples:
            >>> self._is_instruction_page_agnostic("Tap button to switch back")
            False  # "Tap" indicates DOM operation
            >>> self._is_instruction_page_agnostic("Go back to previous page")
            True   # Legitimate navigation
            >>> self._is_instruction_page_agnostic("Click the back button")
            False  # "Click" indicates DOM operation
        """
        # Normalize instruction for case-insensitive matching
        instruction_lower = test_step.lower().replace('_', ' ').replace('-', ' ')

        # ========================================================================
        # PRIORITY 1: Check for explicit DOM operations (HIGHEST PRIORITY)
        # ========================================================================
        # If instruction explicitly mentions DOM operations, it's NOT page-agnostic
        # This prevents false positives from ambiguous keywords like "back"
        DOM_OPERATION_INDICATORS = [
            # Click/Tap operations
            'tap', 'click', 'press', 'touch',
            # Input operations
            'input', 'type', 'enter', 'fill',
            # Selection operations
            'select', 'choose', 'dropdown',
            # Mouse operations
            'hover', 'mouse over',
            # Scroll operations
            'scroll', 'swipe',
            # Drag operations
            'drag', 'drop',
            # Upload operations
            'upload', 'attach',
            # UI state changes (these require DOM interaction)
            'toggle', 'switch',  # e.g., "toggle button"
            'check', 'uncheck',  # checkboxes
            'expand', 'collapse',  # accordions
        ]

        for dom_keyword in DOM_OPERATION_INDICATORS:
            if dom_keyword in instruction_lower:
                logging.debug(
                    f"DOM operation '{dom_keyword}' detected in '{test_step[:60]}...' "
                    f'→ instruction is NOT page-agnostic'
                )
                return False

        # ========================================================================
        # PRIORITY 2: Check for action type names in instruction
        # ========================================================================
        # Handle cases where LLM uses action type directly in description
        for action_type in [ActionType.GO_BACK, ActionType.SLEEP]:
            # Case-insensitive check (handles "GoBack", "goback", "go back")
            if action_type.lower() in instruction_lower:
                logging.debug(
                    f"Action type '{action_type}' detected in '{test_step[:60]}...' "
                    f'→ instruction IS page-agnostic'
                )
                return True

        # ========================================================================
        # PRIORITY 3: Check for page-agnostic phrases
        # ========================================================================
        # Use refined keyword list with contextual phrases only
        PAGE_AGNOSTIC_KEYWORDS = get_page_agnostic_keywords()

        for keyword in PAGE_AGNOSTIC_KEYWORDS:
            if keyword in instruction_lower:
                logging.debug(
                    f"Page-agnostic keyword '{keyword}' detected in '{test_step[:60]}...' "
                    f'→ instruction IS page-agnostic'
                )
                return True

        # ========================================================================
        # DEFAULT: Assume DOM-dependent (safe default)
        # ========================================================================
        return False
