"""Prompt templates for focused mode test planning.

Focused mode generates deep end-to-end test cases for a specific user journey,
as opposed to explore mode which generates many independent test cases for
broad coverage. The execution agent is the same — only planning prompts differ.
"""

import json
from typing import Optional

from webqa_agent.prompts.test_planning_prompts import \
    _get_custom_tools_planning_section
from webqa_agent.tools.base import ActionTypes


def get_focused_test_design_standards(language: str = 'zh-CN') -> str:
    """Get test case design standards for focused E2E mode.

    Replaces granularity/activation sections from the shared standards
    to avoid conflicting with focused mode's E2E journey design principle.
    Keeps step rules, test data, scroll/mouse, and i18n sections unchanged.

    Args:
        language: Language for test case naming (zh-CN or en-US)

    Returns:
        String containing focused mode test case design standards
    """
    name_language = '中文' if language == 'zh-CN' else 'English'
    action_types_str = ActionTypes.get_prompt_string()
    output_lang_instruction = (
        '**所有字段内容（name、objective、steps 的 action/verify 描述、'
        'success_criteria 等）均使用中文输出。**'
        if language == 'zh-CN'
        else '**All field content (name, objective, step action/verify '
        'descriptions, success_criteria, etc.) must be written in English.**'
    )
    return f"""## Test Case Design Standards (Focused E2E Mode)

{output_lang_instruction}

### 1. Granularity: One Test Case = One Complete E2E User Journey
- Design ONE or FEW deeply detailed test cases (typically 1-3)
- Each case traces a COMPLETE workflow: entry → operations → verification → completion
- Steps are SEQUENTIAL and DEPENDENT — step N builds on step N-1's result
- Include 8-15 steps per case covering the full journey
- Insert verification checkpoints at critical milestones (not just at the end)
- When multiple objectives are provided, organize cases by natural grouping:
  - Chain dependent objectives into one E2E case (e.g., create → view → edit)
  - Keep truly independent objectives as separate cases
  - Total cases typically equals number of independent objective groups
- ✅ Complete E2E flow in one case: upload → process → interact → verify → check history
- ❌ Splitting a journey into many small independent cases
- ❌ Generating separate cases for each navigation link or button

### 2. Functional Activation — Trace the COMPLETE journey, not isolated features
- **Multi-step workflows**: Follow the full user journey from start to finish
- **Cross-feature interactions**: Test how features connect (e.g., upload → read → verify)
- **State persistence**: Verify data survives across navigation, refresh, re-login
- **Checkpoint verification**: Insert verify steps at key milestones within the journey

### 3. Field Reference
- **`name`**: 简洁描述端到端业务场景 (使用{name_language}命名)
- **`objective`**: The complete user journey being validated end-to-end
- **`test_category`**: e.g. E2E_Workflow, Critical_Path
- **`priority`**: Critical / High (focused cases are typically high priority)
- **`business_context`**: The end-to-end user scenario and its business value
- **`domain_specific_rules`**: Industry-specific validation rules (if applicable)
- **`test_data_requirements`**: What test data is needed across the journey
- **`steps`**: Sequential action/verify pairs forming the complete journey. Available action types: {action_types_str}
  - **FORBIDDEN in steps**: `elementRef`, `elementId`, `domId`
- **`preamble_actions`**: Optional setup steps before the journey begins.
  Each entry is a single atomic operation with concrete parameters.
  Format: `{{"action": "<instruction>", "params": {{"url": "..."}}}}` (params optional but preferred for URLs).
- **`reset_session`**: true/false for test isolation
- **`success_criteria`**: End-to-end pass/fail conditions covering the complete journey

### 4. Step Rules
1. **One atomic action per step** — no compound instructions
2. **Merge consecutive verifies (MANDATORY)**: Multiple verify steps with no action between them MUST be combined into one.
   - ❌ `[{{"verify": "Title correct"}}, {{"verify": "Email input visible"}}, {{"verify": "Button present"}}]`
   - ✅ `[{{"verify": "Title is correct, email input is visible, and submit button is present"}}]`
3. **Element descriptions**: semantic role + visual label + context location
   - ✅ `"Click the search submit button (magnifying glass icon) next to the search input"`
   - ❌ `"Click element 36"` or `"Click the first button"`
4. **Navigation return**: Use `GoBack` to return to previous page (preserves history); use `GoToPage` only for direct URL jumps
5. **Single-tab environment**: all navigation happens in the current tab — no "new tab", "switch tab", "open in new window"
6. **verify** = functional result a user would see (behavior, data, logic)
   **ux_verify** = visual/layout quality (typos, alignment, rendering) — use after navigation or dynamic content load
7. **Journey checkpoint pattern**: Insert a verify/ux_verify step after every 3-5 action steps to validate journey progress

### 5. Test Data
- Use realistic data consistent across the ENTIRE journey
- If step 1 uploads "test_paper.pdf", later steps should reference the same file
- Maintain data consistency: IDs, names, content created in early steps must be verifiable in later steps
- Edge cases: include within the journey where natural (e.g., empty field during form filling)

### 6. Scroll vs Mouse
- **Scroll**: scroll page to bring a **specific element** into view → `{{"action": "Scroll to the footer section"}}`
- **Mouse wheel**: precise distance/direction control → `{{"action": "Scroll down 300 pixels using mouse wheel"}}` (value: `"wheel:0,300"`)
- **Mouse move**: coordinate-based interaction (canvas, drawing) → `{{"action": "Move mouse to position (150, 300)"}}` (value: `"move:150,300"`)
- For standard element clicks/hovers, always prefer `Tap`/`Hover` — only use Mouse when coordinate precision is required

### 7. i18n Language Detection
When testing language switching: use navigation menu text as the primary language indicator. Switch to the non-current language first to ensure observable change. Product names staying in English after switch is expected behavior."""


