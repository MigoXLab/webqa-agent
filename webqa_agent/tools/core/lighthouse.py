import asyncio
import json
import logging
import os
import tempfile

from webqa_agent.data import TestStatus
from webqa_agent.data.gen_structures import SubTestReport, SubTestResult
from webqa_agent.utils import i18n


class LighthouseMetricsTest:

    def __init__(self, report_config: dict = None):
        self.language = report_config.get('language', 'zh-CN') if report_config else 'zh-CN'
        self.localized_strings = {
            'zh-CN': i18n.get_lang_data('zh-CN').get('tools', {}).get('performance', {}),
            'en-US': i18n.get_lang_data('en-US').get('tools', {}).get('performance', {}),
        }

    def _get_text(self, key: str) -> str:
        """Get localized text for the given key."""
        return self.localized_strings.get(self.language, {}).get(key, key)

    async def _get_playwright_chromium_path(self) -> str:
        """Get Playwright chromium executable path using async API.

        Returns:
            str: Path to Playwright chromium, or None if not found
        """
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                # Get chromium browser type
                browser_type = p.chromium
                # Get executable path
                executable_path = browser_type.executable_path
                logging.debug(f'Found Playwright chromium at: {executable_path}')
                return executable_path
        except ImportError:
            logging.warning('Playwright not installed, cannot get chromium path')
            return None
        except Exception as e:
            logging.warning(f'Failed to get Playwright chromium path: {e}')
            return None

    async def run(self, url: str, browser_config: dict = None, **kwargs) -> SubTestResult:
        """Run Lighthouse test on the given URL.

        Args:
            url: The URL to test
            browser_config: Config of browser
        """
        test_name = f"Lighthouse_{browser_config['viewport']['width']}x{browser_config['viewport']['height']}"
        result = SubTestResult(name=test_name, sub_test_id='performance')

        try:
            # Check if Node.js is available
            process = await asyncio.create_subprocess_exec(
                'node', '--version', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise Exception('Node.js is not installed. Please install Node.js to run Lighthouse tests.')

            logging.debug(f'Node.js version: {stdout.decode().strip()}')

            # If browser configuration is provided, use its viewport settings
            if browser_config and browser_config.get('viewport'):
                viewport = browser_config.get('viewport')
                logging.debug(f'Using custom viewport for Lighthouse: {viewport}')
            else:
                from webqa_agent.browser.config import DEFAULT_CONFIG

                viewport = DEFAULT_CONFIG['viewport']

            lighthouse_output = await self.run_lighthouse(url, viewport)
            result.metrics = lighthouse_output['metrics']

            # Set test status based on performance score
            performance_score = result.metrics.get('overall_scores', {}).get('performance', 0)
            if performance_score >= 90:
                result.status = TestStatus.PASSED
            elif performance_score >= 50:
                result.status = TestStatus.WARNING
            else:
                result.status = TestStatus.FAILED

            result.report = [SubTestReport(**r) for r in lighthouse_output['report']]

        except Exception as e:
            error_message = f'An error occurred in LighthouseMetricsTest: {str(e)}'
            logging.error(error_message)
            result.status = TestStatus.FAILED
            result.messages = {'error': error_message}
            raise Exception(error_message)

        return result

    @staticmethod
    def _find_lighthouse_path() -> str:
        """Find the lighthouse npm package and return its core module path.

        Searches multiple locations for node_modules/lighthouse, including
        cwd, project root, ancestor directories, NODE_PATH, and home dir.

        Returns:
            str: Path to lighthouse core/index.js (with forward slashes)

        Raises:
            Exception: If lighthouse package is not found
        """
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
        logging.debug(f'Project root: {project_root}')

        possible_locations = [
            os.getcwd(),
            project_root,
        ]

        # Add ancestor directories (farthest to nearest, up to 3 levels)
        ancestor = project_root
        ancestors = []
        for _ in range(3):
            ancestor = os.path.dirname(ancestor)
            ancestors.append(ancestor)
        possible_locations.extend(reversed(ancestors))

        possible_locations.append(os.path.expanduser('~'))

        # NODE_PATH takes highest priority
        node_path = os.environ.get('NODE_PATH')
        if node_path:
            possible_locations.insert(0, node_path)

        for location in possible_locations:
            lighthouse_path = os.path.join(location, 'node_modules', 'lighthouse')
            if os.path.exists(lighthouse_path):
                logging.debug(f'Found lighthouse at: {lighthouse_path}')
                return os.path.join(lighthouse_path, 'core/index.js').replace('\\', '/')

        error_message = (
            'Lighthouse npm package not found. '
            "Please run 'npm install lighthouse' in your project directory."
        )
        logging.error(error_message)
        raise Exception(error_message)

    @staticmethod
    def _build_lighthouse_js(lighthouse_core_path: str, url: str, viewport: dict) -> str:
        """Build the JavaScript source that launches Chrome and runs
        Lighthouse.

        Args:
            lighthouse_core_path: Absolute path to lighthouse core/index.js
            url: Target URL to audit
            viewport: Dict with 'width' and 'height' keys

        Returns:
            str: Complete ES module JavaScript source code
        """
        # JSON-encode URL to safely escape special characters (quotes, backslashes)
        # json.dumps produces a quoted string like '"https://example.com"'
        safe_url = json.dumps(url)
        return f"""
import {{ pathToFileURL }} from 'url';
import {{ execSync, spawn }} from 'child_process';
import {{ existsSync, mkdtempSync, rmSync }} from 'fs';
import {{ tmpdir }} from 'os';
import {{ join }} from 'path';
import net from 'net';

function getPort() {{
    return new Promise((resolve, reject) => {{
        const server = net.createServer();
        server.listen(0, '127.0.0.1', () => {{
            const port = server.address().port;
            server.close(() => resolve(port));
        }});
        server.on('error', reject);
    }});
}}

function waitForPort(port, timeout = 15000) {{
    const start = Date.now();
    return new Promise((resolve, reject) => {{
        function tryConnect() {{
            if (Date.now() - start > timeout) {{
                return reject(new Error(`Chrome did not start within ${{timeout}}ms`));
            }}
            const socket = net.createConnection({{ port, host: '127.0.0.1' }});
            socket.on('connect', () => {{
                socket.destroy();
                resolve();
            }});
            socket.on('error', () => {{
                setTimeout(tryConnect, 100);
            }});
        }}
        tryConnect();
    }});
}}

function findChrome() {{
    // 1. Check CHROME_PATH env var (set by Python from Playwright)
    let chromePath = process.env.CHROME_PATH;
    if (chromePath && existsSync(chromePath)) return chromePath;

    console.error('CHROME_PATH not set or invalid, searching for Chrome...');

    // 2. Search Playwright chromium in user cache
    const homeDir = process.env.HOME || process.env.USERPROFILE;
    const findDirs = [
        homeDir ? `${{homeDir}}/.cache/ms-playwright` : null,
        '/ms-playwright',  // Docker system-level
    ].filter(Boolean);

    for (const dir of findDirs) {{
        try {{
            const found = execSync(
                `find ${{dir}} -name chrome -type f -executable 2>/dev/null | head -1`,
                {{ encoding: 'utf8' }}
            ).trim();
            if (found && existsSync(found)) {{
                console.error(`Found Chrome: ${{found}}`);
                return found;
            }}
        }} catch (e) {{}}
    }}

    // 3. Fallback: well-known system paths
    const systemPaths = [
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/usr/bin/chromium-browser',
        '/usr/bin/chromium',
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    ];
    for (const p of systemPaths) {{
        if (existsSync(p)) {{
            console.error(`Found Chrome at: ${{p}}`);
            return p;
        }}
    }}

    return null;
}}

async function runLighthouse() {{
    let chromeProcess;
    let userDataDir;
    let chromeKilled = false;
    try {{
        const lhUrl = pathToFileURL('{lighthouse_core_path}').href;
        const lighthouse = await import(lhUrl);

        const chromePath = findChrome();
        if (!chromePath) {{
            throw new Error('Chrome/Chromium not found. Set CHROME_PATH or install via: npx playwright install chromium');
        }}

        const port = await getPort();
        userDataDir = mkdtempSync(join(tmpdir(), 'lighthouse-'));

        console.error(`Launching Chrome on port ${{port}} with profile ${{userDataDir}}`);
        chromeProcess = spawn(chromePath, [
            '--headless',
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            `--remote-debugging-port=${{port}}`,
            `--user-data-dir=${{userDataDir}}`,
            'about:blank',
        ], {{ stdio: ['pipe', 'pipe', 'pipe'] }});

        // Detect spawn failure or premature Chrome exit via a rejecting promise
        const chromeExit = new Promise((_, reject) => {{
            chromeProcess.on('error', (err) => {{
                reject(new Error(`Failed to launch Chrome: ${{err.message}}`));
            }});
            chromeProcess.on('exit', (code, signal) => {{
                if (chromeKilled) return;
                if (code !== null && code !== 0) {{
                    reject(new Error(`Chrome exited with code ${{code}}`));
                }} else if (signal) {{
                    reject(new Error(`Chrome killed by signal ${{signal}}`));
                }}
            }});
        }});

        await Promise.race([waitForPort(port, 30000), chromeExit]);
        console.error('Chrome ready, running Lighthouse...');

        const result = await lighthouse.default({safe_url}, {{
            port,
            onlyCategories: ['performance', 'accessibility', 'best-practices', 'seo'],
            output: 'json',
            logLevel: 'info',
            formFactor: 'desktop',
            throttlingMethod: 'devtools',
            throttling: {{
                requestLatencyMs: 0,
                downloadThroughputKbps: 0,
                uploadThroughputKbps: 0,
                cpuSlowdownMultiplier: 1,
            }},
            emulatedUserAgent: false,
            screenEmulation: {{
                mobile: false,
                width: {viewport['width']},
                height: {viewport['height']},
                deviceScaleFactor: 1,
                disabled: false,
            }},
        }});

        console.log(JSON.stringify(result.lhr));
    }} catch (error) {{
        console.error('Error running Lighthouse:', error);
        process.exitCode = 1;
    }} finally {{
        chromeKilled = true;
        if (chromeProcess) {{
            chromeProcess.kill('SIGTERM');
            await new Promise((resolve) => {{
                chromeProcess.on('close', resolve);
                setTimeout(() => {{
                    try {{ chromeProcess.kill('SIGKILL'); }} catch (e) {{}}
                    resolve();
                }}, 5000);
            }});
        }}
        if (userDataDir) {{
            try {{
                rmSync(userDataDir, {{ recursive: true, force: true, maxRetries: 3, retryDelay: 500 }});
            }} catch (e) {{
                console.error('Failed to clean up temp profile:', userDataDir, e.message);
            }}
        }}
    }}
}}

runLighthouse();
"""

    @staticmethod
    def _parse_lighthouse_output(stdout_data: str, stderr_data: bytes) -> dict:
        """Parse Lighthouse JSON output from stdout.

        Args:
            stdout_data: Decoded stdout from the Node.js process
            stderr_data: Raw stderr bytes (for error context)

        Returns:
            dict: Parsed Lighthouse report JSON

        Raises:
            Exception: If JSON parsing fails or no JSON found
        """
        logging.debug(f'Lighthouse stdout: {stdout_data}')

        json_start = stdout_data.find('{')
        if json_start >= 0:
            try:
                return json.loads(stdout_data[json_start:])
            except json.JSONDecodeError as e:
                logging.error(f'Failed to parse JSON output: {e}')
                logging.error(f'JSON snippet: {stdout_data[json_start:json_start + 100]}...')
                raise Exception(f'Invalid JSON output from Lighthouse: {e}')

        logging.error(f'No JSON data found in output. Starts with: {stdout_data[:100]}')
        if not stdout_data and stderr_data:
            logging.error(f'Stderr: {stderr_data.decode()}')
        raise Exception('No JSON data found in the output. Lighthouse may have failed to generate a report.')

    @staticmethod
    def _check_execution_error(stderr_output: str) -> None:
        """Raise a descriptive exception based on Lighthouse stderr output.

        Args:
            stderr_output: Decoded stderr from the failed Node.js process

        Raises:
            Exception: With a message tailored to the specific error type
        """
        logging.error(f'Lighthouse execution failed: {stderr_output}')

        if "Cannot find package 'lighthouse'" in stderr_output or (
            'Cannot find module' in stderr_output and 'lighthouse' in stderr_output
        ):
            raise Exception('Lighthouse npm package is not installed. Please run: npm install lighthouse')

        if 'ERR_REQUIRE_ESM' in stderr_output or 'Cannot use import statement' in stderr_output:
            raise Exception(
                'ES Module error: Make sure Node.js properly handles ES modules. Try upgrading Node.js version.'
            )

        raise Exception(f'Failed to run Lighthouse: {stderr_output}')

    async def run_lighthouse(self, url, viewport=None):
        """Run Lighthouse using Node.js and return the metrics.

        Args:
            url: The URL to test
            viewport: The viewport configuration for the browser

        Returns:
            dict: Performance metrics
        """
        if viewport is None:
            viewport = {'width': 1280, 'height': 900}

        lighthouse_core_path = self._find_lighthouse_path()
        js_source = self._build_lighthouse_js(lighthouse_core_path, url, viewport)

        # Get Playwright chromium path to pass as CHROME_PATH env var
        chrome_path = await self._get_playwright_chromium_path()
        if chrome_path:
            logging.info(f'Using Playwright chromium at: {chrome_path}')
        else:
            logging.warning('Could not find Playwright chromium, will use default Chrome search')

        env = os.environ.copy()
        if chrome_path:
            env['CHROME_PATH'] = chrome_path

        with tempfile.TemporaryDirectory() as temp_dir:
            js_file_path = os.path.join(temp_dir, 'run_lighthouse.mjs')
            with open(js_file_path, 'w') as f:
                f.write(js_source)

            try:
                logging.debug('Running Lighthouse via Node.js')
                process = await asyncio.create_subprocess_exec(
                    'node', js_file_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(), timeout=300  # 5 minute timeout
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    raise Exception(
                        'Lighthouse execution timed out after 5 minutes. '
                        'The target page may be unresponsive or Lighthouse is stuck.'
                    )

                if process.returncode != 0:
                    self._check_execution_error(stderr.decode())

                report_data = self._parse_lighthouse_output(stdout.decode(), stderr)
                return self.extract_ai_optimized_performance_data(report_data)

            except FileNotFoundError:
                logging.error('Node.js not found')
                raise Exception(
                    'Make sure Node.js is installed and lighthouse npm package is available (npm install lighthouse)'
                )

    def extract_ai_optimized_performance_data(self, lhr):
        """Extract AI-optimized performance data from Lighthouse results.

        Args:
            lhr: Lighthouse result object

        Returns:
            dict: Simplified performance metrics with scores and recommendations
        """

        categories = lhr.get('categories', {})
        performance_category = categories.get('performance', {})
        seo_category = categories.get('seo', {})
        audits = lhr.get('audits', {})

        # Check for valid Lighthouse results
        if not categories or not performance_category:
            raise Exception('Lighthouse execution failed: No valid performance category found in results')

        # Check if performance score is available
        if performance_category.get('score') is None:
            raise Exception('Lighthouse execution failed: Performance score is N/A or missing')

        # ====== Performance Analysis ======
        # 1. Audit statistics
        performance_audit_refs = performance_category.get('auditRefs', [])
        audit_counts = {'failed': 0, 'passed': 0, 'manual': 0, 'informative': 0, 'not_applicable': 0}

        for ref in performance_audit_refs:
            audit_id = ref.get('id')
            audit = audits.get(audit_id)
            if not audit:
                continue

            if audit.get('scoreDisplayMode') == 'manual':
                audit_counts['manual'] += 1
            elif audit.get('scoreDisplayMode') == 'informative':
                audit_counts['informative'] += 1
            elif audit.get('scoreDisplayMode') == 'notApplicable':
                audit_counts['not_applicable'] += 1
            elif audit.get('score') is not None:
                if audit.get('score') >= 0.9:
                    audit_counts['passed'] += 1
                else:
                    audit_counts['failed'] += 1

        # 3. Core performance metrics
        core_vitals = {}

        # Define all metrics to extract
        metrics_to_extract = {
            'first-contentful-paint': {'id': 'fcp', 'name': 'First Contentful Paint', 'is_core_vital': False},
            'largest-contentful-paint': {'id': 'lcp', 'name': 'Largest Contentful Paint', 'is_core_vital': True},
            'speed-index': {'id': 'si', 'name': 'Speed Index', 'is_core_vital': False},
            'cumulative-layout-shift': {'id': 'cls', 'name': 'Cumulative Layout Shift', 'is_core_vital': True},
            'total-blocking-time': {'id': 'tbt', 'name': 'Total Blocking Time', 'is_core_vital': True},
            'interactive': {'id': 'tti', 'name': 'Time to Interactive', 'is_core_vital': False},
            'max-potential-fid': {'id': 'mpfid', 'name': 'Max Potential FID', 'is_core_vital': False},
            'first-meaningful-paint': {'id': 'fmp', 'name': 'First Meaningful Paint', 'is_core_vital': False},
        }

        # Extract detailed information for each metric
        performance_metrics = {}
        for audit_id, metric_info in metrics_to_extract.items():
            if audit_id in audits:
                audit = audits.get(audit_id)
                score = audit.get('score')

                # Keep only metric scores and display values
                performance_metrics[metric_info['id']] = {
                    'name': metric_info['name'],
                    'score': score,
                    'display_value': audit.get('displayValue', 'N/A'),
                }

                # For core metrics, record whether threshold is passed
                if metric_info['is_core_vital']:
                    # Use actual performance thresholds instead of Lighthouse scores
                    passes_threshold = self._check_core_vital_threshold(
                        metric_info['id'],
                        audit.get('numericValue'),
                        audit.get('displayValue', '')
                    )
                    performance_metrics[metric_info['id']]['passes_threshold'] = passes_threshold
                    core_vitals[metric_info['id']] = performance_metrics[metric_info['id']]

        # 4. Performance opportunities and diagnostics
        opportunities = []
        diagnostics = []

        # Retrieve opportunities and diagnostics from audits
        for ref in performance_audit_refs:
            audit_id = ref.get('id')
            group = ref.get('group')

            # Skip already processed core metrics
            if audit_id in metrics_to_extract:
                continue

            audit = audits.get(audit_id)
            if not audit or audit.get('score') is None or audit.get('score') >= 0.9:
                continue

            # Determine impact level
            impact = self._determine_impact_level(audit.get('score', 0))

            # Create basic issue object - keep only necessary information
            issue = {'id': audit_id, 'title': audit.get('title', ''), 'impact': impact}

            # Add time savings information for load opportunities
            if group == 'load-opportunities' and audit.get('details'):
                if audit.get('details').get('overallSavingsMs'):
                    issue['savings_ms'] = audit.get('details').get('overallSavingsMs')

                opportunities.append(issue)
            elif group != 'load-opportunities' and audit.get('score') < 0.9:
                # Add diagnostic issues
                diagnostics.append(issue)

        # ====== SEO Analysis ======
        # 5. SEO audit analysis
        seo_issues = []
        seo_audit_refs = seo_category.get('auditRefs', [])

        for ref in seo_audit_refs:
            audit_id = ref.get('id')
            audit = audits.get(audit_id)

            if not audit:
                continue

            # Focus only on failed SEO audits
            if audit.get('score') is not None and audit.get('score') < 1.0:
                impact = self._determine_impact_level(audit.get('score', 0))

                seo_issue = {
                    'id': audit_id,
                    'title': audit.get('title', ''),
                    'description': audit.get('description', ''),
                    'impact': impact,
                    'score': audit.get('score'),
                }

                # Add specific SEO issue details
                if audit.get('details'):
                    seo_issue['details'] = self._extract_seo_issue_details(audit_id, audit.get('details'))

                seo_issues.append(seo_issue)

        # 6. Page statistics - extract only necessary statistics for generating recommendations
        page_stats = self._extract_minimal_page_stats(lhr)

        # 7. Generate prioritized recommendations (including performance and SEO)
        prioritized_recommendations = self._generate_recommendations(
            core_vitals, opportunities, diagnostics, page_stats, seo_issues, self.language
        )

        # 8. Summarize scores for each category
        score_categories = {
            'performance': performance_category,
            'accessibility': categories.get('accessibility', {}),
            'best_practices': categories.get('best-practices', {}),
            'seo': categories.get('seo', {}),
        }
        category_scores = {
            name: round(cat.get('score', 0) * 100) if cat.get('score') is not None else 0
            for name, cat in score_categories.items()
        }

        # 9.1 Four category scores
        score_str = '\n'.join([f'- {k}: {v}' for k, v in category_scores.items()])
        simple_report = [{'title': self._get_text('overall_score'), 'issues': score_str}]

        # 9.2 Prioritized recommendations / potential issues
        if prioritized_recommendations:
            simple_report.append(
                {'title': self._get_text('issues_to_improve'), 'issues': '\n'.join([f'- {rec}' for rec in prioritized_recommendations])}
            )

        # 9.3 Key performance metrics
        perf_metrics_str = '\n'.join([f"- {m['name']}: {m['display_value']}" for m in performance_metrics.values()])
        simple_report.append({'title': self._get_text('performance_metrics'), 'issues': perf_metrics_str})

        # 9.4 Return comprehensive results
        result = {
            'report': simple_report,
            'metrics': {
                'device': lhr.get('configSettings', {}).get('formFactor', 'desktop'),
                'overall_scores': category_scores,
                'performance_metrics': performance_metrics,
                'prioritized_recommendations': prioritized_recommendations,
                'seo_issues': seo_issues,
            },
        }
        logging.debug(f'Lighthouse result: {result}')
        return result

    @staticmethod
    def _extract_minimal_page_stats(lhr):
        """Extract simplified page statistics, only used for generating
        recommendations."""
        audits = lhr.get('audits', {})
        minimal_stats = {'total_size_kb': 0, 'total_requests': 0, 'third_party_size_kb': 0}

        # Total byte weight
        total_byte_weight = audits.get('total-byte-weight', {})
        if total_byte_weight and total_byte_weight.get('numericValue'):
            minimal_stats['total_size_kb'] = round(total_byte_weight.get('numericValue') / 1024)

        # Network request statistics
        network_requests = audits.get('network-requests', {})
        if network_requests and network_requests.get('details'):
            items = network_requests.get('details').get('items', [])
            minimal_stats['total_requests'] = len(items)

        # Third-party resource statistics
        third_party = audits.get('third-party-summary', {})
        if third_party and third_party.get('details'):
            third_party_items = third_party.get('details').get('items', [])
            for item in third_party_items:
                if item.get('transferSize'):
                    minimal_stats['third_party_size_kb'] += round(item.get('transferSize') / 1024)

        return minimal_stats

    @staticmethod
    def _extract_seo_issue_details(audit_id, details):
        """Extract specific details of SEO issues."""
        # Simple issue type mappings (no extra data needed)
        SIMPLE_ISSUE_TYPES = {
            'document-title': 'Missing or poor document title',
            'meta-description': 'Missing or poor meta description',
            'hreflang': 'Hreflang issues',
            'canonical': 'Canonical link issues',
            'robots-txt': 'Robots.txt issues',
            'structured-data': 'Structured data issues',
        }

        extracted_details = {}
        items = details.get('items', [])

        if audit_id in SIMPLE_ISSUE_TYPES:
            extracted_details['issue_type'] = SIMPLE_ISSUE_TYPES[audit_id]

        elif audit_id == 'link-text' and items:
            extracted_details['issue_type'] = 'Poor link text'
            extracted_details['problematic_links'] = [item.get('text', '') for item in items[:5]]

        elif audit_id == 'image-alt' and items:
            extracted_details['issue_type'] = 'Missing image alt attributes'
            extracted_details['images_count'] = len(items)

        elif audit_id == 'crawlable-anchors' and items:
            extracted_details['issue_type'] = 'Non-crawlable links'
            extracted_details['links_count'] = len(items)

        if details.get('headings') and items:
            extracted_details['items_count'] = len(items)

        return extracted_details

    @staticmethod
    def _check_core_vital_threshold(metric_id, numeric_value, display_value):
        """Check if a core vital metric passes the recommended threshold.

        Args:
            metric_id: The metric identifier (lcp, cls, tbt)
            numeric_value: The numeric value from Lighthouse audit
            display_value: The display value string

        Returns:
            bool: True if the metric passes the threshold
        """
        if numeric_value is None:
            return False

        # Define thresholds for Core Web Vitals (good thresholds)
        thresholds = {
            'lcp': 2500,  # 2.5 seconds in milliseconds
            'cls': 0.1,   # CLS score
            'tbt': 200,   # 200 milliseconds
        }

        threshold = thresholds.get(metric_id)
        if threshold is None:
            return False

        # For LCP and TBT, numeric_value is in milliseconds
        # For CLS, numeric_value is the score itself
        return numeric_value <= threshold

    @staticmethod
    def _determine_impact_level(score):
        """Determine impact level based on score."""
        if score == 0:
            return 'critical'
        elif score < 0.5:
            return 'serious'
        elif score < 0.9:
            return 'moderate'
        else:
            return 'minor'

    def _generate_recommendations(self, core_vitals, opportunities, diagnostics, page_stats, seo_issues, language='zh-CN'):
        """Generate prioritized recommendations."""
        recommendations = []

        # 1. Core Web Vitals recommendations
        vitals_thresholds = {
            'lcp': {'threshold': 2500, 'unit': 'ms', 'name': 'Largest Contentful Paint'},
            'cls': {'threshold': 0.1, 'unit': '', 'name': 'Cumulative Layout Shift'},
            'tbt': {'threshold': 200, 'unit': 'ms', 'name': 'Total Blocking Time'},
        }

        for vital_id, info in vitals_thresholds.items():
            if vital_id in core_vitals and not core_vitals[vital_id].get('passes_threshold'):
                recommendations.append(
                    f"{self._get_text('core_metrics')}: {self._get_text('improve')}{info['name']}（{self._get_text('current_value')}：{core_vitals[vital_id].get('display_value')}, {self._get_text('target')}：< {info['threshold']}{info['unit']}）"
                )

        # 2. Time-saving based opportunity recommendations (maximum 3)
        sorted_opportunities = sorted(opportunities, key=lambda x: -(x.get('savings_ms') or 0))
        for opportunity in sorted_opportunities[:3]:
            savings = ''
            if opportunity.get('savings_ms'):
                savings = f"（{self._get_text('potential_savings')}：{opportunity.get('savings_ms')}ms）"
            recommendations.append(f"{self._get_text('performance_optimization')}: {opportunity.get('title')}{savings}")

        # 3. Page statistics based recommendations
        if page_stats.get('total_size_kb', 0) > 3000:  # 超过3MB
            recommendations.append(f"{self._get_text('resource_optimization')}: {self._get_text('reduce_total_size')}（{self._get_text('current')}：{page_stats.get('total_size_kb') / 1024:.1f}MB）")

        if page_stats.get('third_party_size_kb', 0) > 500:  # 第三方资源超过500KB
            recommendations.append(
                f"{self._get_text('resource_optimization')}: {self._get_text('optimize_third_party')}（{self._get_text('current')}：{page_stats.get('third_party_size_kb') / 1024:.1f}MB）"
            )

        # 4. Diagnostic issue recommendations (maximum 2 critical issues)
        critical_diagnostics = [d for d in diagnostics if d.get('impact') == 'critical']
        for diagnostic in critical_diagnostics:
            recommendations.append(f"{self._get_text('performance_diagnosis')}: {diagnostic.get('title')}")

        # 5. SEO issue recommendations (sorted by impact level)
        seo_issues_sorted = sorted(
            seo_issues,
            key=lambda x: {'critical': 4, 'serious': 3, 'moderate': 2, 'minor': 1}.get(x.get('impact'), 0),
            reverse=True,
        )

        for seo_issue in seo_issues_sorted[:5]:  # 最多显示5个SEO问题
            recommendation = f"{self._get_text('seo')}: {seo_issue.get('title')}"

            # 添加具体的详情信息（如果有的话）
            details = seo_issue.get('details', {})
            if details.get('images_count'):
                recommendation += f" ({details['images_count']} {self._get_text('images')})"
            elif details.get('links_count'):
                recommendation += f" ({details['links_count']} {self._get_text('links')})"
            elif details.get('problematic_links'):
                recommendation += f" ({self._get_text('example')}: {', '.join(details['problematic_links'][:2])})"

            recommendations.append(recommendation)

        return recommendations
