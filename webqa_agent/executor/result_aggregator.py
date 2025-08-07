import json
import logging
import os
from typing import Any, Dict, List, Optional

from webqa_agent.data import ParallelTestSession, TestStatus
from webqa_agent.llm.llm_api import LLMAPI


class ResultAggregator:
    """Aggregates and analyzes parallel test results"""
    
    async def aggregate_results(self, test_session: ParallelTestSession) -> Dict[str, Any]:
        """Aggregate all test results into a comprehensive summary.

        Args:
            test_session: Session containing all test results

        Returns:
            Aggregated results dictionary
        """
        logging.info(f"Aggregating results for session: {test_session.session_id}")
        issues = []
        error_message = await self._get_error_message(test_session)
        # Generate issue list (LLM powered when possible)
        llm_issues = await self._generate_llm_issues(test_session)
        
        issues.extend(error_message)
        issues.extend(llm_issues)
        logging.debug(f"Found {len(test_session.test_results)} test results")
        for test_id, result in test_session.test_results.items():
            sub_tests_count = len(result.sub_tests or [])
            logging.debug(f"Test {test_id} has {sub_tests_count} sub_tests")
            if result.sub_tests:
                for i, sub_test in enumerate(result.sub_tests):
                    logging.debug(f"Sub-test {i}: status={sub_test.status}")
        
        total_sub_tests = sum(len(r.sub_tests or []) for r in test_session.test_results.values())
        passed_sub_tests = sum(
            1
            for r in test_session.test_results.values()
            for sub in (r.sub_tests or [])
            if sub.status == TestStatus.PASSED
        )
        critical_sub_tests = total_sub_tests - passed_sub_tests  # 未通过即视为关键问题
        
        logging.info(f"Debug: total_sub_tests={total_sub_tests}, passed_sub_tests={passed_sub_tests}, critical_sub_tests={critical_sub_tests}")

        # Build content for executive summary tab
        executive_content = {
            "executiveSummary": "",
            "statistics": [
                {"label": "评估子测试总数", "value": str(total_sub_tests), "colorClass": "var(--warning-color)"},
                {"label": "测试通过", "value": str(passed_sub_tests), "colorClass": "var(--success-color)"},
                {"label": "测试失败", "value": str(critical_sub_tests), "colorClass": "var(--failure-color)"},
            ]
        }

        aggregated_results_list = [
            {"id": "subtab-summary-advice", "title": "摘要与建议", "content": executive_content},
            {
                "id": "subtab-issue-tracker",
                "title": "问题列表",
                "content": {
                    "title": "问题追踪列表",
                    "note": "注：此列表汇总了所有检测到的“失败”和“警告”项",
                    "issues": issues,
                },
            },
        ]

        # Store additional raw analysis for LLM etc.
        raw_analysis = {
            "session_summary": test_session.get_summary_stats(),
        }

        def dict_to_text(d, indent=0):
            lines = []
            for k, v in d.items():
                if isinstance(v, dict):
                    lines.append(" " * indent + f"{k}:")
                    lines.append(dict_to_text(v, indent + 2))
                else:
                    lines.append(" " * indent + f"{k}: {v}")
            return "\n".join(lines)

        executive_content["executiveSummary"] = f"{dict_to_text(raw_analysis['session_summary'])}"

        return {"title": "评估总览", "tabs": aggregated_results_list}

    async def _generate_llm_issues(self, test_session: ParallelTestSession) -> List[Dict[str, Any]]:
        """Use LLM to summarise issues for each sub-test.

        Fallback to heuristic if LLM unavailable.
        """
        llm_config = test_session.llm_config or {}
        use_llm = bool(llm_config)
        critical_issues: List[Dict[str, Any]] = []

        # Prepare LLM client if configured
        llm: Optional[LLMAPI] = None
        if use_llm:
            try:
                llm = LLMAPI(llm_config)
                await llm.initialize()
            except Exception as e:
                logging.error(f"Failed to initialise LLM, falling back to heuristic issue extraction: {e}")
                use_llm = False

        logging.info(f"LLM 总结测试结果中...")
        # Iterate over all tests and their sub-tests
        for test_result in test_session.test_results.values():
            for sub in test_result.sub_tests or []:
                try:
                    # Determine severity strictly based on sub-test status
                    if sub.status == TestStatus.PASSED:
                        continue  # No issue for passed sub-tests
                    if sub.status == TestStatus.WARNING:
                        severity_level = "low"
                    elif sub.status == TestStatus.FAILED:
                        severity_level = "high"
                    else:
                        severity_level = "medium"

                    issue_entry = {
                        "issue_name": "测试不通过: "+test_result.test_name, 
                        "issue_type": test_result.test_type.value,
                        "sub_test_name": sub.name,
                        "severity": severity_level,
                    }
                    if use_llm and llm:
                        prompt_content = {
                            "name": sub.name,
                            "status": sub.status,
                            "report": sub.report,
                            "metrics": sub.metrics,
                            "final_summary": sub.final_summary,
                        }
                        prompt = (
                            "你是一名经验丰富的软件测试分析师。请阅读以下子测试信息，提取【问题内容】、【问题数量】和【严重程度】：\n"
                            "1）如果 status = pass，请返回 JSON {\"issue_count\": 0}。\n"
                            "2）如果 status != pass，则根据 report、metrics 或 final_summary 的具体内容判断：\n"
                            "   - 提取最关键的一句话问题描述 issues\n"
                            "   - 统计问题数量 issue_count（如果无法准确统计，可默认为 1）\n"
                            "   - 严重程度判断：优先查看 report 中是否已标明严重程度（如 high/medium/low、严重/中等/轻微、critical/major/minor 等），如果有则直接遵循；如果 report 中没有明确标明，则根据问题影响程度自行判断：high（严重影响功能/性能）、medium（中等影响）、low（轻微问题/警告）\n"
                            "3）你不能输出任何其他内容，也不能输出代码块，只能输出统一为 JSON：{\"issue_count\": <数字>, \"issues\": \"一句话中文问题描述\", \"severity\": \"high|medium|low\"}。\n"
                            f"子测试信息: {json.dumps(prompt_content, ensure_ascii=False, default=str)}"
                        )
                        logging.debug(f"LLM Issue Prompt: {prompt}")
                        llm_response_raw = await llm.get_llm_response("", prompt)
                        llm_response = llm._clean_response(llm_response_raw)
                        logging.debug(f"LLM Issue Response: {llm_response}")
                        try:
                            parsed = json.loads(llm_response)
                            issue_count = parsed.get("issue_count", parsed.get("count", 1))
                            if issue_count == 0:
                                continue
                            issue_text = parsed.get("issues", "").strip()
                            if not issue_text:
                                continue
                            llm_severity = parsed.get("severity", severity_level)
                            issue_entry["severity"] = llm_severity
                            issue_entry["issues"] = issue_text
                            issue_entry["issue_count"] = issue_count
                        except Exception as parse_err:
                            logging.error(f"Failed to parse LLM JSON: {parse_err}; raw: {llm_response}")
                            continue  # skip if cannot parse
                    else:
                        # Heuristic fallback – use final_summary to detect issue presence
                        summary_text = (sub.final_summary or "").strip()
                        if not summary_text:
                            continue
                        lowered = summary_text.lower()
                        if any(k in lowered for k in ["error", "fail", "严重", "错误", "崩溃", "无法"]):
                            issue_entry["severity"] = "high"
                        elif any(k in lowered for k in ["warning", "警告", "建议", "优化", "改进"]):
                            issue_entry["severity"] = "low"
                        else:
                            issue_entry["severity"] = "medium"
                        issue_entry["issues"] = summary_text
                        issue_entry["issue_count"] = 1
                    # add populated entry
                    critical_issues.append(issue_entry)
                except Exception as e:
                    logging.error(f"Error while generating issue summary for sub-test {sub.name}: {e}")
                    continue  # skip problematic sub-test
        # Close LLM client if needed
        if use_llm and llm:
            try:
                await llm.close()
            except Exception as e:
                logging.warning(f"Failed to close LLM client: {e}")
        return critical_issues

    async def generate_llm_summary(self, aggregated_results: Dict[str, Any], llm_config: Dict[str, Any]) -> str:
        """Generate LLM-powered summary and analysis."""
        try:
            llm = LLMAPI(llm_config)

            # Create comprehensive prompt
            prompt = self._create_analysis_prompt(aggregated_results)

            # Get LLM analysis
            await llm.initialize()  # 确保LLM已初始化
            summary = await llm.get_llm_response("", prompt)

            return summary

        except Exception as e:
            logging.error(f"Failed to generate LLM summary: {e}")
            return f"LLM summary generation failed: {str(e)}"

    def _create_analysis_prompt(self, aggregated_results: Dict[str, Any]) -> str:
        """Create analysis prompt for LLM."""
        prompt = f"""
        请基于以下并行测试结果进行综合分析，生成专业的测试报告总结：

        ## 测试会话概览
        {json.dumps(aggregated_results.get('session_summary', {}), indent=2, ensure_ascii=False)}

        ## 整体指标
        {json.dumps(aggregated_results.get('overall_metrics', {}), indent=2, ensure_ascii=False)}

        ## 性能分析
        {json.dumps(aggregated_results.get('lighthouse_summary', {}), indent=2, ensure_ascii=False)}

        ## 用户体验分析
        {json.dumps(aggregated_results.get('ux_analysis', {}), indent=2, ensure_ascii=False)}

        ## 技术健康度
        {json.dumps(aggregated_results.get('technical_health', {}), indent=2, ensure_ascii=False)}

        ## 功能分析
        {json.dumps(aggregated_results.get('ui_functionality', {}), indent=2, ensure_ascii=False)}

        ## 关键问题
        {json.dumps(aggregated_results.get('critical_issues', []), indent=2, ensure_ascii=False)}

        请提供：
        1. 执行总结
        2. 关键发现
        3. 风险评估
        4. 改进建议
        5. 下一步行动计划

        要求：
        - 使用专业且易懂的语言
        - 突出重要问题和成功亮点
        - 提供具体可行的建议
        - 包含风险等级评估
        """
        logging.debug(f"Analysis Prompt: {prompt}")

        return prompt

    async def _get_error_message(self, test_session: ParallelTestSession) -> str:
        """Get error message from test session."""
        error_message = []
        for test_result in test_session.test_results.values():
            if test_result.status != TestStatus.PASSED:
                # Only append if error_message is not empty
                if test_result.error_message:
                    error_message.append({
                        "issue_name": "执行异常: "+test_result.test_name,
                        "issue_type": test_result.test_type.value,
                        "severity": "high",
                        "issues": test_result.error_message
                    })
        return error_message

    async def generate_json_report(self, test_session: ParallelTestSession, report_dir: str | None = None) -> str:
        """Generate comprehensive JSON report."""
        try:
            # Determine report directory
            if report_dir is None:
                timestamp = os.getenv("WEBQA_TIMESTAMP")
                report_dir = f"./reports/test_{timestamp}"
            os.makedirs(report_dir, exist_ok=True)

            json_path = os.path.join(report_dir, "test_results.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(test_session.to_dict(), f, indent=2, ensure_ascii=False, default=str)

            absolute_path = os.path.abspath(json_path)
            if os.getenv("DOCKER_ENV"):
                host_path = absolute_path.replace("/app/reports", "./reports")
                logging.debug(f"JSON report generated: {host_path}")
                return host_path
            else:
                logging.debug(f"JSON report generated: {absolute_path}")
                return absolute_path

        except Exception as e:
            logging.error(f"Failed to generate JSON report: {e}")
            return ""

    def _read_css_content(self) -> str:
        """Read and return CSS content."""
        try:
            css_path = os.path.join(os.path.dirname(__file__), "../static/assets/style.css")
            if os.path.exists(css_path):
                with open(css_path, "r", encoding="utf-8") as f:
                    return f.read()
        except Exception as e:
            logging.warning(f"Failed to read CSS file: {e}")
        return ""

    def _read_js_content(self) -> str:
        """Read and return JavaScript content."""
        try:
            js_path = os.path.join(os.path.dirname(__file__), "../static/assets/index.js")
            if os.path.exists(js_path):
                with open(js_path, "r", encoding="utf-8") as f:
                    return f.read()
        except Exception as e:
            logging.warning(f"Failed to read JS file: {e}")
        return ""

    def generate_html_report_fully_inlined(self, test_session, report_dir: str | None = None, template_path: str = None) -> str:
        """Generate a fully inlined HTML report for the test session."""
        import re
        import json
        import re

        try:
            if template_path is None:
                template_path = os.path.join(os.path.dirname(__file__), "../static/index.html")
            with open(template_path, "r", encoding="utf-8") as f:
                html_template = f.read()

            css_content = self._read_css_content()
            js_content = self._read_js_content()
            datajs_content = (
                "window.testResultData = " + json.dumps(test_session.to_dict(), ensure_ascii=False, default=str) + ";"
            )

            html_out = html_template
            html_out = re.sub(
                r'<link\s+rel="stylesheet"\s+href="/assets/style.css"\s*>',
                lambda m: f"<style>\n{css_content}\n</style>",
                html_out,
            )
            html_out = re.sub(
                r'<script\s+src="/data.js"\s*>\s*</script>',
                lambda m: f"<script>\n{datajs_content}\n</script>",
                html_out,
            )
            html_out = re.sub(
                r'<script\s+type="module"\s+crossorigin\s+src="/assets/index.js"\s*>\s*</script>',
                lambda m: f'<script type="module">\n{js_content}\n</script>',
                html_out,
            )

            if report_dir is None:
                timestamp = os.getenv("WEBQA_TIMESTAMP")
                report_dir = f"./reports/test_{timestamp}"
            os.makedirs(report_dir, exist_ok=True)
            html_path = os.path.join(report_dir, "test_report.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_out)
            absolute_path = os.path.abspath(html_path)
            if os.getenv("DOCKER_ENV"):
                host_path = absolute_path.replace("/app/reports", "./reports")
                logging.debug(f"HTML report generated: {host_path}")
                return host_path
            else:
                logging.debug(f"HTML report generated: {absolute_path}")
                return absolute_path
        except Exception as e:
            logging.error(f"Failed to generate fully inlined HTML report: {e}")
            return ""