def get_focused_planning_system_prompt(
    focused_objective: str,
    language: str = 'zh-CN',
    enabled_custom_tools: Optional[list[str]] = None,
    file_catalog: str = '',
) -> str:
    """Generate system prompt for focused E2E test case planning.

    Args:
        focused_objective: Use-case-level objective for focused testing
        language: Language for test case naming (zh-CN or en-US)
        enabled_custom_tools: List of enabled custom tool step_types
        file_catalog: Formatted file catalog string

    Returns:
        Formatted system prompt string
    """
    if isinstance(focused_objective, str):
        focused_objective_str = focused_objective
    elif focused_objective:
        focused_objective_str = str(focused_objective)
    else:
        focused_objective_str = ''

    role_and_objective = """## Role
You are a Senior QA Test Engineer specialized in end-to-end scenario testing
and user journey validation. Your expertise is designing deep, thorough test
cases that trace a COMPLETE user journey from start to finish.

## Primary Objective
Given a SPECIFIC test objective, design focused end-to-end test case(s) that
thoroughly validate the COMPLETE user journey. Your test case(s) should be
deep rather than broad — trace the full workflow with detailed steps and
verification checkpoints. Prioritize depth and completeness of the target
scenario over breadth of coverage."""

    mode_section = f"""## Test Planning Mode: Focused End-to-End Testing
**Focused Objective**: {focused_objective_str}

### Objective Input Format

The focused objective above may be provided in two formats:

**Format A — Single Objective** (simple string):
A single sentence describing one test goal. Generate 1-3 E2E test cases.

**Format B — Multi-Objective Specification** (structured text):
A structured document containing multiple test objectives with metadata
(test data, preconditions, expected results). When you receive this format:
1. Parse ALL objectives and their metadata
2. Analyze dependencies between objectives based on preconditions
3. Decide how to organize test cases:
   - Merge dependent objectives into sequential E2E cases
     (preferred when preconditions chain naturally)
   - Keep independent objectives as separate test cases
4. For each test case, respect the specified test data and expected results

### Analysis Approach

#### Phase 1: Journey Understanding
1. **Objective Decomposition**: Parse the focused objective to understand
   the complete user workflow it implies
2. **Journey Mapping**: Identify the start point, key milestones, and
   completion criteria of the journey
3. **Feature Scope**: Determine which features/pages are involved in this
   specific journey (ignore unrelated features)

#### Phase 2: Journey Step Decomposition
4. **Step Sequencing**: Break the journey into ordered, sequential steps
   that form a continuous workflow
5. **Dependency Analysis**: Ensure each step naturally follows from the
   previous one's outcome
6. **Data Flow Tracking**: Identify data created/modified in early steps
   that must be verified in later steps

#### Phase 3: Verification Checkpoint Design
7. **Milestone Verification**: Insert verification points at critical
   milestones (not just at the end)
8. **Cross-Step Validation**: Design verifications that check state
   persistence across multiple steps
9. **Acceptance Criteria**: Define clear pass/fail conditions for the
   complete end-to-end journey

### CRITICAL — Focus Constraint
- ALL steps MUST relate to the focused objective
- Do NOT test unrelated features, even if visible on the page
- Do NOT generate separate cases for each navigation link or button
- Stay within the journey — depth over breadth
- Generate 1-3 deeply detailed test cases, NOT 5-10 shallow ones

### What makes a good focused test case:
✅ Complete E2E flow: upload → process → interact → verify → check history
✅ Deep step sequence (8-15 steps) with verification checkpoints every 3-5 actions
✅ Cross-step state verification (data created in step 1 verified in step 10)
✅ Covers the FULL journey from entry to completion

### What to AVOID:
❌ Splitting the journey into many small independent cases
❌ Testing unrelated features (login, settings) unless part of the journey
❌ Generating 5+ separate single-feature test cases
❌ Shallow cases with only 2-3 steps"""

    standards = get_focused_test_design_standards(language)
    custom_tools_section = _get_custom_tools_planning_section(enabled_custom_tools)

    # Build steps example
    steps_example = """      {{"action": "Navigate to the target feature area"}},
      {{"verify": "Verify the feature page loads correctly"}},
      {{"action": "Perform the primary workflow action"}},
      {{"action": "Continue with the next step in the journey"}},
      {{"verify": "Verify intermediate milestone is reached correctly"}},
      {{"action": "Complete the workflow"}},
      {{"verify": "Verify the end-to-end journey completed successfully"}},
      {{"ux_verify": "Verify the final state displays correctly without visual issues"}}"""

    system_prompt = f"""
{role_and_objective}

{mode_section}

{custom_tools_section}

{standards}

## Output Format Requirements

Your response must be ONLY in JSON format. Do not include any analysis,
explanation, or additional text outside the JSON structure.

```json
[
  {{
    "name": "端到端场景名称",
    "objective": "complete_e2e_journey_description",
    "test_category": "E2E_Workflow",
    "priority": "Critical",
    "business_context": "end_to_end_user_scenario_and_business_value",
    "domain_specific_rules": "industry_specific_validation_requirements",
    "test_data_requirements": "data_needed_across_the_complete_journey",
    "preamble_actions": [optional_setup_steps],
    "steps": [
{steps_example}
    ],
    "reset_session": boolean_isolation_flag,
    "success_criteria": ["end_to_end_measurable_conditions"]
  }}
]
```

"""

    if file_catalog:
        system_prompt += f"""

## File Upload Testing
File upload is a SINGLE action step. The Upload action automatically handles clicking the file input
and injecting the file — do NOT plan separate "Click upload button" and "Upload file" steps.

When you identify file upload controls (input[type="file"]) on the page:
- Include ONE upload step per file, using only filenames from the available test files below
- Do NOT invent filenames; use only files from the list below

Available test files:
{file_catalog}
"""

    return system_prompt


