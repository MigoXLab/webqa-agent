"""Nuclei scan tool for the cc-mini engine.

Provides a dedicated, native tool for running Nuclei security scans, parsing
its JSONL output, and formatting a summary for the LLM. This prevents LLM
context truncation issues and JSON parsing hallucinations that occur when using
raw shell execution.
"""
from __future__ import annotations

import json
import logging
import shlex
import shutil
import subprocess

from ..core.tool import Tool, ToolResult

_log = logging.getLogger('cc_mini.nuclei_tool')

_DEFAULT_TIMEOUT = 1800  # 30 minutes


class NucleiScanTool(Tool):
    """Run a Nuclei security scan and return a formatted summary."""

    @property
    def name(self) -> str:
        return 'execute_nuclei_scan'

    @property
    def description(self) -> str:
        return (
            'Run an automated Nuclei security vulnerability scan against a target URL.\n'
            'This tool automatically handles template execution, JSONL parsing, '
            'and result summarization. You do not need to write the raw shell command.\n'
            'Use this whenever you need to scan for CVEs, XSS, SQLi, or other web vulnerabilities.\n'
            'Returns a structured summary of findings grouped by severity.'
        )

    @property
    def input_schema(self) -> dict:
        return {
            'type': 'object',
            'properties': {
                'url': {
                    'type': 'string',
                    'description': 'The target URL to scan (e.g. "https://example.com/api").',
                },
                'scan_types': {
                    'type': 'string',
                    'description': (
                        'Comma-separated list of vulnerability types to scan for. '
                        'Common values: cve, xss, sqli, misconfig, exposure. '
                        'Default: "xss,sqli,cve".'
                    ),
                    'default': 'xss,sqli,cve',
                },
                'mode': {
                    'type': 'string',
                    'enum': ['smoke', 'deep'],
                    'description': (
                        '"smoke": Fast scan (timeout ~5s/req, high rate limit), best for CI and quick checks.\n'
                        '"deep": Comprehensive scan (lower rate limit, higher timeout), slower but more thorough.\n'
                        'Default: "smoke".'
                    ),
                    'default': 'smoke',
                }
            },
            'required': ['url'],
        }

    def get_activity_description(self, **kwargs) -> str | None:
        url = kwargs.get('url', '')
        scan_types = kwargs.get('scan_types', 'xss,sqli,cve')
        return f'Running Nuclei scan on {url} (tags: {scan_types})'

    def is_read_only(self) -> bool:
        return False

    def execute(self, **kwargs) -> ToolResult:
        url: str = (kwargs.get('url') or '').strip()
        if not url:
            return ToolResult(content='[FAILURE] URL is required', is_error=True)

        if not shutil.which('nuclei'):
            return ToolResult(
                content='[FAILURE] nuclei binary not found in PATH. Safety scan unavailable.',
                is_error=True,
            )

        raw_scan_types: str = (kwargs.get('scan_types') or 'xss,sqli,cve').strip()

        # Map user-friendly scan types to Nuclei template tags (and clean up spaces)
        type_mapping = {
            'cve': 'cve',
            'xss': 'xss',
            'sqli': 'sqli',
            'sql': 'sqli',
            'lfi': 'lfi',
            'rce': 'rce',
            'ssrf': 'ssrf',
            'default': 'default-logins,exposed-panels,vulnerabilities',
            'misconfig': 'misconfig',
            'exposure': 'exposure'
        }

        mapped_tags: list[str] = []
        for t in raw_scan_types.split(','):
            t_clean = t.strip().lower()
            if not t_clean:
                continue
            mapped = type_mapping.get(t_clean, t_clean)
            for piece in mapped.split(','):
                p = piece.strip().lower()
                if p:
                    mapped_tags.append(p)

        tags = mapped_tags if mapped_tags else ['default-logins', 'exposed-panels']
        # Single -tags with comma-separated values (Nuclei expects comma-separated; avoids multi-flag AND quirks)
        tags_csv = ','.join(dict.fromkeys(tags))  # de-dupe preserving order
        scan_types = tags_csv

        mode: str = (kwargs.get('mode') or 'smoke').strip().lower()

        # Align with webqa_agent nuclei_tool: JSONL on stdout for parsing.
        # Nuclei v3+ uses -jsonl; -json was removed (e.g. v3.8+) and exits 2 with "flag ... not defined".
        cmd = [
            'nuclei',
            '-u', url,
            '-tags', tags_csv,
            '-jsonl',
            '-silent',
            '-nc',
        ]
        # Disable OOB/DNS callbacks (interactsh) in all modes to avoid triggering security alerts.
        cmd.extend(['-ni'])
        if mode == 'deep':
            cmd.extend(['-timeout', '30'])
        else:
            cmd.extend(['-timeout', '8'])

        _log.info('Executing Nuclei scan: %s', shlex.join(cmd))

        def run_nuclei(update_templates=False):
            if update_templates:
                _log.info('Updating nuclei templates...')
                subprocess.run(['nuclei', '-ut', '-silent'], capture_output=True, timeout=120)

            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=_DEFAULT_TIMEOUT,
            )

        def _stderr_indicates_scan_failed(stderr: str) -> bool:
            """True if stderr suggests the run did not complete a normal
            scan."""
            s = (stderr or '').lower()
            if not s.strip():
                return False
            markers = (
                'no templates provided',
                'no templates found',
                'flag provided but not defined',
                'invalid flag',
                '[ftl]',
                'update nuclei',
                'could not create runner client',
            )
            return any(m in s for m in markers)

        try:
            proc = run_nuclei(update_templates=False)

            # If templates are missing, Nuclei often prints "no templates provided" / FTL in stderr
            if proc.returncode != 0 and (
                'no templates provided' in (proc.stderr or '').lower()
                or 'no templates found' in (proc.stderr or '').lower()
                or '[ftl]' in (proc.stderr or '').lower()
            ):
                _log.info('Nuclei templates missing or empty. Updating templates and retrying...')
                proc = run_nuclei(update_templates=True)

        except subprocess.TimeoutExpired:
            return ToolResult(
                content=f'[FAILURE] Nuclei scan timed out after {_DEFAULT_TIMEOUT}s',
                is_error=True,
            )
        except OSError as exc:
            return ToolResult(
                content=f'[FAILURE] Failed to start nuclei process: {exc}',
                is_error=True,
            )

        # Parse the JSONL output
        output_text = proc.stdout.strip()
        lines = output_text.split('\n') if output_text else []

        findings_data = {
            'critical': [],
            'high': [],
            'medium': [],
            'low': [],
            'info': []
        }

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                finding = json.loads(line)
                severity = finding.get('info', {}).get('severity', 'info').lower()

                info_block = finding.get('info', {}) or {}
                finding_data = {
                    'template_id': finding.get('template-id', 'unknown'),
                    'name': info_block.get('name', 'Unknown'),
                    'severity': severity,
                    'matched_at': finding.get('matched-at', ''),
                    'description': info_block.get('description', ''),
                    'reference': info_block.get('reference', []),
                    'cvss_score': (info_block.get('classification') or {}).get('cvss-score', 'N/A'),
                }

                if severity in findings_data:
                    findings_data[severity].append(finding_data)
                else:
                    findings_data['info'].append(finding_data)
            except json.JSONDecodeError:
                continue

        # Count findings
        critical_count = len(findings_data['critical'])
        high_count = len(findings_data['high'])
        medium_count = len(findings_data['medium'])
        low_count = len(findings_data['low'])
        info_count = len(findings_data['info'])
        total = critical_count + high_count + medium_count + low_count + info_count

        # Build the summary (structure similar to webqa_agent.tools.custom.nuclei_tool messaging)
        parts = [
            f'安全扫描完成（Nuclei）：共发现 {total} 个问题。',
            f'扫描目标：{url}',
            f'扫描类型：{raw_scan_types}',
            f'扫描模式：{mode}',
            f'扫描范围：tags={scan_types}',
            '发现统计：',
            f'  Critical: {critical_count}',
            f'  High: {high_count}',
            f'  Medium: {medium_count}',
            f'  Low: {low_count}',
            f'  Info: {info_count}',
            f'  Total: {total}',
        ]

        # Match webqa_agent behavior: trust parsed JSONL for findings; avoid treating Nuclei exit codes
        # as hard failure when no JSONL lines exist (versions differ). Only fail on stderr evidence.
        if total == 0:
            if proc.returncode != 0 and _stderr_indicates_scan_failed(proc.stderr or ''):
                stderr_snippet = (proc.stderr or '').strip()[:800]
                parts.append(
                    f'\n[FAILURE] Nuclei 未正常完成扫描 (exit {proc.returncode})。'
                )
                if stderr_snippet:
                    parts.append(f'stderr:\n{stderr_snippet}')
                return ToolResult(content='\n'.join(parts), is_error=True)
            if proc.returncode != 0 and (proc.stderr or '').strip():
                _log.warning(
                    'Nuclei exited %s with no JSONL findings; stderr: %s',
                    proc.returncode,
                    (proc.stderr or '')[:500],
                )
                parts.append(
                    f'\n[NOTE] Nuclei 进程退出码 {proc.returncode}；未发现漏洞。'
                    f'若需排查可查看运行环境日志。'
                )
            parts.append('\n未发现已知漏洞。')
            return ToolResult(content='\n'.join(parts), is_error=False)

        def _add_section(title, severity_key):
            items = findings_data[severity_key]
            if not items:
                return
            parts.append(f'\n● {title} ({len(items)}个):')
            # De-duplicate by template_id + matched_at to avoid flooding
            seen = set()
            for item in items:
                sig = (item['template_id'], item['matched_at'])
                if sig in seen:
                    continue
                seen.add(sig)
                parts.append(f"  - {item['name']} ({item['template_id']}) — {item['matched_at']}")

        _add_section('Critical', 'critical')
        _add_section('High', 'high')
        _add_section('Medium', 'medium')
        _add_section('Low', 'low')
        _add_section('Info', 'info')

        is_error = (critical_count > 0 or high_count > 0)
        return ToolResult(content='\n'.join(parts), is_error=is_error)
