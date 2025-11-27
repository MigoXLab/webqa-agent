"""Case Reflector for Parallel Execution.

This module provides independent reflection capability for each completed test case
in parallel execution mode. Each reflection is fully independent and doesn't require
locks due to:
1. Each case has its own browser session
2. New cases are queued via thread-safe asyncio.Queue
3. No shared state with cross-await read-write patterns

Async Reflection Architecture (Optimized):
    Case1 ──→ execute ──→ capture_snapshot (fast) ──→ release session
                                   ↓
                          CaseSnapshot (in memory)
                                   ↓
                          asyncio.create_task(reflect_from_snapshot)
                                   ↓
                          LLM call (async, doesn't block session)
                                   ↓
                          Queue.put(new_cases) if REPLAN

Benefits:
- Session released immediately after snapshot capture (~100ms)
- Reflection runs async, doesn't block session reuse
- Higher session utilization for parallel execution
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from webqa_agent.crawler.deep_crawler import DeepCrawler, ElementKey
from webqa_agent.testers.case_gen.prompts.planning_prompts import get_reflection_prompt


class CaseReflector:
    """Independent reflector for parallel case execution.

    Each case can trigger reflection independently after completion.
    No locks required - all operations are either:
    - Independent (own session, own LLM call)
    - Thread-safe (asyncio.Queue, asyncio.Event)
    - Atomic (no await between read and write)
    """

    def __init__(
        self,
        new_cases_queue: asyncio.Queue,
        finish_event: asyncio.Event,
        llm_client,  # LLM client for reflection
        business_objectives: str = "",
        language: str = 'zh-CN',
        reflection_config: Optional[Dict] = None
    ):
        """Initialize the case reflector.

        Args:
            new_cases_queue: Thread-safe queue for new cases from REPLAN
            finish_event: Event to signal FINISH decision
            llm_client: LLM client for calling reflection API
            business_objectives: Business objectives for reflection context
            language: Language for prompts ('zh-CN' or 'en-US')
            reflection_config: Optional configuration dict:
                - enabled: bool, whether reflection is enabled (default: True)
                - reflect_on_failure_only: bool, only reflect on failed cases (default: False)
                - max_new_cases_per_reflect: int, max new cases from single reflect (default: 3)
        """
        self.new_cases_queue = new_cases_queue
        self.finish_event = finish_event
        self.llm_client = llm_client
        self.business_objectives = business_objectives
        self.language = language

        # Configuration
        config = reflection_config or {}
        self.enabled = config.get('enabled', True)
        self.reflect_on_failure_only = config.get('reflect_on_failure_only', False)
        self.max_new_cases_per_reflect = config.get('max_new_cases_per_reflect', 3)

        # Statistics (atomic updates, no lock needed)
        self.stats = {
            'total_reflections': 0,
            'replan_count': 0,
            'continue_count': 0,
            'finish_count': 0,
            'new_cases_generated': 0,
            'errors': 0
        }

        logging.info(
            f"[CaseReflector] Initialized: enabled={self.enabled}, "
            f"reflect_on_failure_only={self.reflect_on_failure_only}"
        )

    async def _capture_page_state(self, session) -> Dict:
        """Capture current page state for reflection context.

        Args:
            session: Browser session

        Returns:
            Dict with page content summary
        """
        try:
            page = session.get_page()
            dp = DeepCrawler(page)

            # Crawl with highlights
            await dp.crawl(highlight=True, viewport_only=False)

            # Extract elements with position info
            reflect_template = [
                str(ElementKey.TAG_NAME),
                str(ElementKey.INNER_TEXT),
                str(ElementKey.ATTRIBUTES),
                str(ElementKey.CENTER_X),
                str(ElementKey.CENTER_Y)
            ]

            elements = dp.extract_interactive_elements(get_new_elems=False)
            page_content_summary = {}

            for elem_id, elem_data in elements.items():
                cleaned = {}
                for key in reflect_template:
                    if key in elem_data:
                        cleaned[key] = elem_data[key]
                page_content_summary[elem_id] = cleaned

            # Remove markers
            await dp.remove_marker()

            logging.debug(f"[CaseReflector] Captured {len(page_content_summary)} interactive elements")
            return page_content_summary

        except Exception as e:
            logging.warning(f"[CaseReflector] Failed to capture page state: {e}")
            return {}

    async def _take_screenshot(self, session) -> Optional[str]:
        """Take screenshot of current page.

        Args:
            session: Browser session

        Returns:
            Base64 encoded screenshot or None
        """
        try:
            page = session.get_page()
            if page:
                screenshot_bytes = await page.screenshot(full_page=True)
                import base64
                return base64.b64encode(screenshot_bytes).decode('utf-8')
        except Exception as e:
            logging.warning(f"[CaseReflector] Failed to take screenshot: {e}")
        return None

    def _build_reflection_prompt(
        self,
        case_result: Dict,
        completed_cases: List[Dict],
        remaining_cases: List[Dict],
        page_content_summary: Dict
    ) -> Tuple[str, str]:
        """Build reflection prompt from case context.

        Args:
            case_result: Current case result
            completed_cases: All completed cases
            remaining_cases: Remaining planned cases
            page_content_summary: Page elements

        Returns:
            Tuple of (system_prompt, user_prompt)
        """
        # Add current case to completed for context
        all_completed = list(completed_cases)
        if case_result not in all_completed:
            all_completed.append(case_result)

        return get_reflection_prompt(
            business_objectives=self.business_objectives,
            current_plan=remaining_cases,
            completed_cases=all_completed,
            page_content_summary=page_content_summary,
            language=self.language
        )

    def _parse_reflection_response(self, response_str: str) -> Dict:
        """Parse LLM reflection response.

        Args:
            response_str: Raw LLM response

        Returns:
            Parsed decision dict
        """
        try:
            return json.loads(response_str)
        except json.JSONDecodeError as e:
            logging.warning(f"[CaseReflector] Failed to parse response: {e}")
            # Try to extract JSON from response
            try:
                import re
                json_match = re.search(r'\{[\s\S]*\}', response_str)
                if json_match:
                    return json.loads(json_match.group())
            except Exception:
                pass

            # Default to CONTINUE on parse failure
            return {
                'decision': 'CONTINUE',
                'reasoning': f'Failed to parse response: {str(e)}'
            }

    async def _handle_decision(self, decision_data: Dict, case_name: str) -> Dict[str, Any]:
        """Handle reflection decision.

        No locks needed:
        - Event.set() is idempotent and thread-safe
        - Queue.put() is thread-safe
        - Stats updates are atomic (no await between read and write)

        Args:
            decision_data: Parsed decision from LLM
            case_name: Name of the case for logging

        Returns:
            Result dict
        """
        decision = decision_data.get('decision', 'CONTINUE').upper()
        reasoning = decision_data.get('reasoning', 'No reasoning provided')
        new_plan = decision_data.get('new_plan', [])

        logging.info(f"[CaseReflector] Decision for '{case_name}': {decision}")
        logging.debug(f"[CaseReflector] Reasoning: {reasoning}")

        if decision == 'FINISH':
            # Set finish event (idempotent, thread-safe)
            self.finish_event.set()
            self.stats['finish_count'] += 1
            logging.info("[CaseReflector] FINISH decision: signaling to stop new case launches")
            return self._create_result('FINISH', reasoning)

        elif decision == 'REPLAN' and new_plan:
            # Limit new cases
            new_cases = new_plan[:self.max_new_cases_per_reflect]

            if len(new_plan) > self.max_new_cases_per_reflect:
                logging.warning(
                    f"[CaseReflector] Truncated new cases from {len(new_plan)} "
                    f"to {self.max_new_cases_per_reflect}"
                )

            # Add metadata to new cases
            for i, case in enumerate(new_cases):
                case['status'] = 'pending'
                case['completed_steps'] = []
                case['test_context'] = {}
                case['_source'] = f'reflection_after_{case_name}'
                case['_reflection_index'] = i

            # Queue new cases (thread-safe, no lock needed)
            for case in new_cases:
                await self.new_cases_queue.put(case)

            # Update stats (atomic, no await between)
            self.stats['replan_count'] += 1
            self.stats['new_cases_generated'] += len(new_cases)

            logging.info(f"[CaseReflector] REPLAN: queued {len(new_cases)} new cases")
            return self._create_result('REPLAN', reasoning, new_cases=new_cases)

        else:
            # CONTINUE (or REPLAN without new_plan)
            if decision == 'REPLAN':
                logging.warning("[CaseReflector] REPLAN decision but no new_plan provided")

            self.stats['continue_count'] += 1
            return self._create_result('CONTINUE', reasoning)

    def _create_result(
        self,
        decision: str,
        reasoning: str,
        new_cases: List[Dict] = None,
        error: str = None
    ) -> Dict[str, Any]:
        """Create a reflection result dict.

        Args:
            decision: CONTINUE, REPLAN, or FINISH
            reasoning: Reasoning for the decision
            new_cases: New cases if REPLAN
            error: Error message if any

        Returns:
            Result dict
        """
        return {
            'decision': decision,
            'reasoning': reasoning,
            'new_cases': new_cases or [],
            'error': error
        }

    def get_stats(self) -> Dict[str, int]:
        """Get reflection statistics.

        Returns:
            Dict with stats
        """
        return dict(self.stats)

    # =========================================================================
    # Async Reflection (Snapshot + Async LLM Call)
    # =========================================================================

    async def capture_snapshot(
        self,
        case_result: Dict[str, Any],
        session,
        completed_cases: List[Dict] = None,
        remaining_cases: List[Dict] = None
    ) -> Optional[Dict]:
        """Fast snapshot capture (~100-200ms). Session can be released after this.

        Returns:
            Dict with snapshot data, or None if reflection should be skipped
        """
        if not self.enabled:
            return None
        if self.finish_event.is_set():
            return None

        case_status = case_result.get('status', 'unknown')
        if self.reflect_on_failure_only and case_status != 'failed':
            return None

        case_name = case_result.get('case_name', 'Unknown')
        logging.info(f"[CaseReflector] Capturing snapshot for: {case_name}")

        try:
            # Reuse existing methods
            page_content_summary = await self._capture_page_state(session)
            screenshot = await self._take_screenshot(session)

            return {
                'case_result': case_result,
                'case_name': case_name,
                'page_content_summary': page_content_summary,
                'screenshot': screenshot,
                'completed_cases': list(completed_cases or []),
                'remaining_cases': list(remaining_cases or [])
            }
        except Exception as e:
            logging.error(f"[CaseReflector] Snapshot capture failed: {e}")
            return None

    async def reflect_from_snapshot(self, snapshot: Dict) -> Dict[str, Any]:
        """Async reflection from snapshot. Doesn't need session.

        Args:
            snapshot: Dict from capture_snapshot()

        Returns:
            Reflection result dict
        """
        if not snapshot:
            return self._create_result('CONTINUE', 'No snapshot')

        case_name = snapshot['case_name']
        logging.info(f"[CaseReflector] Async reflection for: {case_name}")

        try:
            if self.finish_event.is_set():
                return self._create_result('CONTINUE', 'FINISH already signaled')

            # Reuse existing methods
            system_prompt, user_prompt = self._build_reflection_prompt(
                case_result=snapshot['case_result'],
                completed_cases=snapshot['completed_cases'],
                remaining_cases=snapshot['remaining_cases'],
                page_content_summary=snapshot['page_content_summary']
            )

            response_str = await self.llm_client.get_llm_response(
                system_prompt=system_prompt,
                prompt=user_prompt,
                images=snapshot['screenshot'],
                temperature=0.3
            )

            decision_data = self._parse_reflection_response(response_str)
            result = await self._handle_decision(decision_data, case_name)

            self.stats['total_reflections'] += 1
            return result

        except Exception as e:
            logging.error(f"[CaseReflector] Async reflection failed: {e}", exc_info=True)
            self.stats['errors'] += 1
            return self._create_result('CONTINUE', f'Error: {str(e)}', error=str(e))