def get_focused_planning_user_prompt(
    state_url: str,
    page_text_summary: Optional[dict] = None,
    priority_elements: Optional[dict] = None,
    all_page_links: Optional[list] = None,
    navigation_map: Optional[dict] = None,
) -> str:
    """Generate user prompt for focused E2E test case planning.

    Args:
        state_url: Target URL
        page_text_summary: Intelligent text summary
        priority_elements: Journey-filtered priority elements
        all_page_links: List of all navigable page links
        navigation_map: Element-to-URL correlation mapping

    Returns:
        Formatted user prompt string
    """
    # Build page content summary section
    content_section = ''
    if page_text_summary:
        coverage = page_text_summary.get('coverage', 'N/A')
        text_content = page_text_summary.get('text_content', [])
        estimated_tokens = page_text_summary.get('estimated_tokens', 0)
        strategy = page_text_summary.get('strategy_used', 'unknown')
        sample_text = text_content[:30] if len(text_content) > 30 else text_content

        content_section = f"""## Page Content Summary
- **Coverage**: {coverage} of total page text
- **Estimated Tokens**: {estimated_tokens}
- **Sampling Strategy**: {strategy}
- **Key Text Segments**:
```json
{json.dumps(sample_text, ensure_ascii=False, indent=2)}
```
{"... (showing representative sample from full page)" if len(text_content) > 30 else ""}

**Purpose**: Understand page context and content areas to identify which parts
are relevant to the focused objective.
"""

    # Build priority elements section
    elements_section = ''
    if priority_elements:
        elements_count = len(priority_elements)
        elements_json = json.dumps(priority_elements, ensure_ascii=False, indent=2)

        elements_section = f"""## Journey-Relevant Interactive Elements
**{elements_count} elements** identified as relevant to the focused objective:

```json
{elements_json}
```

**Usage**: These elements are filtered for relevance to the target user journey.
Focus your test steps on interacting with these elements in the natural order
of the journey workflow.
"""

    # Build page links section (simplified for focused mode)
    links_section = ''
    if all_page_links:
        sample_links = all_page_links[:30]
        links_json = json.dumps(sample_links, ensure_ascii=False, indent=2)

        links_section = f"""## Available Page Links
**{len(all_page_links)} navigable links** on the page:

```json
{links_json}
```
{"... (showing first 30 of " + str(len(all_page_links)) + " total links)" if len(all_page_links) > 30 else ""}

**Purpose**: Use these links only to understand navigation paths relevant
to the focused journey. Do NOT generate test cases for each link.
"""

    user_prompt = f"""## Application Under Test (AUT)
- **Target URL**: {state_url}
- **Visual Element Reference**: The attached screenshot shows the ENTIRE webpage
  with numbered markers for interactive elements.

**IMPORTANT**: The screenshot captures the complete page from top to bottom.
All elements are numbered and can be referenced during test planning. The
execution system will automatically handle scrolling to elements outside
the viewport.

{content_section}

{links_section}

{elements_section}

Please design focused end-to-end test case(s) following the standards in
the system prompt. Remember:
1. **Depth over breadth**: 1-3 deep E2E cases, NOT many shallow ones
2. **Complete journey**: Trace the full workflow from start to finish
3. **Verification checkpoints**: Insert verify steps at critical milestones
4. **Stay focused**: ALL steps must relate to the focused objective
"""

    return user_prompt


