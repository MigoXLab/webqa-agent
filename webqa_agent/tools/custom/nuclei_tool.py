"""Nuclei scanning tool for security vulnerability testing (custom tool - optional).

This tool performs automated security vulnerability scanning using Nuclei scanner.
It can detect a wide range of security issues including:
- Common Vulnerabilities and Exposures (CVEs)
- Cross-Site Scripting (XSS)
- SQL Injection
- Security misconfigurations
- Exposed sensitive files

Key Features:
- Automated vulnerability scanning
- Customizable scan types
- Integration with Nuclei template ecosystem
- Detailed finding reports with severity levels

Requirements:
1. Nuclei binary installed (https://github.com/projectdiscovery/nuclei)
2. Internet connection for template updates (first run)
3. Appropriate permissions for security testing

Usage in test plans:
    LLM autonomously chooses when to invoke this tool based on:
    - Test objectives mentioning security testing
    - Need to verify vulnerability posture
    - Penetration testing scenarios

Example test step:
    {"action": "execute_nuclei_scan", "params": {"scan_types": "cve,xss"}}
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Type

from pydantic import BaseModel, Field

from webqa_agent.tools.base import WebQABaseTool, WebQAToolMetadata
from webqa_agent.tools.registry import register_tool

logger = logging.getLogger(__name__)


class NucleiToolSchema(BaseModel):
    """Schema for Nuclei tool parameters.

    LLM uses these Field descriptions to understand parameter usage.
    """

    scan_types: str = Field(
        default='cve,xss,sqli',
        description=(
            'Comma-separated vulnerability scan types to execute. '
            'Options: cve (CVEs), xss (Cross-Site Scripting), sqli (SQL Injection), '
            'lfi (Local File Inclusion), rce (Remote Code Execution), ssrf (SSRF)'
        )
    )


@register_tool  # Automatically registers to global registry on import
class NucleiTool(WebQABaseTool):
    """Tool for running Nuclei security vulnerability scans.

    This action-category tool performs automated security scanning to detect
    common vulnerabilities and security misconfigurations.

    Architecture:
    - Category: 'custom' - Custom user-defined tool
    - Trigger: Explicit step_type for LLM planning prompt inclusion
    - Browser Access: Requires ui_tester_instance for page URL
    - Scanner: Uses Nuclei vulnerability scanner

    Configuration:
    This tool is optional and must be explicitly enabled via configuration:
        custom_tools:
            enabled: ['nuclei']

    Dependencies:
    - nuclei binary (https://github.com/projectdiscovery/nuclei)
    - Internet connection for template updates

    **IMPORTANT**: This is a PLACEHOLDER implementation.
    Actual Nuclei integration requires subprocess execution and output parsing.
    """

    name: str = 'execute_nuclei_scan'
    description: str = (
        'Run Nuclei security vulnerability scan on the current page. '
        'Detects CVEs, XSS, SQL injection, and other security issues.'
    )
    args_schema: Type[BaseModel] = NucleiToolSchema

    # Requires browser access via ui_tester_instance
    ui_tester_instance: Any = Field(
        ...,
        description='UITester instance for accessing browser page and URL'
    )

    # Requires case_recorder for step recording
    case_recorder: Any | None = Field(
        default=None,
        description='Optional CentralCaseRecorder to record security scan steps'
    )

    @classmethod
    def get_metadata(cls) -> WebQAToolMetadata:
        """Return metadata for Nuclei tool registration."""
        return WebQAToolMetadata(
            name='execute_nuclei_scan',
            category='custom',  # Custom tool - marks as user-defined
            step_type='nuclei',  # Explicit step type for planning
            recovery_disabled=True,  # Batch tool: FAILURE = diagnostic finding, not a transient error
            description_short='Run Nuclei security vulnerability scan on current page',
            description_long=(
                'Executes Nuclei automated security scanner on the current page. '
                'Detects a wide range of security vulnerabilities and misconfigurations.\n\n'
                'Scan Types:\n'
                '  - CVE: Common Vulnerabilities and Exposures from NVD\n'
                '  - XSS: Cross-Site Scripting vulnerabilities\n'
                '  - SQLi: SQL Injection vulnerabilities\n'
                '  - LFI: Local File Inclusion vulnerabilities\n'
                '  - RCE: Remote Code Execution vulnerabilities\n'
                '  - SSRF: Server-Side Request Forgery\n\n'
                'Returns:\n'
                '  - Finding count by severity (critical, high, medium, low)\n'
                '  - Detailed vulnerability information\n'
                '  - Remediation recommendations\n\n'
                'NOTE: Placeholder implementation - requires actual Nuclei integration.'
            ),
            examples=[
                '{{"action": "execute_nuclei_scan", "params": {{}}}}',
                '{{"action": "execute_nuclei_scan", "params": {{"scan_types": "xss,sqli"}}}}',
                '{{"action": "execute_nuclei_scan", "params": {{"scan_types": "cve"}}}}',
            ],
            use_when=[
                # Security testing scenarios
                'Performing security vulnerability assessment',
                'Testing for known CVEs and security issues',
                'Checking for XSS and injection vulnerabilities',
                'Validating security posture before deployment',
                'During penetration testing engagements',

                # Compliance and audit scenarios
                'As part of security compliance audits',
                'Before major releases to catch security issues',
                'During security regression testing',
                'When testing authentication and authorization',

                # Specific use cases
                'Testing API endpoints for security vulnerabilities',
                'Scanning admin panels and sensitive pages',
                'Validating input sanitization and validation',
                'Checking for exposed sensitive files or directories',
            ],
            dont_use_when=[
                # Legal and ethical considerations
                'On production systems without explicit permission',
                'When you lack authorization for security testing',
                'On third-party sites without permission',
                'During live production traffic',

                # Technical limitations
                'On pages behind complex authentication (may fail)',
                'On dynamic content that changes frequently',
                'When network access to Nuclei templates is blocked',
                'On localhost or private network targets (unless authorized)',

                # Performance and frequency considerations
                'Too frequently (execution time varies by scan type: 10-60 seconds)',
                'Quick scans (~10s): Targeted testing with specific templates (e.g., CVE only)',
                'Comprehensive scans (~60s): Full security audit with all templates',
                'Multiple times on the same URL without changes (use once per URL or endpoint group)',
                'On every page navigation (security scans should be targeted to high-risk pages)',
            ],
            priority=20,  # Lower priority than most tools (security testing is specialized)
            dependencies=['nuclei'],  # Requires Nuclei binary installation
            dependency_types={'nuclei': 'command'},  # External command, not Python package
        )

    @classmethod
    def get_required_params(cls) -> Dict[str, str]:
        """Specify required initialization parameters.

        This tool requires:
        - ui_tester_instance: For browser access and page URL
        - case_recorder: For recording security scan steps
        """
        return {
            'ui_tester_instance': 'ui_tester_instance',
            'case_recorder': 'case_recorder',
        }

    def _format_finding(self, finding: Dict[str, Any], default_severity: str) -> str:
        """Format a single security finding with metadata.

        Args:
            finding: Normalized finding dict from _parse_nuclei_output()
            default_severity: Default severity level if not found in data

        Returns:
            Formatted finding string with severity, CVSS, and endpoint
        """
        severity = finding.get('severity', default_severity)
        matched_at = finding.get('matched_at', 'Unknown endpoint')
        cvss_score = finding.get('cvss_score', 'N/A')

        return (
            f"  - {finding.get('name', 'Unknown')} ({finding.get('template_id', 'unknown')})\n"
            f'    Severity: {severity.upper()} | CVSS: {cvss_score} | Affected: {matched_at}'
        )

    def _add_findings_details(
        self,
        message_parts: List[str],
        findings: List[Dict[str, Any]],
        header: str,
        default_severity: str
    ) -> None:
        """Add formatted findings details to message parts.

        Args:
            message_parts: List to append formatted messages to
            findings: List of findings to format
            header: Section header text
            default_severity: Default severity level for findings
        """
        if not findings:
            return

        message_parts.append(header)
        for finding in findings:
            message_parts.append(self._format_finding(finding, default_severity))

    def _map_scan_types_to_tags(self, scan_types: str) -> List[str]:
        """Map user-friendly scan types to Nuclei template tags.

        Args:
            scan_types: Comma-separated scan types (e.g., "cve,xss,sqli")

        Returns:
            List of Nuclei template tags
        """
        type_mapping = {
            'cve': 'cve',
            'xss': 'xss',
            'sqli': 'sqli',
            'sql': 'sqli',
            'lfi': 'lfi',
            'rce': 'rce',
            'ssrf': 'ssrf',
            'default': 'default-logins,exposed-panels,vulnerabilities'
        }

        tags = [
            type_mapping.get(t.strip().lower(), t.strip().lower())
            for t in scan_types.split(',')
        ]
        return tags if tags else ['default-logins', 'exposed-panels']

    def _parse_nuclei_output(self, output_lines: List[str]) -> Dict[str, Any]:
        """Parse Nuclei JSON output and categorize findings.

        Args:
            output_lines: List of JSON lines from Nuclei output

        Returns:
            Dict with categorized findings
        """
        findings = {
            'critical': [],
            'high': [],
            'medium': [],
            'low': [],
            'info': []
        }

        for line in output_lines:
            line = line.strip()
            if not line:
                continue

            try:
                finding = json.loads(line)
                severity = finding.get('info', {}).get('severity', 'info').lower()

                finding_data = {
                    'template_id': finding.get('template-id', 'unknown'),
                    'name': finding.get('info', {}).get('name', 'Unknown'),
                    'severity': severity,
                    'matched_at': finding.get('matched-at', ''),
                    'description': finding.get('info', {}).get('description', ''),
                    'reference': finding.get('info', {}).get('reference', []),
                    'cvss_score': finding.get('info', {}).get('classification', {}).get('cvss-score', 'N/A'),
                }

                if severity in findings:
                    findings[severity].append(finding_data)
                else:
                    findings['info'].append(finding_data)

            except json.JSONDecodeError:
                continue

        return findings

    async def _arun(self, scan_types: str = 'cve,xss,sqli') -> str:
        """Execute Nuclei security scan.

        Workflow:
        1. Check Nuclei installation
        2. Get current page URL
        3. Map scan types to Nuclei template tags
        4. Execute Nuclei scan with specified templates
        5. Parse JSON output for findings
        6. Categorize findings by severity
        7. Update context and record step
        8. Return formatted response

        Args:
            scan_types: Comma-separated scan types (e.g., "cve,xss,sqli")

        Returns:
            Formatted success/failure message with findings count
        """
        import shutil

        try:
            # Step 1: Check if Nuclei is installed
            if not shutil.which('nuclei'):
                logger.warning('Security Tool: Nuclei not installed')

                # Record failed step (using safe_record_step helper)
                self.safe_record_step(
                    description='Execute security scan (failed - Nuclei not installed)',
                    model_io_data={
                        'error': 'Nuclei not installed',
                        'install_url': 'https://github.com/projectdiscovery/nuclei'
                    },
                    status='failed',
                )

                return self.format_critical_error(
                    'VALIDATION_ERROR',
                    'Nuclei not installed. Install from: https://github.com/projectdiscovery/nuclei'
                )

            # Step 2: Get current page URL
            page = await self.ui_tester_instance.get_current_page()
            if not page:
                return self.format_critical_error(
                    'PAGE_CRASHED',
                    'Cannot get current page for security scan'
                )

            url = page.url
            logger.info(f'Security Tool: Running Nuclei scan on {url}')

            # Step 3: Map scan types to Nuclei tags
            tags = self._map_scan_types_to_tags(scan_types)
            tag_args = []
            for tag in tags:
                tag_args.extend(['-tags', tag])

            # Step 4: Execute Nuclei scan
            logger.info(f'Security Tool: Executing Nuclei with tags: {tags}')

            try:
                # Run Nuclei with JSON output (async to avoid blocking event loop)
                cmd = [
                    'nuclei',
                    '-u', url,
                    *tag_args,
                    '-jsonl',
                    '-silent',  # Suppress banner and progress
                    '-nc',  # No color
                    '-no-interactsh',  # Disable OOB/DNS callbacks (interactsh)
                ]

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        process.communicate(), timeout=300  # 5 minute timeout
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    logger.error('Security Tool: Nuclei scan timed out after 5 minutes')
                    return self.format_failure(
                        'Nuclei scan timed out after 5 minutes',
                        recovery_hints=[
                            'Try scanning with fewer template tags',
                            'Check network connectivity',
                            'Verify target URL is accessible'
                        ]
                    )

                # Step 5: Parse JSON output
                stdout_text = stdout_bytes.decode('utf-8', errors='replace') if stdout_bytes else ''
                output_lines = stdout_text.strip().split('\n') if stdout_text.strip() else []
                findings_data = self._parse_nuclei_output(output_lines)

            except Exception as e:
                logger.error(f'Security Tool: Nuclei execution failed: {e}')
                return self.format_failure(
                    f'Nuclei execution failed: {str(e)}',
                    recovery_hints=[
                        'Check Nuclei installation: nuclei -version',
                        'Update templates: nuclei -update-templates',
                        'Verify PATH configuration'
                    ]
                )

            # Step 6: Categorize and count findings
            findings = {
                'critical': len(findings_data['critical']),
                'high': len(findings_data['high']),
                'medium': len(findings_data['medium']),
                'low': len(findings_data['low']),
                'info': len(findings_data['info']),
                'total': sum(len(v) for v in findings_data.values())
            }

            logger.info(
                f'Security Tool: Completed. '
                f"Findings: {findings['critical']} critical, {findings['high']} high, "
                f"{findings['medium']} medium, {findings['low']} low, {findings['info']} info"
            )

            # Step 7: Build detailed result message
            message_parts = [
                f'Security scan completed for {url}',
                f'Scan types: {scan_types}',
                'Findings:',
                f"  Critical: {findings['critical']}",
                f"  High: {findings['high']}",
                f"  Medium: {findings['medium']}",
                f"  Low: {findings['low']}",
                f"  Info: {findings['info']}",
                f"  Total: {findings['total']}"
            ]

            # Add critical/high findings details with enhanced information
            self._add_findings_details(
                message_parts,
                findings_data['critical'][:3],
                '\nCritical Issues (Immediate Action Required):',
                'critical'
            )

            self._add_findings_details(
                message_parts,
                findings_data['high'][:3],
                '\nHigh Severity Issues (Urgent):',
                'high'
            )

            message = '\n'.join(message_parts)

            # Step 8: Update context for downstream tools
            self.update_action_context(
                self.ui_tester_instance,
                {
                    'description': f'Execute security scan (findings: {findings["total"]})',
                    'action_type': 'SecurityScan',
                    'status': 'success' if findings['total'] == 0 else ('critical' if findings['critical'] > 0 else 'warning'),
                    'result': {
                        'message': message,
                        'findings': findings,
                        'scan_types': scan_types,
                        'tags_used': tags,
                        'detailed_findings': {
                            'critical': findings_data['critical'][:5],  # Top 5 per severity
                            'high': findings_data['high'][:5],
                            'medium': findings_data['medium'][:5]
                        }
                    },
                    'timestamp': datetime.now().isoformat(),
                }
            )

            # Step 9: Record to case_recorder (using safe_record_step helper)
            self.safe_record_step(
                description=f'Execute security scan (findings: {findings["total"]})',
                model_io_data={
                    'url': url,
                    'scan_types': scan_types,
                    'tags_used': tags,
                    'findings': findings,
                    'critical_findings': [
                        {'name': f['name'], 'template': f['template_id']}
                        for f in findings_data['critical'][:10]
                    ],
                    'high_findings': [
                        {'name': f['name'], 'template': f['template_id']}
                        for f in findings_data['high'][:10]
                    ]
                },
                status='passed' if findings['total'] == 0 else ('critical' if findings['critical'] > 0 else 'warning'),
            )

            # Step 10: Return formatted response
            if findings['total'] == 0:
                return self.format_success(message)
            elif findings['critical'] > 0:
                return self.format_critical_error(
                    'SECURITY_CRITICAL',
                    message
                )
            elif findings['high'] > 0:
                return self.format_failure(
                    message,
                    recovery_hints=[
                        'Review high severity findings and apply patches',
                        'Implement security best practices',
                        'Run follow-up scans after remediation'
                    ]
                )
            else:
                return self.format_warning(message)

        except Exception as e:
            logger.error(f'Security Tool: Unexpected error: {e}', exc_info=True)

            # Record failed step (using safe_record_step helper)
            self.safe_record_step(
                description='Execute security scan (failed)',
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
                    'description': 'Execute security scan (failed)',
                    'action_type': 'SecurityScan',
                    'status': 'failed',
                    'result': {
                        'message': f'Security scan failed: {str(e)}',
                        'error_details': {
                            'error_type': type(e).__name__,
                        }
                    },
                    'timestamp': datetime.now().isoformat(),
                }
            )

            return self.format_failure(
                f'Security scan failed: {str(e)}',
                recovery_hints=[
                    'Check Nuclei installation and PATH configuration',
                    'Verify target is accessible',
                    'Ensure network connectivity for template updates',
                    'Check permissions for security testing'
                ]
            )
