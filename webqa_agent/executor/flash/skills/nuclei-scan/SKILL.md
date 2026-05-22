---
name: nuclei-scan
description: Run a Nuclei security scan against the target URL and report
findings by severity.
when_to_use: When the task requires security scanning, vulnerability detection,
or CVE checks.
---

# Nuclei Scan Skill

Run a security vulnerability scan against the target URL using the built-in `execute_nuclei_scan` tool, and produce a structured security report.

**Important**: Before each tool call, output a short one-line description of what you are about to do (e.g. "Running smoke security scan on target URL"). This helps generate readable step-by-step reports.

**Task wording**: If the user asks for **基础 / 初步 / 基础安全漏洞 / 快速 / 冒烟 / CI 门禁**-style coverage, assume they want **time over breadth** and use `mode="smoke"` (and state in the report that coverage is intentionally reduced). Only use `mode="deep"` when they ask for **全面 / 深度 / 穷尽** scans or comparable wording.

## Prerequisites

- `execute_nuclei_scan` tool must be available (check the tool list).
- If it is missing, report: "安全扫描不可用：execute_nuclei_scan 工具未加载。"

## Phase 1: Run the Scan

Call `execute_nuclei_scan` with the target URL. You do not need to write raw shell commands; the tool automatically handles `nuclei` subprocess execution, JSONL parsing, and result summarization.

Choose a **smoke** or **deep** mode based on the user's prompt.

Example:

```json
{
  "url": "https://example.com",
  "scan_types": "xss,sqli,cve",
  "mode": "smoke"
}
```

Parameter notes:

- `url` — the exact target URL.
- `scan_types` — Comma-separated classes of vulnerabilities (`cve,xss,sqli,misconfig,exposure`).
- `mode` — `"smoke"` for a fast scan (omits OAST templates, shorter timeouts), `"deep"` for a comprehensive scan (slower).

**Do not run a second full Nuclei scan** against the same URL and the same (or broader) `-tags` just to “confirm how many hits there are” or to “see if there was only one finding.” The first scan's output is the source of truth.

## Phase 2: Report

The `execute_nuclei_scan` tool returns a pre-formatted, translated text summary grouped by severity (Critical, High, Medium, Low, Info), including template IDs, names, and affected URLs.

Structure your final step response to the user by echoing this formatted text. For example:

```
安全扫描完成（Nuclei）：共发现 N 个问题。

● Critical (1个):
  - Log4j RCE (CVE-2021-44228) — https://example.com/api/login

● High (2个):
  - SQL Injection (sqli-detect) — https://example.com/search?q=
  - Reflected XSS (xss-detect) — https://example.com/error?msg=

● Medium (1个):
  - Missing X-Frame-Options header (x-frame-options) — https://example.com/

扫描模式：smoke
扫描范围：tags=xss,sqli,cve
```

If no findings:

```
安全扫描完成（Nuclei）：未发现已知漏洞。
扫描模式：smoke
扫描范围：tags=xss,sqli,cve
```

Set your overall test status to:

- `failed` if any Critical or High findings.
- `warning` if only Medium/Low findings.
- `passed` if no findings.

## Troubleshooting: `[FTL] no templates provided for scan`

If the tool returns a warning that `nuclei` failed because there were no templates provided, it means the running environment (Docker container or local host) has an empty template library.
There is no in-agent fix for this; the environment administrator must ensure `nuclei -update-templates` succeeds during image build or initialization. In this case, report the failure as a **\[warning\]** and explain that the environment lacks nuclei templates.