def get_focused_planning_prompt(
    focused_objective: str,
    state_url: str,
    language: str = 'zh-CN',
    page_text_summary: Optional[dict] = None,
    priority_elements: Optional[dict] = None,
    all_page_links: Optional[list] = None,
    navigation_map: Optional[dict] = None,
    enabled_custom_tools: Optional[list[str]] = None,
    file_catalog: str = '',
) -> tuple[str, str]:
    """Generate prompts for focused E2E planning (system + user prompt).

    Args:
        focused_objective: Use-case-level objective
        state_url: Target URL
        language: Language for test case naming
        page_text_summary: Intelligent text summary
        priority_elements: Journey-filtered priority elements
        all_page_links: All navigable page links
        navigation_map: Element-to-URL correlation mapping
        enabled_custom_tools: Enabled custom tool step_types
        file_catalog: Formatted file catalog string

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    system_prompt = get_focused_planning_system_prompt(
        focused_objective, language, enabled_custom_tools, file_catalog
    )
    user_prompt = get_focused_planning_user_prompt(
        state_url, page_text_summary, priority_elements,
        all_page_links, navigation_map,
    )
    return system_prompt, user_prompt


# ============================================================================
# Focused Mode Element Filtering Prompts
# ============================================================================

def get_focused_element_filtering_system_prompt(language: str = 'zh-CN') -> str:
    """Generate system prompt for focused mode element filtering.

    Filters elements by journey relevance instead of broad business value.

    Args:
        language: Language for naming

    Returns:
        System prompt for journey-focused element filtering
    """
    role_desc = '专业QA工程师' if language == 'zh-CN' else 'Professional QA Engineer'

    return f"""You are a {role_desc} filtering interactive elements based on
their relevance to a SPECIFIC user journey.

## Core Responsibility
Select elements that a user would interact with or observe during the
specified user journey. Exclude elements for unrelated features.

## Prioritization Framework (Journey-Focused)

### Tier 1: Journey-Critical Elements (Must Include)
- Elements directly used in the target user journey workflow
- Entry points to the journey (navigation to the feature area)
- Core interaction controls (buttons, inputs, dropdowns for the feature)
- Primary action triggers within the journey

### Tier 2: Journey-Adjacent Elements (Should Include)
- Verification indicators (status, results, feedback messages)
- State transition elements (loading, progress, confirmation)
- Supporting controls within the same feature area
- Navigation elements needed to reach the journey's pages

