"""Lighthouse testing tool for web performance analysis (custom tool - optional).

This tool performs comprehensive web performance analysis using Google Lighthouse.
It measures Core Web Vitals and other performance metrics including:
- Performance Score (0-100)
- First Contentful Paint (FCP)
- Largest Contentful Paint (LCP)
- Total Blocking Time (TBT)
- Cumulative Layout Shift (CLS)

Key Features:
- Reuses LighthouseMetricsTest for consistency with existing infrastructure
- Captures comprehensive performance metrics
- Returns actionable optimization recommendations
- Integrates with test reporting system

Usage in test plans:
    LLM autonomously chooses when to invoke this tool based on:
    - Test objectives mentioning performance or page speed
    - Need to verify Core Web Vitals compliance
    - Performance regression testing scenarios

Example test step:
    {"action": "execute_lighthouse_test", "params": {}}
"""
import logging
from datetime import datetime
from typing import Any, Dict, Type

from pydantic import BaseModel, Field

from webqa_agent.tools.base import WebQABaseTool, WebQAToolMetadata
from webqa_agent.tools.registry import register_tool

logger = logging.getLogger(__name__)

# Performance metric thresholds (recommended values)
PERFORMANCE_THRESHOLDS = {
    'fcp': {
        'threshold': 1800,
        'hint': 'Optimize server response time, reduce render-blocking CSS/JS, use CDN'
    },
    'lcp': {
        'threshold': 2500,
        'hint': 'Optimize largest content element (images/videos), preload critical resources, improve server response time'
    },
    'tbt': {
        'threshold': 200,
        'hint': 'Reduce JavaScript execution time, split long tasks, defer non-critical scripts'
    },
    'cls': {
        'threshold': 0.1,
        'hint': 'Add size attributes to images/videos, avoid inserting content above existing content, use CSS transforms'
    }
}


class LighthouseToolSchema(BaseModel):
    """Schema for Lighthouse tool parameters.

    LLM uses these Field descriptions to understand parameter usage.
    """

    pass  # No parameters needed - tests current page


