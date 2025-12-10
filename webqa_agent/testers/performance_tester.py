import asyncio
import json
import logging
import os
import tempfile

from webqa_agent.data import TestStatus
from webqa_agent.utils import i18n
from webqa_agent.data.test_structures import SubTestReport, SubTestResult


class LighthouseMetricsTest:

    def __init__(self, report_config: dict = None):
        self.language = report_config.get("language", "zh-CN") if report_config else "zh-CN"
        self.localized_strings = {
            'zh-CN': i18n.get_lang_data('zh-CN').get('testers', {}).get('performance', {}),
            'en-US': i18n.get_lang_data('en-US').get('testers', {}).get('performance', {}),
        }

    def _get_text(self, key: str) -> str:
        """Get localized text for the given key."""
        return self.localized_strings.get(self.language, {}).get(key, key)

    async def run(self, url: str, browser_config: dict = None, **kwargs) -> SubTestResult:
        """Run Lighthouse test on the given URL.

        Args:
            url: The URL to test
            browser_config: Config of browser
        """
        test_name = f"Lighthouse_{browser_config['viewport']['width']}x{browser_config['viewport']['height']}"
        result = SubTestResult(name=test_name)

        try:
            # Check if Node.js is available
            process = await asyncio.create_subprocess_exec(
                "node", "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise Exception("Node.js is not installed. Please install Node.js to run Lighthouse tests.")

            logging.debug(f"Node.js version: {stdout.decode().strip()}")

            # If browser configuration is provided, use its viewport settings
            if browser_config and browser_config.get("viewport"):
                viewport = browser_config.get("viewport")
                logging.debug(f"Using custom viewport for Lighthouse: {viewport}")
            else:
                from webqa_agent.browser.config import DEFAULT_CONFIG

                viewport = DEFAULT_CONFIG["viewport"]

            lighthouse_output = await self.run_lighthouse(url, viewport)
            result.metrics = lighthouse_output["metrics"]

            # Set test status based on performance score
            performance_score = result.metrics.get("overall_scores", {}).get("performance", 0)
            if performance_score >= 90:
                result.status = TestStatus.PASSED
            elif performance_score >= 50:
                result.status = TestStatus.WARNING
            else:
                result.status = TestStatus.FAILED

            result.report = [SubTestReport(**r) for r in lighthouse_output["report"]]

        except Exception as e:
            error_message = f"An error occurred in LighthouseMetricsTest: {str(e)}"
            logging.error(error_message)
            result.status = TestStatus.FAILED
            result.messages = {"error": error_message}
            raise Exception(error_message)

        return result

    async def run_lighthouse(self, url, viewport=None):
        """Run Lighthouse using Node.js and return the metrics.

        Args:
            url: The URL to test
            viewport: The viewport configuration for the browser

        Returns:
            dict: Performance metrics
        """
        # Get project root directory
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        logging.debug(f"{project_root}")

        # Use the provided viewport or default value
        if viewport is None:
            viewport = {"width": 1280, "height": 900}

        # Try multiple locations to find node_modules
        possible_locations = [
            # 1. Try current working directory
            os.getcwd(),
            # 2. Try project root directory
            project_root,
            # 3. Workspace root directory (three levels up)
            os.path.abspath(os.path.join(project_root, "../../../")),
            # 4. Workspace root directory (two levels up)
            os.path.abspath(os.path.join(project_root, "../../")),
            # 5. Workspace root directory (one level up)
            os.path.abspath(os.path.join(project_root, "../")),
            # 6. User home directory
            os.path.expanduser("~"),
        ]

        # If NODE_PATH environment variable exists, add it too
        if os.environ.get("NODE_PATH"):
            possible_locations.insert(0, os.environ.get("NODE_PATH"))

        # Find node_modules directory and required packages
        node_modules_path = None
        chrome_launcher_path = None
        lighthouse_path = None

        for location in possible_locations:
            test_node_modules = os.path.join(location, "node_modules")
            test_chrome_launcher = os.path.join(test_node_modules, "chrome-launcher")
            test_lighthouse = os.path.join(test_node_modules, "lighthouse")

            if os.path.exists(test_node_modules):
                node_modules_path = test_node_modules
                logging.debug(f"Found node_modules at: {node_modules_path}")

                if os.path.exists(test_chrome_launcher) and os.path.exists(test_lighthouse):
                    chrome_launcher_path = test_chrome_launcher
                    lighthouse_path = test_lighthouse
                    logging.debug(f"Found required packages at: {node_modules_path}")
                    break

        # Only try to check global npm packages when not found locally
        logging.debug(f"chrome_launcher_path: {chrome_launcher_path}")
        logging.debug(f"lighthouse_path: {lighthouse_path}")

        # If still cannot find required packages, throw error
        if not node_modules_path:
            error_message = f"Could not find node_modules directory in any of these locations. Please run 'npm install' in your project directory or install packages globally with 'npm install -g chrome-launcher lighthouse'."
            logging.error(error_message)
            raise Exception(error_message)

        if not chrome_launcher_path:
            error_message = f"chrome-launcher module not found in {node_modules_path}. Please run 'npm install chrome-launcher' in your project directory."
            logging.error(error_message)
            raise Exception(error_message)

        if not lighthouse_path:
            error_message = f"lighthouse module not found in {node_modules_path}. Please run 'npm install lighthouse' in your project directory."
            logging.error(error_message)
            raise Exception(error_message)

        # Adjust paths for correct import
        chrome_launcher_index_path = os.path.join(chrome_launcher_path, "dist/index.js").replace("\\", "/")
        lighthouse_core_path = os.path.join(lighthouse_path, "core/index.js").replace("\\", "/")

        # Create a temporary directory for reports
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a temporary JavaScript file to run Lighthouse
            js_file_path = os.path.join(temp_dir, "run_lighthouse.mjs")

            with open(js_file_path, "w") as f:
                f.write(
                    f"""
                    import {{ pathToFileURL }} from 'url';
                    import {{ execSync }} from 'child_process';
                    import {{ existsSync }} from 'fs';

                    // Hybrid module that works with both ESM and CommonJS
                async function runLighthouse() {{
                    let chrome;
                    try {{
                        const chromeUrl = pathToFileURL('{chrome_launcher_index_path}').href;
                        const lhUrl     = pathToFileURL('{lighthouse_core_path}').href;

                        // Use dynamic imports for ES modules
                        const chromeLauncher = await import(chromeUrl);
                        const lighthouse = await import(lhUrl);

                        let chromePath = process.env.CHROME_PATH;

                        if (!chromePath || !existsSync(chromePath)) {{
                            console.log('CHROME_PATH not set or invalid, searching for Chrome...');

                            const possiblePaths = [
                                '/ms-playwright/chromium-*/chrome-linux/chrome',
                                '/usr/bin/google-chrome',
                                '/usr/bin/google-chrome-stable',
                                '/usr/bin/chromium-browser',
                                '/usr/bin/chromium',
                                '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
                            ];

                            try {{
                                const findResult = execSync('find /ms-playwright -name chrome -type f -executable 2>/dev/null | head -1', {{encoding: 'utf8'}}).trim();
                                if (findResult && existsSync(findResult)) {{
                                    chromePath = findResult;
                                    console.log(`Found Chrome via find command: ${{chromePath}}`);
                                }}
                            }} catch (e) {{
                                console.log('Find command failed, trying predefined paths...');
                            }}

                            if (!chromePath || !existsSync(chromePath)) {{
                                for (const path of possiblePaths) {{
                                    if (path.includes('*')) {{
                                        try {{
                                            const expandedPath = execSync(`ls ${{path}} 2>/dev/null | head -1`, {{encoding: 'utf8'}}).trim();
                                            if (expandedPath && existsSync(expandedPath)) {{
                                                chromePath = expandedPath;
                                                console.log(`Found Chrome via wildcard: ${{chromePath}}`);
                                                break;
                                            }}
                                        }} catch (e) {{
                                        }}
                                    }} else if (existsSync(path)) {{
                                        chromePath = path;
                                        console.log(`Found Chrome at predefined path: ${{chromePath}}`);
                                        break;
                                    }}
                                }}
                            }}
                        }}

                        const launchOptions = {{
                            chromeFlags: ['--headless', '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
                        }};

                        if (chromePath && existsSync(chromePath)) {{
                            console.log(`Using Chrome at path: ${{chromePath}}`);
                            launchOptions.chromePath = chromePath;
                        }} else {{
                            console.log('Chrome path not found, using default launcher behavior');
                        }}

                        // Launch Chrome using the imported module
                        chrome = await chromeLauncher.launch(launchOptions);

                        const options = {{
                            port: chrome.port,
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
                                disabled: false
                            }}
                        }};

                        // 运行Lighthouse using the imported module
                        const result = await lighthouse.default('{url}', options);

                        console.log(JSON.stringify(result.lhr));
                    }} catch (error) {{
                        console.error('Error running Lighthouse:', error);
                        process.exit(1);
                    }} finally {{
                        if (chrome) {{
                            await chrome.kill();
                        }}
                    }}
                }}

                runLighthouse();
                """
                )

            try:
                # Run the Node.js script
                logging.debug("Running Lighthouse via Node.js")
                process = await asyncio.create_subprocess_exec(
                    "node", js_file_path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )

                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    stderr_output = stderr.decode()
                    logging.error(f"Lighthouse execution failed: {stderr_output}")

                    # Check if it's a module missing error
                    if (
                        "Cannot find package 'lighthouse'" in stderr_output
                        or "Cannot find module" in stderr_output
                        and "lighthouse" in stderr_output
                    ):
                        raise Exception("Lighthouse npm package is not installed. Please run: npm install lighthouse")
                    elif (
                        "Cannot find package 'chrome-launcher'" in stderr_output
                        or "Cannot find module" in stderr_output
                        and "chrome-launcher" in stderr_output
                    ):
                        raise Exception(
                            "Chrome-launcher npm package is not installed. Please run: npm install chrome-launcher"
                        )
                    elif "ERR_REQUIRE_ESM" in stderr_output or "Cannot use import statement" in stderr_output:
                        raise Exception(
                            "ES Module error: Make sure Node.js properly handles ES modules. Try upgrading Node.js version."
                        )
                    else:
                        raise Exception(f"Failed to run Lighthouse: {stderr_output}")

                # Parse JSON data directly from stdout
                stdout_data = stdout.decode()

                # Log complete output for debugging
                logging.debug(f"Lighthouse stdout: {stdout_data}")

                # Find start and end of JSON string
                json_start = stdout_data.find("{")
                if json_start >= 0:
                    try:
                        report_data = json.loads(stdout_data[json_start:])
                        # 提取AI优化的性能指标
                        return self.extract_ai_optimized_performance_data(report_data)
                    except json.JSONDecodeError as e:
                        logging.error(f"Failed to parse JSON output: {e}")
                        logging.error(f"JSON snippet: {stdout_data[json_start:json_start + 100]}...")
                        raise Exception(f"Invalid JSON output from Lighthouse: {e}")
                else:
                    # Provide more detailed error information
                    logging.error(f"No JSON data found in the output. Output starts with: {stdout_data[:100]}")
                    if not stdout_data:
                        logging.error("Lighthouse returned no output")
                        if stderr:
                            stderr_output = stderr.decode()
                            logging.error(f"Stderr: {stderr_output}")
                    raise Exception(
                        "No JSON data found in the output. Lighthouse may have failed to generate a report."
                    )

            except FileNotFoundError:
                logging.error("Node.js or required NPM modules not found")
                raise Exception(
                    "Make sure Node.js is installed and required NPM modules (lighthouse, chrome-launcher) are installed globally or locally"
                )

    def extract_ai_optimized_performance_data(self, lhr):
        """Extract AI-optimized performance data from Lighthouse results.

        Args:
            lhr: Lighthouse result object

        Returns:
            dict: Simplified performance metrics with scores and recommendations
        """

        # Get all audit category data
        categories = lhr.get("categories", {})
        performance_category = categories.get("performance", {})
        accessibility_category = categories.get("accessibility", {})
        best_practices_category = categories.get("best-practices", {})
        seo_category = categories.get("seo", {})
        audits = lhr.get("audits", {})
        
        # Check for valid Lighthouse results
        if not categories or not performance_category:
            raise Exception("Lighthouse execution failed: No valid performance category found in results")
        
        # Check if performance score is available
        if performance_category.get("score") is None:
            raise Exception("Lighthouse execution failed: Performance score is N/A or missing")

        # ====== Performance Analysis ======
        # 1. Overall score and metrics
        performance_score = (
            round(performance_category.get("score", 0) * 100) if performance_category.get("score") is not None else 0
        )

        # 2. Audit statistics
        performance_audit_refs = performance_category.get("auditRefs", [])
        audit_counts = {"failed": 0, "passed": 0, "manual": 0, "informative": 0, "not_applicable": 0}

        for ref in performance_audit_refs:
            audit_id = ref.get("id")
            audit = audits.get(audit_id)
            if not audit:
                continue

            if audit.get("scoreDisplayMode") == "manual":
                audit_counts["manual"] += 1
            elif audit.get("scoreDisplayMode") == "informative":
                audit_counts["informative"] += 1
            elif audit.get("scoreDisplayMode") == "notApplicable":
                audit_counts["not_applicable"] += 1
            elif audit.get("score") is not None:
                if audit.get("score") >= 0.9:
                    audit_counts["passed"] += 1
                else:
                    audit_counts["failed"] += 1

        # 3. Core performance metrics
        core_vitals = {}

        # Define all metrics to extract
        metrics_to_extract = {
            "first-contentful-paint": {"id": "fcp", "name": "First Contentful Paint", "is_core_vital": False},
            "largest-contentful-paint": {"id": "lcp", "name": "Largest Contentful Paint", "is_core_vital": True},
            "speed-index": {"id": "si", "name": "Speed Index", "is_core_vital": False},
            "cumulative-layout-shift": {"id": "cls", "name": "Cumulative Layout Shift", "is_core_vital": True},
            "total-blocking-time": {"id": "tbt", "name": "Total Blocking Time", "is_core_vital": True},
            "interactive": {"id": "tti", "name": "Time to Interactive", "is_core_vital": False},
            "max-potential-fid": {"id": "mpfid", "name": "Max Potential FID", "is_core_vital": False},
            "first-meaningful-paint": {"id": "fmp", "name": "First Meaningful Paint", "is_core_vital": False},
        }

        # Extract detailed information for each metric
        performance_metrics = {}
        for audit_id, metric_info in metrics_to_extract.items():
            if audit_id in audits:
                audit = audits.get(audit_id)
                score = audit.get("score")

                # Keep only metric scores and display values
                performance_metrics[metric_info["id"]] = {
                    "name": metric_info["name"],
                    "score": score,
                    "display_value": audit.get("displayValue", "N/A"),
                }

                # For core metrics, record whether threshold is passed
                if metric_info["is_core_vital"]:
                    # Use actual performance thresholds instead of Lighthouse scores
                    passes_threshold = self._check_core_vital_threshold(
                        metric_info["id"], 
                        audit.get("numericValue"), 
                        audit.get("displayValue", "")
                    )
                    performance_metrics[metric_info["id"]]["passes_threshold"] = passes_threshold
                    core_vitals[metric_info["id"]] = performance_metrics[metric_info["id"]]

        # 4. Performance opportunities and diagnostics
        opportunities = []
        diagnostics = []

        # Retrieve opportunities and diagnostics from audits
        for ref in performance_audit_refs:
            audit_id = ref.get("id")
            group = ref.get("group")

            # Skip already processed core metrics
            if audit_id in metrics_to_extract:
                continue

            audit = audits.get(audit_id)
            if not audit or audit.get("score") is None or audit.get("score") >= 0.9:
                continue

            # Determine impact level
            impact = self._determine_impact_level(audit.get("score", 0))

            # Create basic issue object - keep only necessary information
            issue = {"id": audit_id, "title": audit.get("title", ""), "impact": impact}

            # Add time savings information for load opportunities
            if group == "load-opportunities" and audit.get("details"):
                if audit.get("details").get("overallSavingsMs"):
                    issue["savings_ms"] = audit.get("details").get("overallSavingsMs")

                opportunities.append(issue)
            elif group != "load-opportunities" and audit.get("score") < 0.9:
                # Add diagnostic issues
                diagnostics.append(issue)

        # ====== SEO Analysis ======
        # 5. SEO audit analysis
        seo_issues = []
        seo_audit_refs = seo_category.get("auditRefs", [])

        for ref in seo_audit_refs:
            audit_id = ref.get("id")
            audit = audits.get(audit_id)

            if not audit:
                continue

            # Focus only on failed SEO audits
            if audit.get("score") is not None and audit.get("score") < 1.0:
                impact = self._determine_impact_level(audit.get("score", 0))

                seo_issue = {
                    "id": audit_id,
                    "title": audit.get("title", ""),
                    "description": audit.get("description", ""),
                    "impact": impact,
                    "score": audit.get("score"),
                }

                # Add specific SEO issue details
                if audit.get("details"):
                    seo_issue["details"] = self._extract_seo_issue_details(audit_id, audit.get("details"))

                seo_issues.append(seo_issue)

        # 6. Page statistics - extract only necessary statistics for generating recommendations
        page_stats = self._extract_minimal_page_stats(lhr)

        # 7. Generate prioritized recommendations (including performance and SEO)
        prioritized_recommendations = self._generate_recommendations(
            core_vitals, opportunities, diagnostics, page_stats, seo_issues, self.language
        )

        # 8. Summarize scores for each category
        category_scores = {
            "performance": performance_score,
            "accessibility": (
                round(accessibility_category.get("score", 0) * 100)
                if accessibility_category.get("score") is not None
                else 0
            ),
            "best_practices": (
                round(best_practices_category.get("score", 0) * 100)
                if best_practices_category.get("score") is not None
                else 0
            ),
            "seo": round(seo_category.get("score", 0) * 100) if seo_category.get("score") is not None else 0,
        }

        # 9.1 Four category scores
        score_str = "\n".join([f"- {k}: {v}" for k, v in category_scores.items()])
        simple_report = [{"title": self._get_text('overall_score'), "issues": score_str}]

        # 9.2 Prioritized recommendations / potential issues
        if prioritized_recommendations:
            simple_report.append(
                {"title": self._get_text('issues_to_improve'), "issues": "\n".join([f"- {rec}" for rec in prioritized_recommendations])}
            )

        # 9.3 Key performance metrics
        perf_metrics_str = "\n".join([f"- {m['name']}: {m['display_value']}" for m in performance_metrics.values()])
        simple_report.append({"title": self._get_text('performance_metrics'), "issues": perf_metrics_str})

        # 9.4 Return comprehensive results
        result = {
            "report": simple_report,
            "metrics": {
                "device": lhr.get("configSettings", {}).get("formFactor", "desktop"),
                "overall_scores": category_scores,
                "performance_metrics": performance_metrics,
                "prioritized_recommendations": prioritized_recommendations,
                "seo_issues": seo_issues,
            },
        }
        logging.debug(f"Lighthouse result: {result}")
        return result

    @staticmethod
    def _extract_minimal_page_stats(lhr):
        """Extract simplified page statistics, only used for generating
        recommendations."""
        audits = lhr.get("audits", {})
        minimal_stats = {"total_size_kb": 0, "total_requests": 0, "third_party_size_kb": 0}

        # Total byte weight
        total_byte_weight = audits.get("total-byte-weight", {})
        if total_byte_weight and total_byte_weight.get("numericValue"):
            minimal_stats["total_size_kb"] = round(total_byte_weight.get("numericValue") / 1024)

        # Network request statistics
        network_requests = audits.get("network-requests", {})
        if network_requests and network_requests.get("details"):
            items = network_requests.get("details").get("items", [])
            minimal_stats["total_requests"] = len(items)

        # Third-party resource statistics
        third_party = audits.get("third-party-summary", {})
        if third_party and third_party.get("details"):
            third_party_items = third_party.get("details").get("items", [])
            for item in third_party_items:
                if item.get("transferSize"):
                    minimal_stats["third_party_size_kb"] += round(item.get("transferSize") / 1024)

        return minimal_stats

    @staticmethod
    def _extract_seo_issue_details(audit_id, details):
        """Extract specific details of SEO issues."""
        extracted_details = {}

        # Extract relevant information based on different SEO audit types
        if audit_id == "document-title":
            # Page title issue
            extracted_details["issue_type"] = "Missing or poor document title"

        elif audit_id == "meta-description":
            # Meta description issue
            extracted_details["issue_type"] = "Missing or poor meta description"

        elif audit_id == "link-text":
            # Link text issue
            if details.get("items"):
                extracted_details["issue_type"] = "Poor link text"
                extracted_details["problematic_links"] = [
                    item.get("text", "") for item in details.get("items", [])[:5]
                ]  # 最多显示5个

        elif audit_id == "image-alt":
            # Image alt attribute issue
            if details.get("items"):
                extracted_details["issue_type"] = "Missing image alt attributes"
                extracted_details["images_count"] = len(details.get("items", []))

        elif audit_id == "hreflang":
            # Hreflang issue
            extracted_details["issue_type"] = "Hreflang issues"

        elif audit_id == "canonical":
            # Canonical tag issue
            extracted_details["issue_type"] = "Canonical link issues"

        elif audit_id == "robots-txt":
            # Robots.txt issue
            extracted_details["issue_type"] = "Robots.txt issues"

        elif audit_id == "structured-data":
            # Structured data issue
            extracted_details["issue_type"] = "Structured data issues"

        elif audit_id == "crawlable-anchors":
            # Crawlable anchor issue
            if details.get("items"):
                extracted_details["issue_type"] = "Non-crawlable links"
                extracted_details["links_count"] = len(details.get("items", []))

        # If there are general headings or items, also extract some basic information
        if details.get("headings") and details.get("items"):
            extracted_details["items_count"] = len(details.get("items", []))

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
            "lcp": 2500,  # 2.5 seconds in milliseconds
            "cls": 0.1,   # CLS score
            "tbt": 200,   # 200 milliseconds
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
            return "critical"
        elif score < 0.5:
            return "serious"
        elif score < 0.9:
            return "moderate"
        else:
            return "minor"

    def _generate_recommendations(self, core_vitals, opportunities, diagnostics, page_stats, seo_issues, language="zh-CN"):
        """Generate prioritized recommendations."""
        recommendations = []

        # 1. Core Web Vitals recommendations
        vitals_thresholds = {
            "lcp": {"threshold": 2500, "unit": "ms", "name": "Largest Contentful Paint"},
            "cls": {"threshold": 0.1, "unit": "", "name": "Cumulative Layout Shift"},
            "tbt": {"threshold": 200, "unit": "ms", "name": "Total Blocking Time"},
        }

        for vital_id, info in vitals_thresholds.items():
            if vital_id in core_vitals and not core_vitals[vital_id].get("passes_threshold"):
                recommendations.append(
                    f"{self._get_text('core_metrics')}: {self._get_text('improve')}{info['name']}（{self._get_text('current_value')}：{core_vitals[vital_id].get('display_value')}, {self._get_text('target')}：< {info['threshold']}{info['unit']}）"
                )

        # 2. Time-saving based opportunity recommendations (maximum 3)
        sorted_opportunities = sorted(opportunities, key=lambda x: -(x.get("savings_ms") or 0))
        for opportunity in sorted_opportunities[:3]:
            savings = ""
            if opportunity.get("savings_ms"):
                savings = f"（{self._get_text('potential_savings')}：{opportunity.get('savings_ms')}ms）"
            recommendations.append(f"{self._get_text('performance_optimization')}: {opportunity.get('title')}{savings}")

        # 3. Page statistics based recommendations
        if page_stats.get("total_size_kb", 0) > 3000:  # 超过3MB
            recommendations.append(f"{self._get_text('resource_optimization')}: {self._get_text('reduce_total_size')}（{self._get_text('current')}：{page_stats.get('total_size_kb') / 1024:.1f}MB）")

        if page_stats.get("third_party_size_kb", 0) > 500:  # 第三方资源超过500KB
            recommendations.append(
                f"{self._get_text('resource_optimization')}: {self._get_text('optimize_third_party')}（{self._get_text('current')}：{page_stats.get('third_party_size_kb') / 1024:.1f}MB）"
            )

        # 4. Diagnostic issue recommendations (maximum 2 critical issues)
        critical_diagnostics = [d for d in diagnostics if d.get("impact") == "critical"]
        for diagnostic in critical_diagnostics:
            recommendations.append(f"{self._get_text('performance_diagnosis')}: {diagnostic.get('title')}")

        # 5. SEO issue recommendations (sorted by impact level)
        seo_issues_sorted = sorted(
            seo_issues,
            key=lambda x: {"critical": 4, "serious": 3, "moderate": 2, "minor": 1}.get(x.get("impact"), 0),
            reverse=True,
        )

        for seo_issue in seo_issues_sorted[:5]:  # 最多显示5个SEO问题
            recommendation = f"{self._get_text('seo')}: {seo_issue.get('title')}"

            # 添加具体的详情信息（如果有的话）
            details = seo_issue.get("details", {})
            if details.get("images_count"):
                recommendation += f" ({details['images_count']} {self._get_text('images')})"
            elif details.get("links_count"):
                recommendation += f" ({details['links_count']} {self._get_text('links')})"
            elif details.get("problematic_links"):
                recommendation += f" ({self._get_text('example')}: {', '.join(details['problematic_links'][:2])})"

            recommendations.append(recommendation)

        return recommendations