### Tier 3: Exclude (Do NOT Include)
- Elements for completely unrelated features
- Generic footer/header elements not part of the journey
- Decorative or informational elements outside the feature scope
- Navigation links to unrelated sections

## Selection Rule
ONLY select elements relevant to the focused objective.
Prefer fewer, highly relevant elements over a broad selection.
Order elements by their temporal position in the journey workflow
(elements encountered first in the journey appear first).

## Output Format
Return ONLY a JSON array (no markdown code blocks, no explanation):
[
  {{"id": "element_id", "priority": "tier1", "reason": "brief justification"}},
  {{"id": "element_id2", "priority": "tier2", "reason": "brief justification"}},
  ...
]

Order by: tier1 first, then tier2. Within each tier, order by expected
temporal position in the journey workflow.
Maximum elements to return: as specified in user prompt.
"""


def get_focused_element_filtering_user_prompt(
    url: str,
    focused_objective: str,
    elements: dict,
    max_elements: int = 30,
) -> str:
    """Generate user prompt for focused mode element filtering.

    Args:
        url: Target URL
        focused_objective: Use-case-level objective
        elements: Simplified element data
        max_elements: Maximum number of elements to select

    Returns:
        User prompt for journey-focused element filtering
    """
    elements_json = json.dumps(elements, ensure_ascii=False, indent=2)

    return f"""## Analysis Context
- **Target URL**: {url}
- **Focused Objective**: {focused_objective}
- **Total Elements Found**: {len(elements)}
- **Required Selection**: Top {max_elements} journey-relevant elements

## Interactive Elements Data
{elements_json}

**Your Task**: Select the top {max_elements} elements most relevant to the
focused objective's user journey. ONLY include elements that would be
interacted with or observed during this specific workflow. Exclude elements
for unrelated features. Return in the specified JSON format."""


# ============================================================================
# Focused Mode Reflection Prompts
# ============================================================================

def get_focused_reflection_system_prompt(
    language: str = 'zh-CN',
    enabled_custom_tools: Optional[list[str]] = None,
) -> str:
    """Generate system prompt for focused mode reflection.

    Constrains reflection to the same objective scope — no diverging
    to unrelated features.

    Args:
        language: Language for test case naming
        enabled_custom_tools: List of enabled custom tool step_types

    Returns:
        Formatted system prompt
    """
    name_language = '中文' if language == 'zh-CN' else 'English'
    standards = get_focused_test_design_standards(language)
    custom_tools_section = _get_custom_tools_planning_section(enabled_custom_tools)
    action_types_str = ActionTypes.get_prompt_string()

    return f"""## Role
You are a Senior QA Test Engineer conducting focused test execution oversight.
Your mission is to evaluate whether the focused user journey has been
adequately tested, and decide whether to continue, replan within scope,
or finish.

## CRITICAL — Focused Mode Reflection Constraints

This is a FOCUSED test execution targeting a SPECIFIC user journey.
Your reflection MUST stay within the scope of the original focused objective.

### Allowed REPLAN Scenarios:
✅ Edge cases WITHIN the same journey (e.g., error handling in the workflow)
✅ Alternative paths in the same workflow (e.g., cancel and retry)
✅ Missed verification points in the journey
✅ Deeper validation of a step that showed issues
✅ Retry with modified approach when critical steps failed

### Forbidden REPLAN Scenarios:
❌ Testing completely unrelated features on the page
❌ Generating comprehensive feature-isolation test cases
❌ Exploring page areas outside the journey scope
❌ Creating broad test suites for the entire application
❌ Adding test cases for navigation links not part of the journey

### Decision Override:
If the focused journey has been fully tested and key verifications passed,
prefer FINISH over REPLAN — even if there are untested features on the page.
The goal is journey depth, not page coverage.

## Decision Framework

### Phase 0: Normal Progress Detection (HIGHEST PRIORITY)
IF (completed_cases < total planned cases) AND (last case succeeded) AND
(no critical errors): THEN CONTINUE

### Phase 1: Journey Completion Assessment
IF (all planned journey cases completed) AND (critical verifications passed):
THEN FINISH

### Phase 2: Journey Gap Analysis
IF (journey has untested edge cases or alternative paths within scope):
THEN REPLAN with new cases WITHIN the focused objective scope

## Output Format