@register_tool
class LighthouseTool(WebQABaseTool):
    """Tool for running Lighthouse performance analysis on the current page.

    This action-category tool measures page performance using Google Lighthouse
    and returns comprehensive metrics and optimization recommendations.

    Architecture:
    - Category: 'custom' - Custom user-defined tool
    - Trigger: Explicit step_type for LLM planning prompt inclusion
    - Browser Access: Requires ui_tester_instance for page URL
    - Test Implementation: Reuses LighthouseMetricsTest for consistency

    Configuration:
    This tool is optional and must be explicitly enabled via configuration:
        custom_tools:
            enabled: ['lighthouse']

    Dependencies:
    - Node.js runtime
    - lighthouse npm package (npm install -g lighthouse)
    """

    name: str = 'execute_lighthouse_test'
    description: str = (
        'Run Lighthouse performance analysis on the current page. '
        'Measures Core Web Vitals and returns performance score with recommendations.'
    )
    args_schema: Type[BaseModel] = LighthouseToolSchema

    # Requires browser access via ui_tester_instance
    ui_tester_instance: Any = Field(
        ...,
        description='UITester instance for accessing browser page and URL'
    )

    # Requires case_recorder for step recording
    case_recorder: Any | None = Field(
        default=None,
        description='Optional CentralCaseRecorder to record performance test steps'
    )

    # Requires llm_config for browser and report configuration
    llm_config: Dict = Field(
        default_factory=dict,
        description='LLM configuration including browser and report settings'
    )

    @classmethod
    def get_metadata(cls) -> WebQAToolMetadata:
        """Return metadata for Lighthouse tool registration."""
        return WebQAToolMetadata(
            name='execute_lighthouse_test',
            category='custom',  # Custom tool - marks as user-defined
            step_type='lighthouse',  # Explicit step type for planning
            recovery_disabled=True,  # Batch tool: FAILURE = diagnostic finding, not a transient error
            description_short='Run Lighthouse performance analysis on current page',
            description_long=(
                'Executes Google Lighthouse performance audit on the current page. '
                'Measures key performance metrics and Core Web Vitals.\n\n'
                'Features:\n'
                '  - Performance Score (0-100)\n'
                '  - First Contentful Paint (FCP)\n'
                '  - Largest Contentful Paint (LCP)\n'
                '  - Total Blocking Time (TBT)\n'
                '  - Cumulative Layout Shift (CLS)\n'
                '  - Speed Index and Time to Interactive (TTI)\n\n'
                'Returns:\n'
                '  - Overall performance score\n'
                '  - Individual metric values\n'
                '  - Pass/warning/fail status based on thresholds'
            ),
            examples=[
                '{{"action": "execute_lighthouse_test", "params": {{}}}}',
            ],
            use_when=[
                # Performance testing scenarios
                'Verifying page performance meets requirements',
                'Checking Core Web Vitals compliance for SEO',
                'Testing page load speed after optimization',
                'Measuring performance impact of new features',
                'During performance regression testing',

                # Quality assurance workflows
                'As part of automated test suite for performance monitoring',
                'Before major releases to catch performance degradation',
                'When testing on different network conditions',
                'During accessibility audits (Lighthouse includes accessibility metrics)',

                # Specific use cases
                'Testing e-commerce checkout flow performance',
                'Measuring single-page application (SPA) load times',
                'Validating image optimization and lazy loading',
                'Testing mobile page performance',
            ],
            dont_use_when=[
                # Inappropriate scenarios
                'Page is not fully loaded or still rendering',
                'Testing non-web content (PDFs, downloads, binary files)',
                'During interactive user flows (Lighthouse requires page reload)',
                'On pages behind authentication (Lighthouse runs in incognito)',

                # Performance considerations
                'Too frequently (Lighthouse takes 30-60 seconds per run)',
                'On every single page navigation (use sampling instead)',
                'When quick feedback is needed (use browser DevTools instead)',
            ],
            priority=30,  # Lower priority than core action tools (70-90)
            dependencies=['lighthouse'],  # Requires Node.js + lighthouse npm package
            dependency_types={'lighthouse': 'command'},  # External command, not Python package
        )

    @classmethod
    def get_required_params(cls) -> Dict[str, str]:
        """Specify required initialization parameters.

        This tool requires:
        - ui_tester_instance: For browser access and page URL
        - llm_config: For browser and report configuration
        - case_recorder: For recording performance test steps
        """
        return {
            'ui_tester_instance': 'ui_tester_instance',
            'llm_config': 'llm_config',
            'case_recorder': 'case_recorder',
        }

    async def _arun(self) -> str:
        """Execute Lighthouse performance test.

        Workflow:
        1. Get current page URL
        2. Run Lighthouse performance audit
        3. Extract key metrics (Performance Score, FCP, LCP, TBT, CLS)
        4. Format results and determine status
        5. Update context and record step
        6. Return formatted response

        Returns:
            Formatted success/warning/failure message with performance metrics
        """
        try:
            from webqa_agent.tools.core.lighthouse import LighthouseMetricsTest

            # Step 1: Get current page URL
            page = await self.ui_tester_instance.get_current_page()
            if not page:
                return self.format_critical_error(
                    'PAGE_CRASHED',
                    'Cannot get current page for performance test'
                )

            url = page.url
            logger.info(f'Performance Tool: Running Lighthouse test on {url}')

            # Step 2: Get configuration
            browser_config = self.llm_config.get('browser_config', {
                'viewport': {'width': 1280, 'height': 720}
            })
            report_config = self.llm_config.get('report_config', {'language': 'en-US'})

            # Step 3: Run Lighthouse test
            lighthouse_test = LighthouseMetricsTest(report_config=report_config)
            result = await lighthouse_test.run(url, browser_config=browser_config)

            # Step 4: Extract key metrics from nested performance_metrics dict
            performance_score = result.metrics.get('overall_scores', {}).get('performance', 0)
            perf_metrics = result.metrics.get('performance_metrics', {})

            fcp_data = perf_metrics.get('fcp', {})
            lcp_data = perf_metrics.get('lcp', {})
            tbt_data = perf_metrics.get('tbt', {})
            cls_data = perf_metrics.get('cls', {})

            fcp_display = fcp_data.get('display_value', 'N/A')
            lcp_display = lcp_data.get('display_value', 'N/A')
            tbt_display = tbt_data.get('display_value', 'N/A')
            cls_display = cls_data.get('display_value', 'N/A')

            logger.info(
                f'Performance Tool: Completed. Score: {performance_score}/100, '
                f'FCP: {fcp_display}, LCP: {lcp_display}'
            )

            # Step 5: Build result message (display_value already contains units)
            message = (
                f'Performance Score: {performance_score}/100\n'
                f'First Contentful Paint: {fcp_display}\n'
                f'Largest Contentful Paint: {lcp_display}\n'
                f'Total Blocking Time: {tbt_display}\n'
                f'Cumulative Layout Shift: {cls_display}\n'
                f'Status: {result.status.value}'
            )

            # Step 6: Build shared data structures for context and recording
            metrics_display = {
                'fcp': fcp_display,
                'lcp': lcp_display,
                'tbt': tbt_display,
                'cls': cls_display,
            }
            test_description = f'Execute performance test (score: {performance_score}/100)'
            status_label = 'success' if result.status.value == 'passed' else 'warning'

            # Step 7: Update context for downstream tools
            self.update_action_context(
                self.ui_tester_instance,
                {
                    'description': test_description,
                    'action_type': 'PerformanceTest',
                    'status': status_label,
                    'result': {
                        'message': message,
                        'performance_score': performance_score,
                        'metrics': metrics_display,
                        'test_status': result.status.value,
                    },
                    'timestamp': datetime.now().isoformat(),
                }
            )

            # Step 8: Record to case_recorder (using safe_record_step helper)
            self.safe_record_step(
                description=test_description,
                model_io_data={
                    'url': url,
                    'performance_score': performance_score,
                    'metrics': metrics_display,
                    'status': result.status.value,
                },
                status='passed' if result.status.value == 'passed' else status_label,
            )

            # Step 9: Generate targeted recovery hints based on specific metrics
            recovery_hints = []
            threshold_metrics = {'fcp': fcp_data, 'lcp': lcp_data, 'tbt': tbt_data, 'cls': cls_data}

            for metric_name, metric_data in threshold_metrics.items():
                if not metric_data:
                    continue
                threshold_config = PERFORMANCE_THRESHOLDS[metric_name]
                # Core vitals (lcp, tbt, cls) have passes_threshold from lighthouse.py;
                # for fcp, fall back to Lighthouse score < 0.9 as threshold indicator
                fails_threshold = False
                if 'passes_threshold' in metric_data:
                    fails_threshold = not metric_data['passes_threshold']
                elif metric_data.get('score') is not None and metric_data['score'] < 0.9:
                    fails_threshold = True

                if fails_threshold:
                    display = metric_data.get('display_value', 'N/A')
                    recovery_hints.append(
                        f"{metric_name.upper()} ({display}): {threshold_config['hint']}"
                    )

            # Add general hints if no specific issues or for overall optimization
            if not recovery_hints:
                recovery_hints = [
                    'Performance is good! Continue monitoring metrics',
                    'Consider further optimizations for mobile devices',
                    'Monitor real user metrics (RUM) for production insights'
                ]
            else:
                # Add general optimization tips
                recovery_hints.extend([
                    'General: Compress images (WebP/AVIF), minify CSS/JS, enable HTTP/2',
                    'General: Use lazy loading, implement caching strategies, optimize fonts'
                ])

            # Step 10: Return formatted response based on status
            if result.status.value == 'passed':
                return self.format_success(message)
            elif result.status.value == 'warning':
                # format_warning doesn't accept recovery_hints, include in message
                warning_message = message
                if recovery_hints:
                    warning_message += '\n\nOptimization recommendations:\n' + '\n'.join(f'- {hint}' for hint in recovery_hints)
                return self.format_warning(warning_message)
            else:
                return self.format_failure(message, recovery_hints=recovery_hints)

        except ImportError as e:
            logger.error(f'Performance Tool: Lighthouse dependency missing: {e}')

            # Record failed step (using safe_record_step helper)
            self.safe_record_step(
                description='Execute performance test (failed - dependency missing)',
                model_io_data={
                    'error': 'Lighthouse not installed',
                    'error_type': 'ImportError'
                },
                status='failed',
            )

            return self.format_critical_error(
                'VALIDATION_ERROR',
                'Lighthouse not installed. Install with: npm install -g lighthouse'
            )

        except Exception as e:
            logger.error(f'Performance Tool: Unexpected error: {e}', exc_info=True)

            # Record failed step (using safe_record_step helper)
            self.safe_record_step(
                description='Execute performance test (failed)',
                model_io_data={
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                status='failed',
            )

            # Update context to indicate failure
            self.update_action_context(
                self.ui_tester_instance,
                {
                    'description': 'Execute performance test (failed)',
                    'action_type': 'PerformanceTest',
                    'status': 'failed',
                    'result': {
                        'message': f'Performance test failed: {str(e)}',
                        'error_details': {
                            'error_type': type(e).__name__,
                        }
                    },
                    'timestamp': __import__('datetime').datetime.now().isoformat(),
                }
            )

            return self.format_failure(
                f'Performance test failed: {str(e)}',
                recovery_hints=[
                    'Check Node.js installation',
                    'Verify Lighthouse is installed globally',
                    'Ensure page is accessible and fully loaded',
                    'Check network connectivity'
                ]
            )
