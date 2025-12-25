import json
import logging
import base64
from io import BytesIO
from typing import Any, List

from langchain_core.tools import BaseTool
from pydantic import Field

from webqa_agent.crawler.deep_crawler import DeepCrawler
from webqa_agent.llm.prompt import LLMPrompt
from webqa_agent.llm.llm_api import LLMAPI
from webqa_agent.data.test_structures import TestStatus
from webqa_agent.testers.case_gen.utils.case_recorder import CentralCaseRecorder
from PIL import Image, ImageDraw

class UIUXViewportTool(BaseTool):
    """UX Verify tool to verify visual quality and content accuracy of the page."""

    name: str = "execute_ux_verify"
    description: str = (
        "Performs two UX checks in the current viewport: (1) Typo/grammar/text accuracy using page text; "
        "(2) Layout/visual rendering using screenshot + viewport structure. Returns both analyses."
    )
    ui_tester_instance: Any = Field(..., description="UITester instance to access driver and page")
    llm_config: dict | None = Field(default=None, description="LLM configuration for independent client")
    case_recorder: Any | None = Field(default=None, description="Optional CentralCaseRecorder to record ux_verify step")

    def _run(self, assertion: str) -> str:
        raise NotImplementedError("Use arun for asynchronous execution.")

    def _annotate_b64_image(self, image_b64: str, rect: List[int]) -> str:
        """Annotate a base64 encoded image with a rectangle"""
        try:
            header, b64 = image_b64.split(',', 1)
            img_bytes = base64.b64decode(b64)
            with Image.open(BytesIO(img_bytes)) as im:
                # Ensure RGB to draw colored lines
                if im.mode not in ('RGB', 'RGBA'):
                    im = im.convert('RGB')
                draw = ImageDraw.Draw(im)
                x1, y1, x2, y2 = rect
                # draw rectangle with width 3 in red
                for w in range(2):
                    draw.rectangle([x1 - w, y1 - w, x2 + w, y2 + w], outline=(255, 0, 0))
                out = BytesIO()
                im.save(out, format='PNG')
                new_b64 = base64.b64encode(out.getvalue()).decode('utf-8')
                return f'data:image/png;base64,{new_b64}'
        except Exception as e:
            logging.warning(f'Failed to annotate image: {e}')
            return image_b64

    async def _arun(self, assertion: str) -> str:
        if not self.ui_tester_instance:
            return "[FAILURE] Error: UITester instance not provided for UX collection."

        try:
            logging.debug(f"Executing UX verification: {assertion}")

            # Dynamically get current page from browser session
            page = self.ui_tester_instance.browser_session.page

            dp = DeepCrawler(page)
            # Crawl for interactive elements with layout info (for layout check)
            crawl_result = await dp.crawl(highlight=False, filter_text=False, viewport_only=False, include_styles=True)
            id_map = crawl_result.raw_dict()
            
            # Get full page text directly from page for text/typo check (more comprehensive)
            viewport_structure = await page.evaluate("""
                () => {
                    // Extract all visible text from the page
                    const textElements = [];
                    const walker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_TEXT,
                        {
                            acceptNode: function(node) {
                                const parent = node.parentElement;
                                if (!parent) return NodeFilter.FILTER_REJECT;
                                
                                // Skip script, style, and hidden elements
                                const style = window.getComputedStyle(parent);
                                if (style.display === 'none' || 
                                    style.visibility === 'hidden' || 
                                    parent.tagName === 'SCRIPT' || 
                                    parent.tagName === 'STYLE') {
                                    return NodeFilter.FILTER_REJECT;
                                }
                                
                                const text = node.textContent.trim();
                                return text.length > 0 ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
                            }
                        }
                    );
                    
                    let node;
                    while (node = walker.nextNode()) {
                        const text = node.textContent.trim();
                        if (text && text.length > 0) {
                            textElements.push(text);
                        }
                    }
                    
                    // Deduplicate and return as JSON
                    return JSON.stringify([...new Set(textElements)]);
                }
            """)
            logging.debug(f"Viewport Text Structure: {viewport_structure}")

            screenshot = None
            img_bytes = await page.screenshot(full_page=True)
            screenshot = f"data:image/png;base64,{base64.b64encode(img_bytes).decode('utf-8')}"

            try:
                parsed_structure = json.loads(viewport_structure)
            except Exception:
                parsed_structure = viewport_structure  # fallback as-is

            await dp.remove_marker()

            # Build stringified viewport structure (token-controlled)
            structure_str = viewport_structure
            if isinstance(parsed_structure, (dict, list)):
                try:
                    structure_str = json.dumps(parsed_structure, ensure_ascii=False, separators=(",", ":"))
                except Exception:
                    pass
            # Truncate long structure to control token size
            if structure_str and len(structure_str) > 10000:
                structure_str = structure_str[:10000] + "..."

            # Prepare two user cases: text typo check and layout check
            text_user_case = LLMPrompt.TEXT_USER_CASES[0]
            layout_user_case = LLMPrompt.CONTENT_USER_CASES[0]

            # Initialize an independent LLM client (do not use UITester.llm API directly)
            resolved_llm_config = self.llm_config
            if not resolved_llm_config:
                return "[FAILURE] LLM config is missing. Provide llm_config to the tool."

            llm_client = LLMAPI(resolved_llm_config)
            await llm_client.initialize()

            text_prompt = (
                "Task description: Based on the provided web page content and user cases, check for any typos or English grammar errors. "
                "If errors are found, output the results in the specified JSON format.\n"
                "Input information:\n"
                f"- Web content: ${structure_str}\n"
                f"- User case: ${text_user_case}\n"
                "Output requirements:\n"
                "- If no errors are found, output only None, do not include any explanations.\n"
                "- If errors are found, please output in the following JSON format:\n"
                "{\n"
                "    \"error\": [\n"
                "        {\n"
                "            \"location\": \"Description of error location\",\n"
                "            \"current\": \"Current erroneous content\",\n"
                "            \"suggested\": \"Suggested modification\",\n"
                "            \"type\": \"Error type\"\n"
                "        }\n"
                "    ],\n"
                "    \"summary\": \"Summary of the issues found, errors and suggestions\"\n"
                "}\n"
                "Rules:\n"
                "- Do not invent or guess issues. Report only errors that are present verbatim in the provided Web content.\n"
                "- The \\\"current\\\" field must copy the exact erroneous text snippet from the Web content.\n"
                "- If the text cannot be located exactly in the Web content or you are uncertain, output only None.\n"
                "- Do not infer intent or style; judge strictly on spelling and grammar within the provided content only.\n"
                "- Conciseness: Keep each error description concise and direct, avoid explanations.\n"
            )

            # logging.debug(f"UX text typo analysis prompt: {text_prompt}")

            typo_response = await llm_client.get_llm_response(
                LLMPrompt.page_default_prompt,
                text_prompt,
            )
            logging.debug(f"UX text typo analysis response: {typo_response}")

            # Parse typo response when possible
            parsed_typo = None
            try:
                if isinstance(typo_response, str) and typo_response.strip().lower() != "none":
                    parsed_typo = json.loads(typo_response)
            except Exception:
                parsed_typo = typo_response  # keep raw if not JSON

            # 2) Layout/visual analysis (screenshot + structure)
            layout_prompt = self._build_layout_prompt(layout_user_case, id_map, len(screenshot))

            # logging.debug(f"UX layout analysis prompt: {layout_prompt}")

            images = [screenshot] if isinstance(screenshot, str) else None
            layout_response = await llm_client.get_llm_response(
                LLMPrompt.page_default_prompt,
                layout_prompt,
                images=images,
            )

            parsed_layout = None
            try:
                parsed_layout = json.loads(layout_response) if isinstance(layout_response, str) else layout_response
            except Exception:
                parsed_layout = layout_response  # keep raw if not JSON

            result_payload = {
                "screenshot_included": bool(images),
                "viewport_structure": parsed_structure,
                "typo_analysis": parsed_typo if parsed_typo is not None else (typo_response or None),
                "layout_analysis": parsed_layout if parsed_layout is not None else (layout_response or None),
            }
            compact = json.dumps(result_payload, ensure_ascii=False, separators=(",", ":"))

            # Optionally record this as a ux_verify step into a central recorder if present
            recorder: CentralCaseRecorder | None = self.case_recorder
            if recorder:
                all_issues_summary = []
                # Track issues by category to avoid overwriting flags
                text_has_issues = False
                layout_has_issues = False
                layout_issues_summary = None
                
                # Process typo/text issues
                logging.debug(f"UX Tool: Processing typo/text issues: {parsed_typo}")
                typo_summary_parts = []
                if isinstance(parsed_typo, dict) and parsed_typo.get("error"):
                    errors = parsed_typo.get("error", [])
                    text_has_issues = True
                    
                    for idx, error in enumerate(errors, 1):
                        if isinstance(error, dict):
                            location = error.get("location", "Unknown location")
                            current = error.get("current", "")
                            suggested = error.get("suggested", "")
                            error_type = error.get("type", "Unknown type")
                            
                            typo_summary_parts.append(
                                f"{idx}. [{error_type}] at {location}\n"
                                f"   Current: '{current}'\n"
                                f"   Suggested: '{suggested}'"
                            )
                    
                    if typo_summary_parts:
                        all_issues_summary.append("**Text/Typo Issues:**\n" + "\n".join(typo_summary_parts))
                        logging.debug(f"UX Tool: Collected {len(typo_summary_parts)} text errors")
                
                # Process layout issues with coordinates
                layout_issues = []
                # Check if it's the "no issues" format
                if isinstance(parsed_layout, dict) and parsed_layout.get('status') == 'no_issues':
                    # No issues found - this is the expected case
                    layout_has_issues = False
                    layout_issues_summary = "No layout issues detected"
                    logging.debug(f"UX Tool: LLM confirmed no layout issues found: {parsed_layout.get('message', 'No layout issues detected')}")

                # Check if it's the "issues found" format (array)
                elif isinstance(parsed_layout, list) and len(parsed_layout) > 0:
                    # Issues found - process the array
                    layout_has_issues = True

                    for item in parsed_layout:
                        if isinstance(item, dict):
                            if 'summary' in item:
                                layout_issues_summary = item.get('summary')
                                logging.debug(f'UX Tool: Found layout issues summary: {layout_issues_summary}')
                            elif any(key in item for key in ['issue', 'screenshotid', 'coordinates']):
                                # This is an issue object
                                layout_issues.append(item)
                                logging.debug(f"UX Tool: Added layout issue to list: {item.get('issue', 'No issue description')}")
                            else:
                                logging.debug(f'UX Tool: Skipping item without issue fields: {item}')

                # Check if it's the "issues found" format (object fallback)
                elif isinstance(parsed_layout, dict):
                    layout_issues_summary = parsed_layout.get('summary')
                    issues_candidate = {k: v for k, v in parsed_layout.items() if k != 'summary'}
                    if issues_candidate:
                        layout_has_issues = True
                        layout_issues.append(issues_candidate)
                        
                # Collect all coordinates for annotation
                all_coords = []
                layout_summary_parts = []
                
                for idx, issue in enumerate(layout_issues, 1):
                    if not isinstance(issue, dict):
                        continue
                    
                    layout_has_issues = True
                    issue_desc = issue.get('issue') or issue.get('description') or f"Layout Issue {idx}"
                    suggestion = issue.get('suggestion', '')
                    coords = None
                    
                    # Process coordinates
                    if isinstance(issue, dict) and 'coordinates' in issue:
                        c = issue.get('coordinates')
                        if isinstance(c, (list, tuple)) and len(c) == 4:
                            try:
                                x1, y1, x2, y2 = [int(float(v)) for v in c]
                                # ensure ordering and non-negative
                                x1, x2 = sorted([max(0, x1), max(0, x2)])
                                y1, y2 = sorted([max(0, y1), max(0, y2)])
                                if y1 == y2:
                                    y2 = y1 + 5
                                coords = [x1, y1, x2, y2]
                                all_coords.append(coords)
                                logging.debug(f'Layout issue {idx} - Processed coordinates: {coords}')
                            except Exception as e:
                                logging.warning(f'Layout issue {idx} - Failed to process coordinates {c}: {e}')
                    
                    # Build summary
                    issue_text = f"{idx}. {issue_desc}"
                    if suggestion:
                        issue_text += f"\n   Suggestion: {suggestion}"
                    layout_summary_parts.append(issue_text)
                
                # # If we have a high-level layout summary, include it
                # if layout_issues_summary:
                #     all_issues_summary.append("**Layout Overview:**\n" + str(layout_issues_summary))

                if layout_summary_parts:
                    all_issues_summary.append("**Layout Issues:**\n" + "\n".join(layout_summary_parts))
                
                logging.debug(f"UX Tool: Found {len(layout_issues)} layout issues to process")
                
                # Create annotated screenshot with all coordinates
                step_screenshots = []
                if all_coords:
                    # Annotate all coordinates on a single screenshot
                    annotated_screenshot = screenshot
                    for coords in all_coords:
                        annotated_screenshot = self._annotate_b64_image(annotated_screenshot, coords)
                        logging.debug(f'Annotated screenshot with coordinates: {coords}')
                    
                    step_screenshots.append({"type": "base64", "data": annotated_screenshot})
                    step_screenshots.append({"type": "base64", "data": screenshot})
                else:
                    step_screenshots.append({"type": "base64", "data": screenshot})
                
                # Determine overall status and summary
                has_issues = bool(text_has_issues or layout_has_issues)
                if has_issues:
                    combined_status = TestStatus.WARNING
                    combined_summary = "\n\n".join(all_issues_summary) if all_issues_summary else "UX issues detected (see details in analysis)"
                else:
                    combined_status = TestStatus.PASSED
                    combined_summary = "No UX issues detected."
                
                # Record a single step with all issues
                recorder.add_step(
                    description=f"ux_verify: {assertion}",
                    screenshots=step_screenshots,
                    model_io=combined_summary,
                    actions=[],
                    status=combined_status,
                )
                logging.debug(f"Recorded single UX verify step with {len(typo_summary_parts)} text errors and {len(layout_issues)} layout issues")

            # Return with warning indicator if issues were found
            if has_issues:
                return f"[WARNING] UX viewport analysis completed with issues.\n\nUX_VIEWPORT_RESULT: {compact}"
            else:
                return f"[SUCCESS] UX viewport analysis completed.\n\nUX_VIEWPORT_RESULT: {compact}"

        except Exception as e:
            logging.error(f"Error collecting UX viewport context: {str(e)}")
            return f"[FAILURE] Unexpected error during UX collection: {str(e)}"

    def _build_layout_prompt(self, user_case: str, id_map: dict, screenshot_count: int = 0) -> str:
        structured_info = ''

        if id_map:
            key_elements = []

            for element_id, info in id_map.items():
                if not isinstance(info, dict):
                    continue

                tag = info.get('tagName', '')
                text = (info.get('innerText', '') or '').strip()[:50]
                styles = info.get('styles', {}) or {}
                viewport = info.get('viewport', {})

                # 提取关键布局属性
                key_styles = {}
                layout_signals = {}

                if styles:
                    layout_props = [
                        'position', 'zIndex', 'overflow', 'overflowX', 'overflowY',
                        'textOverflow', 'whiteSpace', 'margin', 'padding',
                        'width', 'height', 'maxWidth', 'maxHeight', 'minWidth', 'minHeight',
                        'display', 'textAlign', 'verticalAlign', 'lineHeight'
                    ]

                    for prop in layout_props:
                        if prop in styles and styles[prop] and styles[prop] not in ['auto', 'none', '']:
                            key_styles[prop] = styles[prop]

                    # 布局信号
                    if (styles.get('overflow') == 'hidden' or styles.get('overflowX') == 'hidden' or
                        styles.get('overflowY') == 'hidden' or styles.get('textOverflow') == 'ellipsis'):
                        layout_signals['potential_overflow'] = True

                    if 'absolute' in styles.get('position', '') or 'fixed' in styles.get('position', ''):
                        layout_signals['positioned'] = True

                    if styles.get('whiteSpace') == 'nowrap':
                        layout_signals['no_wrap'] = True

                    border_value = styles.get('border', '')
                    if (border_value and border_value != '0px solid rgb(255, 255, 255)' and
                        'solid' in border_value and not border_value.startswith('0px')):
                        layout_signals['has_border'] = True
                        if tag in ['input', 'button', 'textarea']:
                            layout_signals['container_risk'] = True

                # 坐标信息
                coords = {
                    'x': viewport.get('x', 0),
                    'y': viewport.get('y', 0),
                    'width': viewport.get('width', 0),
                    'height': viewport.get('height', 0),
                    'x2': viewport.get('x', 0) + viewport.get('width', 0),
                    'y2': viewport.get('y', 0) + viewport.get('height', 0),

                }

                element_info = {
                    'id': element_id,
                    'tag': tag,
                    'text': text,
                    'position': f"({coords['x']:.0f}, {coords['y']:.0f})",
                    'size': f"{coords['width']:.0f}×{coords['height']:.0f}",
                    'coords': coords,
                    'styles': key_styles,
                    'signals': layout_signals
                }

                if tag == 'img':
                    element_info['src'] = info.get('src')
                    element_info['alt'] = info.get('alt')

                if text or key_styles or tag in ['img', 'svg', 'button', 'input', 'select']:
                    key_elements.append(element_info)

            total_elements = len(key_elements)
            logging.debug(f'UX test page total interactive elements: {total_elements}')
            interactive_count = len([e for e in key_elements if e['tag'] in ['button', 'input', 'select', 'a']])
            image_count = len([e for e in key_elements if e['tag'] in ['img', 'svg']])

            structured_info = f'DOM Summary: {total_elements} elements ({interactive_count} interactive, {image_count} images)'

            if key_elements:
                # Handle elements with layout properties
                elements_with_signals = [e for e in key_elements if e.get('signals')]
                # Handle regular elements without layout signals
                regular_elements = [e for e in key_elements if not e.get('signals')]

                # relevant_elements = (elements_with_signals[:15] + regular_elements[:5])[:20]
                relevant_elements = elements_with_signals + regular_elements

                structured_info += '\nKey Elements:'
                for elem in relevant_elements:
                    coords = elem['coords']
                    element_desc = (
                        f"\n- {elem['tag']}[{elem['size']}] "
                        f"(coords: {coords['x']:.0f},{coords['y']:.0f} → {coords['x2']:.0f},{coords['y2']:.0f})"
                    )

                    if elem['text']:
                        element_desc += f" text: \"{elem['text'][:30]}{'...' if len(elem['text']) > 30 else ''}\""

                    critical_styles = {}
                    for prop in ['overflow', 'textOverflow', 'whiteSpace', 'position', 'border']:
                        if prop in elem['styles']:
                            critical_styles[prop] = elem['styles'][prop]
                    if critical_styles:
                        style_str = '; '.join([f'{k}:{v}' for k, v in critical_styles.items()])
                        element_desc += f' {{{style_str}}}'

                    if elem.get('signals'):
                        signals = []
                        if elem['signals'].get('potential_overflow'):
                            signals.append('MAY_OVERFLOW')
                        if elem['signals'].get('positioned'):
                            signals.append('POSITIONED')
                        if elem['signals'].get('no_wrap'):
                            signals.append('NO_WRAP')
                        if elem['signals'].get('has_border'):
                            signals.append('BORDERED')
                        if elem['signals'].get('container_risk'):
                            signals.append('CONTAINER_RISK')
                        if signals:
                            element_desc += f" [⚠️ {','.join(signals)}]"

                    structured_info += element_desc

            logging.debug(f'structured_info (layout check): {structured_info}')


            return f"""## Layout Analysis Task
                **Input**: {screenshot_count} screenshots (index 0-{screenshot_count-1}) + DOM context with layout signals

                **DOM Reference**: {structured_info}

                **Objective**: {user_case}

                ### Analysis Strategy
                **Primary Method**: Visual analysis of screenshots to identify layout issues
                **Supporting Context**: Use DOM information and layout signals as hints for potential problem areas

                **Layout Signal Meanings**:
                - **MAY_OVERFLOW**: Element has overflow:hidden or text-overflow:ellipsis → check for content clipping
                - **POSITIONED**: Element uses absolute/fixed positioning → check for overlaps or misalignment
                - **NO_WRAP**: Element has white-space:nowrap → check for text extending beyond containers
                - **BORDERED**: Element has visible border → check if content extends outside border boundaries
                - **CONTAINER_RISK**: Bordered input/button element → high risk of text/icon overflow issues

                **Focus Areas**:
                1. **Occlusion**: Elements overlapping, text/buttons hidden behind other elements
                2. **Crowding**: Elements too close together, insufficient spacing
                3. **Text Truncation**: Content cut off, ellipsis (...), text overflow beyond container boundaries
                4. **Alignment**: Misaligned elements, inconsistent positioning
                5. **Container Overflow**: Text or icons extending outside their intended boundaries
                6. **Images**: Broken images, placeholders, loading failures, distorted aspect ratios

                ### Output Requirements
                {LLMPrompt.OUTPUT_FORMAT}

                **Rules**:
                - Use **visual evidence** as primary source, DOM signals as supporting hints
                - For BORDERED and CONTAINER_RISK elements, Use **visual evidence** to carefully examine if text/icons extend beyond the visible border boundaries
                - For any element marked with MAY_OVERFLOW or NO_WRAP in DOM signals, compare the full DOM text content with the visible text in screenshot; if mismatch or truncation occurs (e.g., missing letters, words cut off), mark as overflow.
                - Look for content that appears to "break out" or "overflow" from boxes, buttons, input fields
                - Check if text is cut off at container edges or if icons appear partially outside their containers
                - Do not report issues based solely on DOM signals without clear, visible evidence in the screenshot
                - Each reported issue must include a brief evidence note referencing the visible cue (e.g., ellipsis visible, text clipped at right edge)
                - If evidence is ambiguous or coordinates cannot be determined reliably, do not report the issue; output None instead
                - Forbidden: speculating about off-screen elements, claiming overlap without visible occlusion, or asserting overflow without visible truncation/clipping
                - Conciseness: Keep each issue description concise and direct, avoid explanations.
                - Output one JSON object per distinct issue
                - If multiple issues exist in the same screenshot, create separate objects for each
                - If no issues are found, output: None
                """