### For CONTINUE or FINISH:
```json
{{
  "decision": "CONTINUE" | "FINISH",
  "reasoning": "explanation with journey completion assessment",
  "coverage_analysis": {{
    "journey_coverage_percent": estimated_percentage,
    "critical_checkpoints_passed": count,
    "remaining_journey_gaps": "description or none"
  }},
  "new_plan": []
}}
```

### For REPLAN (within scope only):
```json
{{
  "decision": "REPLAN",
  "reasoning": "what journey aspect needs additional testing",
  "replan_strategy": {{
    "scope_justification": "how this relates to the original focused objective",
    "journey_gap": "specific gap in the journey coverage"
  }},
  "new_plan": [
    {{
      "name": "补充测试用例（{name_language}命名）",
      "objective": "specific_journey_gap_to_fill",
      "test_category": "E2E_Workflow",
      "priority": "High",
      "business_context": "how this supplements the journey",
      "steps": [
        {{"action": "action_instruction"}},
        {{"verify": "validation_instruction"}}
      ],
      "preamble_actions": ["setup_steps_to_reach_journey_point"],
      "reset_session": true,
      "success_criteria": ["measurable_conditions"]
    }}
  ]
}}
```

{standards}

{custom_tools_section}

## Available Action Types for Replanning
{action_types_str}
"""


def get_focused_reflection_user_prompt(
    focused_objective: str,
    current_plan: list,
    completed_cases: list,
    page_content_summary: Optional[dict] = None,
    running_cases: Optional[list[str]] = None,
) -> str:
    """Generate user prompt for focused mode reflection.

    Args:
        focused_objective: Original focused objective
        current_plan: Current test plan
        completed_cases: Completed test cases
        page_content_summary: Interactive element mapping
        running_cases: Names of currently executing cases

    Returns:
        Formatted user prompt
    """
    completed_summary = json.dumps(completed_cases, indent=2)
    current_plan_json = json.dumps(current_plan, indent=2)

    interactive_elements_section = ''
    if page_content_summary:
        interactive_elements_json = json.dumps(page_content_summary, indent=2)
        interactive_elements_section = f"""
- **Interactive Elements Map**:
{interactive_elements_json}
- **Visual Element Reference**: Screenshot with numbered markers for elements.
"""

    concurrent_context = ''
    if running_cases:
        running_json = json.dumps(running_cases, ensure_ascii=False)
        concurrent_context = f"""
- **Currently Running Cases** (DO NOT replan these):
{running_json}
"""

    return f"""## Testing Mode: Focused End-to-End Testing
**Original Focused Objective**: {focused_objective}

**REMINDER**: Any REPLAN must stay within the scope of this focused objective.
Do NOT generate test cases for unrelated features.

## Execution Context
- **Current Test Plan**:
{current_plan_json}
- **Completed Test Results**:
{completed_summary}{concurrent_context}

### Execution Metrics Guide
- `metrics.total_steps` / `metrics.passed_steps` / `metrics.failed_steps`: Step-level results
- `failed_step_details`: Array with step_id, description, status, type
- High passed ratio (>80%): journey mostly successful, likely FINISH
- Low passed ratio (<50%): consider REPLAN for failed journey segments

- **Current Application State**: (via attached screenshot){interactive_elements_section}

## Journey Completion Criteria
- Has the focused objective been fully validated?
- Were critical milestones in the journey verified?
- Are there meaningful edge cases WITHIN the journey worth testing?
- If journey is complete, prefer FINISH over unnecessary REPLAN.

Please analyze and provide your decision in JSON format."""


def get_focused_reflection_prompt(
    focused_objective: str,
    current_plan: list,
    completed_cases: list,
    page_content_summary: Optional[dict] = None,
    language: str = 'zh-CN',
    enabled_custom_tools: Optional[list[str]] = None,
    running_cases: Optional[list[str]] = None,
) -> tuple[str, str]:
    """Generate prompts for focused mode reflection (system + user prompt).

    Args:
        focused_objective: Original focused objective
        current_plan: Current test plan
        completed_cases: Completed test cases
        page_content_summary: Interactive element mapping
        language: Language for naming
        enabled_custom_tools: Enabled custom tool step_types
        running_cases: Currently executing case names

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    system_prompt = get_focused_reflection_system_prompt(
        language, enabled_custom_tools
    )
    user_prompt = get_focused_reflection_user_prompt(
        focused_objective, current_plan, completed_cases,
        page_content_summary, running_cases=running_cases,
    )
    return system_prompt, user_prompt
