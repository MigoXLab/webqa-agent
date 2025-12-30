"""Prompt templates for test planning and case generation."""

import json

from webqa_agent.testers.case_gen.tools.base import ActionTypes
from webqa_agent.testers.case_gen.tools.registry import get_registry


def _get_custom_tools_planning_section() -> str:
    """Generate custom tools documentation section for planning prompt.

    Creates a dynamic documentation section listing all registered custom tools
    with their step_type identifiers. This helps LLMs understand available
    custom tools during test case planning.

    Important distinctions:
    - step_type: Documentation identifier/label (e.g., 'detect_dynamic_links')
    - Tool selection: Entirely LLM-driven based on tool descriptions
    - NO tool masking: LLM can freely choose any tool regardless of step_type

    The step_type serves as a human-readable label in planning prompts like:
        "Use these custom actions: detect_dynamic_links, custom_api_test"

    Returns:
        str: Formatted string describing custom step types with descriptions.
             Empty string if no custom tools are registered.

    Example output:
        "Custom Actions:\\n  - detect_dynamic_links: Detects new links after interactions\\n"
    """
    registry = get_registry()
    custom_tools = []
    for name in registry.get_tool_names():
        metadata = registry.get_metadata(name)
        if metadata and hasattr(metadata, 'category') and metadata.category == 'custom' and hasattr(metadata, 'step_type') and metadata.step_type:
            custom_tools.append((name, metadata))

    if not custom_tools:
        return ''

    section = '## Available Custom Step Types:\n'
    section += 'In addition to standard action/verify/ux_verify steps, you can use these custom step types:\n\n'

    for name, metadata in custom_tools:
        section += f'- **`{metadata.step_type}`**: {metadata.description_short}\n'

        # Add use cases
        if metadata.use_when:
            section += f"  - ✅ **Use for**: {', '.join(metadata.use_when)}\n"

        # Add anti-patterns
        if metadata.dont_use_when:
            section += f"  - ❌ **Don't use for**: {', '.join(metadata.dont_use_when)}\n"

        # Add example usage - show up to 3 examples for better few-shot learning
        if metadata.examples:
            section += '  - 📝 **Examples**:\n'
            for i, example in enumerate(metadata.examples[:3], 1):
                section += f'    {i}. `{example}`\n'

        section += '\n'

    # Build dynamic list of custom tool names from registered tools
    custom_tool_names = [metadata.step_type for _, metadata in custom_tools] if custom_tools else []
    custom_tools_list = ', '.join(custom_tool_names) if custom_tool_names else 'none currently registered'

    # Updated note to reflect unified format with action + params
    section += (
        '**Note**: Custom tools use `action` field with optional `params` object.\n'
        'These tools are **automatically registered as available action types** - you can use them just like core UI actions.\n'
        'Format: `{"action": "tool_name", "params": {"param1": value, ...}}`\n\n'
        '**Usage Distinction**:\n'
        f'- **Custom tools** ({custom_tools_list}): Testing utilities - can use technical parameters\n'
        '- **Core UI actions** (Tap, Input, Scroll): User simulations - should use natural language from user perspective\n'
    )
    return section


def get_shared_test_design_standards(language: str = 'zh-CN') -> str:
    """Get shared test case design standards for reuse in plan and reflect
    modules.

    Args:
        language: Language for test case naming (zh-CN or en-US)

    Returns:
        String containing complete test case design standards
    """
    name_language = '中文' if language == 'zh-CN' else 'English'
    # Get dynamic action types from registry (supports custom extensions)
    action_types_str = ActionTypes.get_prompt_string()
    return f"""## Test Case Design Standards

### Test Case Granularity Principle (CRITICAL - HIGHEST PRIORITY)
**Single Responsibility Rule**: Each test case MUST test ONE complete functional scenario.

#### Core Granularity Definition:
- **One Test Case = One Functional Scenario** (NOT just one single action)
- A "Functional Scenario" typically includes: [Setup] → [User Actions] → [Verification]
- Ideally, a test case validates one specific user goal or business rule.

#### Granularity Guidelines:

**✅ Correct Scope (One Functional Scenario)**:
- "Verify searching for 'Python' returns results" (Includes: Input text → Click search → Verify results)
- "Verify login with valid credentials" (Includes: Input user → Input pass → Click login → Verify dashboard)
- "Verify 'Home' navigation" (Includes: Click Home → Verify URL & Content)
- "verify Check A and Check B" (Includes: Check A + Check B)

**Coverage Requirement for Navigation (MANDATORY)**:
- **Generate a SEPARATE test case for EACH button/link in the navigation bar.**
- **Full Coverage**: If the navigation bar has 5 links, you MUST generate 5 corresponding test cases. Do not skip any navigation items.

**❌ Too Broad (Multiple Scenarios)**:
- "Test all search functionality" (Combining exact match, no results, special chars in one case)
- "Test entire checkout flow" (Better to split: Add to Cart, Update Cart, Checkout Form, Payment)

**❌ Too Narrow (Fragmented Actions)**:
- "Click search input" (Only clicking, no meaningful result)
- "Type 'Python'" (Only typing, no search execution)
- "Verify search button exists" (Static check, no interaction)

**When to Split vs. Keep Together**:
- **Split**: If you are testing different *outcomes* (e.g., success vs. failure) or different *inputs* (valid vs. invalid).
- **Keep Together**: All steps required to achieve *one* specific outcome (e.g., filling a form requires multiple inputs).

**Test Case Completeness Requirements**:
- Every test case MUST include at least ONE meaningful user action sequence that leads to a verifiable result.
- Avoid test cases that only verify initial state without interaction.

### Test Case Granularity Principle (CRITICAL)
Each test case must focus on ONE specific functionality:
- ✅ One navigation link = One test case
- ✅ One search scenario = One test case
- ✅ One form field = One test case
- ❌ All search scenarios = One test case (Too broad)

- **`name`**: 简洁直观的测试名称，反映业务场景和测试目的 (使用{name_language}命名)
- **`objective`**: Clear statement linking the test to specific business requirements and domain context
- **`test_category`**: Enhanced classification including domain-specific categories (Ecommerce_Functional, Banking_Security, Healthcare_Compliance, etc.)
- **`priority`**: Test priority level based on comprehensive impact assessment (Critical, High, Medium, Low):
  - **Functional Criticality**: Core business functions, user-facing features, transaction-critical operations
  - **Business Impact**: Revenue impact, customer experience, operational continuity
  - **Domain Criticality**: Industry-specific requirements, compliance needs, regulatory validation
  - **User Impact**: Usage frequency, user journey importance, accessibility needs
  *(Note: The above are conceptual criteria for determining the `priority` field value, not separate database fields)*
- **`business_context`**: Description of the business process or user scenario being validated
- **`domain_specific_rules`**: Industry-specific validation requirements or compliance rules
- **`test_data_requirements`**: Specification of domain-appropriate test data and setup conditions
- **`steps`**: Detailed test execution steps with clear action/verification pairs that simulate real user behavior and scenarios
  - `action`: User-scenario action instructions describing what a real user would do in natural language. **Available action types (core UI actions + custom tools)**: {action_types_str}.
  - `verify`: User-expectation validation instructions describing what result a real user would expect to see
  - **FORBIDDEN FIELDS**: Do NOT output `elementRef`, `elementId`, `domId`, or any other technical identifiers in the step objects. The system handles element resolution automatically based on your semantic description.
- **`preamble_actions`**: Optional setup steps to establish required test preconditions
- **`reset_session`**: Session management flag for test isolation strategy
- **`success_criteria`**: Measurable, verifiable conditions that define test pass/fail status

#### Step Decomposition Rules:
1. **One Action Per Step**: Each step in the `steps` array must contain ONLY ONE atomic action, using one of the available action types: {action_types_str}.
2. **Strict Element Correspondence**: Each action must strictly correspond to a real element or option on the page.
3. **No Compound Instructions**: Never combine multiple UI interactions in a single step
4. **Navigation Return Strategy**: When a step navigates to a new page (via link click, form submission, etc.) and subsequent steps require the original page context:
   - Add an explicit `GoBack` action to return to the previous page
   - Example scenario: Testing multiple footer links requires returning to homepage between each link test
   - Use GoBack instead of GoToPage when the goal is to return to the immediate previous page (preserves browser history)
   - GoBack works on all page types (HTML, PDF, etc.) since it's a browser-level operation
   - Note: GoBack returns boolean indicating success (true if navigation occurred, false if no browser history exists)
6. **Sequential Operations**: Multiple operations on the same or different elements must be separated into distinct steps
7. **State Management**: Each step should account for potential page state changes after execution
8. **Language State Awareness**: When testing internationalization features (language switchers, multi-language content), observe the current page language from the screenshot and DOM text BEFORE planning steps. Switch to the non-current language first to ensure observable changes. Use navigation menu text as primary language indicator (highest reliability), followed by headings and body content.

#### Browser Environment: Single-Tab Mode
**System Configuration**: This test execution environment enforces strict single-tab mode through 7-layer interception architecture. All browser navigation occurs exclusively within the current tab.

**Critical Visual-Runtime Behavior Gap**:
- **What you see in HTML/Screenshots**: `<a href="/page" target="_blank">` or "Open in new tab" links
- **What actually happens at runtime**: The current tab navigates to the new URL (all `target="_blank"` attributes are intercepted and rewritten to `target="_self"`)
- **How to design test steps**: Use standard click → verify → GoBack navigation pattern

**Correct Single-Tab Navigation Pattern**:
✅ **CORRECT Pattern**:
```json
[
  {{"action": "Click the 'About Us' link in the footer"}},
  {{"verify": "Verify the About Us page content is displayed"}},
]
```

❌ **AVOID**: References to "new tab", "switch tab", "open in new window", "close tab" - these concepts do not exist in the execution environment.

#### Visual Language Detection for I18n Testing

When designing test cases for language switching or internationalization features:

**Detection Methodology**:
1. **Primary Indicators (50% weight)**: Navigation menu text (e.g., "首页" vs "Home", "产品" vs "Products")
2. **Secondary Indicators (30% weight)**: Page headings and titles
3. **Tertiary Indicators (15% weight)**: Body content and descriptions
4. **Ignore**: Product names (often English regardless), technical terms (APIs, URLs), footer copyright (5%)

**Mixed-Language Decision Rule**:
- If Navigation + Headings are 70%+ in Language A → Page language = A
- If mixed 50/50 → Use navigation menu as tiebreaker
- Document detected language ratio in `business_context` field

**Field Usage Guidelines**:
- `name`: Include clear language switching indicator in test name (e.g., "中英文切换用户体验验证" or "Language Switcher Validation")
- `objective`: Include detected current language with confidence level (e.g., "Validate language switcher functionality (detected current: Chinese from navigation text '首页', '产品', '关于我们' - confidence 90%)")
- `business_context`: Document language state and switching strategy with visual indicators (e.g., "Page loads in Chinese based on navigation menu language (Chinese characters detected in primary nav elements). Test switches to English first to ensure observable content change (Chinese → English transition), then back to Chinese to verify bidirectional functionality. Product names may remain in English across language switches (expected behavior for international brands).")
- `test_data_requirements`: Specify language detection methodology with weighted indicators (e.g., "Visual language detection from screenshot: Navigation menu (primary indicator - 50% weight), page headings (secondary - 30%), body content (tertiary - 15%). Ignore product names, technical terms, and footer text (5%).")
- `domain_specific_rules`: Note expected behavior for mixed-language scenarios and edge cases (e.g., "Language switching should update navigation, headings, and body content. Product names and technical terms may remain in source language. Mixed-language scenarios common in e-commerce (nav in one language, product names in English).")
- `success_criteria`: Include language-specific validation points (e.g., "Language switcher toggles between languages", "Navigation menu text updates correctly on language switch", "Content updates observable (excluding expected English product names)", "No mixed-language artifacts or layout breaks after switching")

**Example Detection Scenarios**:

**Scenario 1 - Clear Chinese Page**:
- Navigation: 100% Chinese ("首页", "产品", "关于我们")
- Headings: 80% Chinese, 20% English (product names)
- Body: 70% Chinese
- **Decision**: Page language = Chinese (navigation is decisive)
- **Test Design**: Switch to English first, verify change, then back to Chinese

**Scenario 2 - Mixed Language E-commerce**:
- Navigation: 100% English ("Home", "Products", "About")
- Headings: 60% English, 40% Chinese (bilingual titles)
- Body: 50/50 mix
- **Decision**: Page language = English (navigation tiebreaker)
- **Test Design**: Switch to Chinese first for observable content change

**Scenario 3 - E-commerce with English Product Names**:
- Navigation: 100% Chinese ("首页", "商品")
- Headings: 50% Chinese, 50% English (all product names are English: "iPhone", "MacBook")
- Body: 60% Chinese, 40% English (product names)
- **Decision**: Page language = Chinese (ignore product names per rule)
- **Test Design**: Product names staying English after language switch is EXPECTED behavior, not a bug

### Action Examples
**✅ Good (User perspective, atomic)**:
```json
[
{{"action": "Click the 'Products' navigation link in the top menu bar"}},
{{"verify": "Verify the page successfully navigated to the Products page"}},
{{"ux_verify": "Verify Products page renders correctly without layout breaks or text truncation in the viewport"}},
]
```

**❌ Bad (Technical, compound)**:
```json
[
{{"action": "Enter search keyword 'product' in the search input field"}},
{{"action": "Click the search submit button (blue button with magnifying glass icon) next to the search input field"}},
{{"verify": "Confirm search results list is displayed"}}
]
```

### Robust Element Reference Guidelines

**Core Principle**: Test steps must use semantic element descriptions that remain valid even when dynamic UI elements appear or DOM structure changes.

#### Why Semantic Descriptions Matter
When UI elements appear dynamically (dropdowns open, modals show, buttons reveal), element IDs often shift based on DOM traversal order. Positional or ID-based references break in these scenarios, causing test failures.

**Common Problem Pattern**:
```
User Interaction → Dynamic UI Change → Element IDs Shift → Positional References Break
```

**Solution Pattern**:
```
Describe elements using STABLE SEMANTIC ATTRIBUTES that persist across DOM changes
```

#### Semantic Attribute Taxonomy

Build element descriptions using stable attributes in priority order:

| Priority | Category | Examples | Usage |
|----------|----------|----------|-------|
| **Highest** | Functional Role | "submit button", "email input", "search field", "dropdown menu" | ALWAYS include |
| **High** | Visual Identifier | Text labels, icons, colors, styles ("blue button", "magnifying glass icon") | Include when visible |
| **Medium** | Contextual Location | Container, semantic position ("in login form", "next to search input") | Include for disambiguation |
| **Low** | State/Relationship | Conditional visibility, dynamic states ("appears when Business selected") | Include for complex scenarios |

#### Element Description Composition Formula

```
MINIMUM: Functional Role + (Visual OR Contextual)
RECOMMENDED: Functional + Visual + Contextual
COMPLEX: Functional + Visual + Contextual + State
```

**Composition Examples**:
- **Simple**: "the submit button (labeled 'Submit')" → Functional + Visual
- **Better**: "the submit button (labeled 'Submit') in the login form" → Functional + Visual + Contextual
- **Best**: "the primary submit button (blue, labeled 'Submit') at the bottom of the login form" → Functional + Visual + Visual + Contextual

#### Few-Shot Examples: Fragile vs Robust Descriptions

**Example 1 - Dropdown Selection**:
```
❌ FRAGILE: "Click element 36" or "Select the first option"
✅ ROBUST: "Select 'California' (text: California) from the state dropdown menu"

Why robust: Uses text content + container context, survives when new options appear
```

**Example 2 - Search Button (Dynamic UI)**:
```
❌ FRAGILE: "Click the search button" or "Click element 45"
✅ ROBUST: "Click the search submit button (blue button with magnifying glass icon) next to the search input field"

Why robust: Combines function + visual + relative position, remains valid when clear button appears
```

**Example 3 - Modal Form Field**:
```
❌ FRAGILE: "Enter email" or "Type in the third field"
✅ ROBUST: "Enter email address in the 'Email' input field (labeled 'Email Address') within the registration modal dialog"

Why robust: Specifies label + container, unambiguous even with multiple email fields on page
```

**Example 4 - Autocomplete Suggestion**:
```
❌ FRAGILE: "Click the suggestion" or "Select item 2"
✅ ROBUST: "Select the autocomplete suggestion 'San Francisco, CA' (displaying population info) from the city search suggestions dropdown"

Why robust: Uses exact text + distinguishing feature + container, survives suggestion order changes
```

**Example 5 - Conditional Form Field (State-Dependent)**:
```
❌ FRAGILE: "Fill the company field" or "Enter text in element 58"
✅ ROBUST: "Enter company name in the 'Company' input field (appears when 'Business' account type is selected) in the registration form"

Why robust: Includes trigger condition + semantic location, handles dynamic visibility
```

**Example 6 - Navigation Submenu**:
```
❌ FRAGILE: "Click Settings" or "Click the fourth item"
✅ ROBUST: "Click the 'Privacy Settings' submenu item under the 'Account' parent menu in the top navigation bar"

Why robust: Specifies hierarchy + location, remains valid when menu items reorder
```

#### Prohibited Anti-Patterns

**DO NOT use these fragile reference patterns**:
1. ❌ **Positional**: "the first button", "element at position 3", "the top one"
2. ❌ **ID-based**: "element 36", "ID: search-btn-45", "component #12"
3. ❌ **Vague**: "the button", "the link", "the input" (without qualifiers)
4. ❌ **Index-only**: "option[2]", "the third item", "second dropdown"
5. ❌ **Relative-only**: "the button below" (without other attributes)

#### Self-Validation Checkpoint

**IMPORTANT - Before finalizing test steps, verify each element description**:
1. ✅ Uses semantic attributes (functional + visual + contextual)
2. ✅ Avoids positional references ("first", "second", "element X")
3. ✅ Would remain valid if new elements appear on the page
4. ✅ Uniquely identifies the element among similar elements

If any check fails, revise the description using the composition formula above.

### Test Data Management Standards
- **Realistic Data**: Use production-like data that reflects real user behavior
- **Boundary Testing**: Include edge cases (minimum/maximum values, empty fields, special characters)
- **Negative Testing**: Invalid data scenarios to test error handling
- **Internationalization**: Multi-language and character set considerations where applicable

### Enhanced Scenario-Specific Test Data Guidelines
- **E-commerce Testing**: Use realistic product data, pricing scenarios, discount codes, payment methods, and shipping addresses
- **Authentication Testing**: Use valid/invalid credential pairs, test accounts with different permission levels, MFA scenarios
- **Search Functionality**: Use realistic search terms, ambiguous queries, and special characters. Search engines should return results for any input.
- **Form Validation**: Test with valid data, empty fields, oversized input, special characters, and format violations
- **File Operations**: Use various file formats, size limits, and naming conventions. Include valid and invalid file types.
- **Data Operations**: Use unique test data to avoid conflicts, include special characters and unicode in text fields
- **Pagination**: Test with data sets that span multiple pages, empty pages, and single page scenarios
- **Banking/Finance**: Use realistic account numbers, transaction amounts, and financial scenarios with proper validation
- **Healthcare**: Use realistic patient data, medical codes, and HIPAA-compliant test scenarios
- **Social Media**: Use realistic user profiles, content types, and interaction patterns

### Scroll vs Mouse Wheel - Usage Guidelines
**CRITICAL**: Understand the difference between `Scroll` and `Mouse` wheel actions.

#### Scroll Action (Element-based Navigation)
- **Purpose**: Scroll the page to bring a specific element into view
- **When to Use**: Navigate to elements outside the current viewport
- **Format**: `{{"action": "Scroll to the footer target element"}}`
- **Behavior**: The system automatically scrolls to center the target element in viewport

### Mouse Action Usage Guidelines
**IMPORTANT**: The Mouse action allows precise cursor positioning and mouse wheel scrolling.

#### Mouse Action Format
- **Mouse Move**: Use format `"Mouse"` action with value `"move:x,y"` where x,y are pixel coordinates
  - Example: `{{"action": "Move mouse cursor to position (100, 200)"}}` with value `"move:100,200"`
  - Use for: Precise cursor positioning, custom drawing areas, coordinate-based interactions

- **Mouse Wheel**: Use format `"Mouse"` action with value `"wheel:deltaX,deltaY"`
  - Example: `{{"action": "Scroll mouse wheel down 300 pixels"}}` with value `"wheel:0,300"`
  - Use for: **Precise scroll distance control, horizontal scrolling, custom scroll behavior**
  - **deltaX**: Horizontal scroll amount (positive = right, negative = left)
  - **deltaY**: Vertical scroll amount (positive = down, negative = up)

#### When to Use Mouse Action
- **Coordinate-based interactions**: Canvas drawing, image mapping, coordinate systems
- **Custom scroll needs**: Horizontal scrolling, specific scroll distances
- **Specialized UIs**: Games, design tools, interactive visualizations

#### Mouse Action Examples
```json
[
  {{"action": "Move mouse to drawing area coordinates (150, 300)"}},
  {{"verify": "Verify cursor position indicator updates"}},
  {{"action": "Scroll horizontally 200 pixels to the right in the carousel"}},
  {{"verify": "Verify next set of items is displayed"}},
  {{"action": "Scroll down 500 pixels using mouse wheel"}},
  {{"verify": "Verify more content is revealed"}}
]
```

**Note**: Mouse action is for **advanced use cases only** (coordinate-based interactions, custom scroll behavior). For standard element interactions (clicking buttons, hovering over links), **always prefer** `Tap` and `Hover` actions which automatically locate elements by ID and handle viewport positioning. Only use Mouse when coordinate-level precision is explicitly required by the test scenario.

### User-Scenario Step Design Standards
**CRITICAL**: All test steps must be designed from the user's perspective to ensure realistic and actionable test scenarios:

#### User Behavior Simulation Requirements
1. **Natural User Actions**:
   - Actions must describe what a real user would actually do (e.g., "Type email address in the signup form" instead of "Enter valid email address 'testuser@example.com' in the email field")
   - Use natural language that reflects user thought processes and behavior patterns
   - Consider user's visual attention flow and interaction sequence
   - Include realistic user hesitation, exploration, and decision-making points

2. **Scenario Coherence**:
   - Steps must follow logical user workflow and mental models
   - Each step should naturally lead to the next based on user expectations
   - Account for user's prior knowledge and learning curve
   - Consider user's emotional state and motivation during the process

3. **User-Expectation Verification**:
   - Verify steps must validate what users care about and expect to see
   - Focus on user-perceivable results rather than technical implementation details
   - Include both explicit user expectations and implicit user satisfaction criteria
   - Consider user's tolerance levels and acceptance thresholds

#### Step Quality Validation Criteria
- **User Reality Check**: "Would a real user actually do this?" - If not, revise the step
- **Action Clarity**: "Can a user understand and perform this action without technical knowledge?" - If not, simplify
- **Result Relevance**: "Does this verification matter to the user experience?" - If not, remove or replace
- **Scenario Completeness**: "Does this represent a complete user task or goal?" - If not, expand

#### Examples of User-Scenario vs Technical Steps

**❌ Technical Action Step (Avoid)**:
```json
{{"action": "Enter valid email address 'testuser@example.com' in the email field"}}
```

**✅ User-Scenario Action Step (Preferred)**:
```json
{{"action": "Type your email address in the signup form like you normally would"}}
```

**❌ Technical Verify Step (Avoid)**:
```json
{{"verify": "Record any exceptions, stack traces, or network request failures in browser console (screenshot and save logs)"}},
{{"verify": "Check DOM element CSS properties and JavaScript event bindings"}},
{{"verify": "Verify HTTP response status code is 200 and check response headers"}}
```

**✅ User-Scenario Verify Step (Preferred)**:
```json
{{"verify": "Confirm page displays 'Login successful' message"}},
{{"verify": "Check if redirected to user homepage"}},
{{"verify": "Confirm form displays error message 'Please enter a valid email'"}}
```

#### Verification Design Principles
- **User-Observable Results**: Focus only on what users can see or experience, never include technical debugging like console logs, DOM inspection, or network monitoring
- **Business Value Validation**: Verify business outcomes and UI changes visible to users, not internal system implementation details

## Core Test Scenario Patterns

### Common Test Patterns
1. **Form Validation**: Test required fields, validation messages, error handling, and successful submission
2. **Search & Discovery**: Test search functionality, filters, result relevance, and edge cases
3. **Navigation**: Test user flows, link functionality, and page transitions
4. **Data Operations**: Test CRUD operations, data consistency, and user feedback

### Pattern Application Guidelines
- **Forms**: Include empty field validation, valid data submission, and error message testing
- **Search**: Test various search terms, filters, and result handling
- **User Flows**: Design steps that reflect realistic user behavior and expectations
- **Adapt patterns** to specific application domain and business requirements

### Enhanced Business Context Integration
- **Business Process Continuity**: Ensure test cases maintain business workflow integrity
- **Domain-Specific Validation**: Include industry-specific validation rules and compliance requirements
- **User Experience Focus**: Consider usability, accessibility, and user satisfaction in all test cases
- **User Scenario Realism**: Design test steps from real user perspective with natural actions and expectations
- **Business Value Alignment**: Ensure each test case validates specific business value and user benefits

### UX Verification Guidelines
**When to use `ux_verify`**:
- After page navigation or URL changes (to check visual rendering)
- After dynamic content loading or AJAX updates (to check layout integrity)
- When testing responsive layouts or viewport changes (to check visual adaptation)
- When validating text-heavy content (to check for typos and readability)

**Key Distinction**:
- `verify` → "Does it **WORK**?" (Functional Testing - behavior, data, logic)
- `ux_verify` → "Does it **LOOK correct**?" (Visual Quality Testing - appearance, text accuracy, layout)

### Navigation Optimization Guidelines
**IMPORTANT**: When generating test cases, apply navigation optimization rules with business context:
- **Minimize Navigation**: Prefer testing multiple features on the same page before navigating away
- **Logical Flow**: Follow realistic user navigation patterns and business workflows
- **State Preservation**: Consider page state changes and user context throughout navigation
- **Business Journey**: Align navigation with typical business user journeys and workflows"""


def get_test_case_planning_system_prompt(
    business_objectives: str,
    language: str = 'zh-CN',
) -> str:
    """Generate system prompt for test case planning.

    Args:
        business_objectives: Business objectives
        language: Language for test case naming (zh-CN or en-US)

    Returns:
        Formatted system prompt string
    """

    # Decide mode based on whether business_objectives is empty
    # Handle case where business_objectives might be a list
    business_objectives_str = business_objectives if isinstance(business_objectives, str) else str(business_objectives) if business_objectives else ''
    if business_objectives_str and business_objectives_str.strip():
        role_and_objective = """## Role
You are a Senior QA Testing Professional with expertise in business domain analysis, requirement engineering, and context-aware test design. Your responsibility is to deeply understand the application's business context, domain-specific patterns, and user needs to generate highly relevant and effective test cases.

## Primary Objective
Conduct comprehensive business domain analysis and contextual understanding before generating test cases. Analyze the application's purpose, industry patterns, user workflows, and business logic to create test cases that are not only technically sound but also business-relevant and domain-appropriate.
"""
        mode_section = f"""## Test Planning Mode: Context-Aware Intent-Driven Testing
**Business Objectives Provided**: {business_objectives_str}

Please follow these steps for comprehensive page analysis:

### Phase 1: Business Domain & Context Analysis
1. **Domain Identification and Business Context**:
   - Identify the specific industry (e.g., e-commerce, finance, healthcare, education, media)
   - Analyze business model and revenue streams (if discernible)
   - Map different user types (customers, administrators, partners, etc.) and their needs
   - Recognize applicable regulations and compliance requirements

2. **Application Purpose and Value Analysis**:
   - Determine primary application purpose (informational, transactional, social, utility, etc.)
   - Identify key user journeys and critical workflows
   - Understand the value proposition and core functionalities
   - Recognize competitive differentiators and unique features

### Phase 2: Functional & Technical Analysis
3. **Functional Module Identification**:
   - Identify main functional areas of the page (navigation bar, login area, search box, forms, buttons, etc.)
   - Analyze interactive elements (input fields, dropdown menus, buttons, links, etc.)
   - Identify business processes (login, registration, search, form submission, etc.)
   - Map UI components to underlying business processes and rules

4. **User Journey & Workflow Analysis**:
   - Analyze possible user operation paths
   - Identify key business scenarios and user workflows
   - Consider exception cases and boundary conditions
   - Account for different user types and permission levels

### Phase 3: Strategic Test Planning
5. **Test Priority Assessment**:
   - Core functionality > auxiliary functionality
   - High-frequency usage scenarios > low-frequency scenarios
   - Business-critical paths > general functionality
   - Revenue impact and user experience considerations

6. **Risk Assessment & Prioritization**:
   - Business Risk Analysis: Identify impact of failures on business operations and revenue
   - User Experience Impact: Prioritize user-facing functionality and usability
   - Technical Complexity: Evaluate implementation complexity and associated risks
   - Compliance and Security: Assess regulatory requirements and security implications

=== Test Case Generation Guidelines ===

**CRITICAL - Test Case Granularity Requirements**:
- **One Test Case = One Functionality**: Each test case must focus on testing ONE specific feature, link, button, or user action
- **Separate Features**: If testing multiple navigation links, create separate test cases for each link (e.g., "Test Home Link", "Test About Link", etc.)
- **Separate Scenarios**: If testing search functionality, create separate test cases for each scenario (e.g., "Exact Match Search", "Case Insensitive Search", "No Results Search")
- **Independent Execution**: Each test case should be independently executable without depending on other test cases
- **Avoid Comprehensive Tests**: Do NOT create comprehensive test cases that test multiple features in one case

**Test Case Generation Rules**:
For each SINGLE functionality, provide:
- **Clear test objectives**: Describe the ONE specific functionality to verify
- **Focused test steps**: Specific operation sequence for THIS functionality only, including:
  * Minimal navigation (if needed)
  * Element interaction for THIS feature
  * Data input for THIS scenario
  * Verification points for THIS functionality
- **Success criteria**: Clear verification conditions for THIS feature only
- **Test data**: Specific test data for THIS scenario only

**Example Granularity**:
- ✅ Generate 5 separate test cases for 5 different navigation links
- ✅ Generate 4 separate test cases for 4 different search scenarios
"""
    else:
        role_and_objective = """## Role
You are a Senior QA Testing Professional with expertise in comprehensive web application analysis and domain-aware testing. Your responsibility is to conduct deep application analysis, understand business context, and design complete test suites that ensure software quality through systematic validation of all functional, business, and domain-specific requirements.

## Primary Objective
Perform comprehensive application analysis including business domain understanding, user workflow identification, and contextual awareness before generating test cases. Apply established QA methodologies including domain-specific testing patterns, business process validation, and risk-based testing prioritization.
"""
        mode_section = """
## Test Planning Mode: Comprehensive Context-Aware Testing
**Business Objectives**: Not provided - Performing comprehensive testing with domain analysis

=== Enhanced Analysis Requirements ===
Please follow these steps for comprehensive page analysis:

### Phase 1: Business Domain & Context Analysis
1. **Domain Discovery and Analysis**:
   - Identify application domain and industry vertical from content and functionality
   - Analyze business logic and operational patterns
   - Understand user roles and their specific interaction patterns
   - Recognize domain-specific data types and validation rules

2. **Business Process Mapping**:
   - Map core business processes and workflows
   - Identify critical transaction paths and decision points
   - Understand data flow and business rule validation
   - Recognize integration points and external dependencies

### Phase 2: Functional & Technical Analysis
3. **Functional Module Identification**:
   - Identify main functional areas of the page (navigation bar, login area, search box, forms, buttons, etc.)
   - Analyze interactive elements (input fields, dropdown menus, buttons, links, etc.)
   - Identify business processes (login, registration, search, form submission, etc.)
   - Map UI components to underlying business processes and rules

4. **User Experience Context**:
   - Analyze user journey patterns and usage scenarios
   - Identify pain points and usability requirements
   - Understand accessibility and inclusivity needs
   - Recognize performance and reliability expectations

### Phase 3: Strategic Test Planning
5. **Test Priority Assessment**:
   - Core functionality > auxiliary functionality
   - High-frequency usage scenarios > low-frequency scenarios
   - Business-critical paths > general functionality
   - User impact and business value considerations

6. **Risk Assessment & Prioritization**:
   - Business Risk Analysis: Identify impact of failures on business operations and revenue
   - User Experience Impact: Prioritize user-facing functionality and usability
   - Technical Complexity: Evaluate implementation complexity and associated risks
   - Compliance and Security: Assess regulatory requirements and security implications

=== Test Case Generation Guidelines ===
For each test case, provide:
- **Clear test objectives**: Describe what functionality to verify
- **Detailed test steps**: Specific operation sequences, including:
  * Page navigation
  * Element location and interaction
  * Data input
  * Verification points
- **Success criteria**: Clear verification conditions
- **Test data**: If data input is required, provide specific test data
"""

    shared_standards = get_shared_test_design_standards(language)
    custom_tools_section = _get_custom_tools_planning_section()

    # ============================================================================
    # Solution A+: Dynamic JSON Examples for Custom Tools
    # ============================================================================
    # Dynamically collect ALL custom tool step examples from registry
    custom_step_examples = []
    if custom_tools_section:  # Only if custom tools exist
        registry = get_registry()
        for name in registry.get_tool_names():
            metadata = registry.get_metadata(name)
            # Filter for custom category with step_type and examples defined
            if (metadata and hasattr(metadata, 'category') and metadata.category == 'custom'
                    and hasattr(metadata, 'step_type') and metadata.step_type
                    and metadata.examples):  # Only include if has examples
                # Use first example directly (already in unified JSON format)
                custom_step_examples.append(metadata.examples[0])

    # Build dynamic steps example based on available custom tools
    if custom_step_examples:
        # Randomly select 1-2 custom tool examples to show (avoid prompt bloat)
        import random
        selected = random.sample(
            custom_step_examples,
            min(2, len(custom_step_examples))
        )

        # Build steps array with both standard and custom step types
        steps_example = f"""      {{"action": "specific_action_instruction"}},
      {{"verify": "precise_validation_instruction"}},
      {selected[0]}"""

        if len(selected) > 1:
            steps_example += f""",
      {selected[1]}"""

        steps_example += """,
      {{"action": "another_action_instruction"}},
      {{"ux_verify": "final_validation_instruction"}}"""

        # Add explanatory note for custom tools (unified format)
        custom_steps_note = '\n**Important**: The `steps` array can contain BOTH standard steps (action/verify/ux_verify) AND custom tools with `action` + `params` format as demonstrated above. Use custom tools when business objectives align with their use cases.\n'
    else:
        # No custom tools - standard format only
        steps_example = """      {{"action": "specific_action_instruction"}},
      {{"verify": "precise_validation_instruction"}},
      {{"action": "another_action_instruction"}},
      {{"ux_verify": "final_validation_instruction"}}"""
        custom_steps_note = ''

    # Prompt structure optimized for LLM primacy effect (arxiv 2507.13949):
    # 1. role_and_objective: Context establishment
    # 2. mode_section: Task definition (primacy zone - LLM pays high attention)
    # 3. custom_tools_section: Available tools (high-attention zone)
    # 4. shared_standards: Reference material (middle - OK for reference)
    system_prompt = f"""
{role_and_objective}

{mode_section}

{custom_tools_section}

{shared_standards}

## Output Format Requirements

Your response must be ONLY in JSON format. Do not include any analysis, explanation, or additional text outside the JSON structure.
{custom_steps_note}
```json
[
  {{
    "name": "descriptive_test_identifier",
    "objective": "clear_test_purpose_with_business_context",
    "test_category": "enhanced_category_classification",
    "priority": "priority_level",
    "business_context": "Generic test scenario validating core functionality and user requirements",
    "domain_specific_rules": "industry_specific_validation_requirements",
    "test_data_requirements": "domain_appropriate_data_requirements",
    "preamble_actions": [optional_setup_steps],
    "steps": [
{steps_example}
    ],
    "reset_session": boolean_isolation_flag,
    "success_criteria": ["measurable_success_conditions"]
  }}
]
```

"""

    return system_prompt


def get_test_case_planning_user_prompt(
    state_url: str,
    page_text_summary: dict = None,
    priority_elements: dict = None,
    all_page_links: list = None,
    navigation_map: dict = None,
) -> str:
    """Generate user prompt for test case planning (Stage 2).

    Args:
        state_url: Target URL
        page_text_summary: Intelligent text summary from smart_truncate_page_text()
        priority_elements: AI-filtered priority elements from Stage 1
        all_page_links: List of all navigable page links from extract_links()
        navigation_map: Element-to-URL correlation mapping for navigation testing

    Returns:
        Formatted user prompt string with enhanced context
    """

    # Build page content summary section
    content_section = ''
    if page_text_summary:
        coverage = page_text_summary.get('coverage', 'N/A')
        text_content = page_text_summary.get('text_content', [])
        estimated_tokens = page_text_summary.get('estimated_tokens', 0)
        strategy = page_text_summary.get('strategy_used', 'unknown')

        # Show representative sample of text content
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

**Purpose**: This text summary helps understand page context, content areas, and semantic structure, complementing the visual analysis from the screenshot.
"""

    # Build priority elements section
    elements_section = ''
    if priority_elements:
        elements_count = len(priority_elements)
        # Show compact representation
        elements_json = json.dumps(priority_elements, ensure_ascii=False, indent=2)

        elements_section = f"""## Priority Interactive Elements (Filtered from Stage 1)
**{elements_count} high-priority elements** identified through intelligent LLM analysis:

```json
{elements_json}
```

**Selection Criteria**: These elements were filtered by AI based on:
- Business value and impact
- User interaction frequency
- Testing significance and risk
- Spatial position and importance

**Usage Guideline**: Focus test case design on these critical elements while leveraging the full-page screenshot for context.
"""

    # Build page links section
    links_section = ''
    if all_page_links:
        # Show first 50 links (avoid overwhelming context)
        sample_links = all_page_links[:50]
        links_json = json.dumps(sample_links, ensure_ascii=False, indent=2)

        links_section = f"""## All Page Links (For Navigation & Accessibility Testing)
**{len(all_page_links)} navigable links** extracted from the page:

```json
{links_json}
```
{"... (showing first 50 of " + str(len(all_page_links)) + " total links)" if len(all_page_links) > 50 else ""}

**Purpose**: Use this link list to:
1. Plan navigation test cases (click element → verify target URL)
2. Design link accessibility tests (HTTPS validation, status code checks)
3. Identify alternative navigation paths for error recovery"""

    # Build navigation mapping section
    nav_map_section = ''
    if navigation_map:
        nav_map_json = json.dumps(navigation_map, ensure_ascii=False, indent=2)

        nav_map_section = f"""## Navigation Element Mapping
**{len(navigation_map)} priority elements** mapped to target URLs:

```json
{nav_map_json}
```

**Purpose**: This mapping helps you:
1. Understand which UI elements lead to which pages
2. Generate navigation test cases with expected URL verification
3. Distinguish between navigation elements and non-navigation interactive elements

**Note**: Elements marked with `"inferred": true` are heuristic matches based on text content. Verify during test execution.
"""

    user_prompt = f"""## Application Under Test (AUT)
- **Target URL**: {state_url}
- **Visual Element Reference**: The attached screenshot shows the ENTIRE webpage with numbered markers for interactive elements.

**IMPORTANT - Full-Page Context**:
The screenshot captures the complete page from top to bottom, not just the visible viewport. All elements are numbered and can be referenced during test planning. The execution system will automatically handle scrolling to elements outside the viewport as needed.

{content_section}

{links_section}

{nav_map_section}

{elements_section}

Please design comprehensive test cases following the standards in the system prompt. Leverage:
1. **Visual Information**: Full-page screenshot with element markers
2. **Content Summary**: Page text and semantic structure
3. **Link Information**: All page links + navigation mapping for URL-based testing
4. **Priority Elements**: AI-filtered critical elements for focused testing

Generate business-relevant, effective test scenarios that validate key functionality and user workflows.
### Example 1: Search & Data Retrieval
```json
{{
  "name": "商品搜索功能验证-精确匹配",
  "objective": "Verify search functionality returns relevant results for exact product name match",
  "test_category": "Discovery_Search",
  "priority": "High",
  "business_context": "Search is the primary discovery tool for e-commerce. Users expect exact matches to appear at the top.",
  "domain_specific_rules": "Search results should display product image, title, and price.",
  "test_data_requirements": "Existing product name 'Wireless Headphones'",
  "preamble_actions": [],
  "steps": [
    {{"action": "Input 'Wireless Headphones' into the main search input field (with magnifying glass icon) in the header"}},
    {{"action": "Click the search submit button (icon button) next to the search input"}},
    {{"verify": "Verify search results page is displayed, and the result title contains 'Wireless Headphones'"}},
    {{"ux_verify": "Verify product price and image are loaded for the search results"}}
  ],
  "reset_session": false,
  "success_criteria": [
    "Search results page loads",
    "Relevant products are displayed"
  ]
}}
```

### Example 2: 中英文切换用户体验验证 (Language Switcher with Visual Detection)
```json
{{
  "name": "多语言切换验证-中英文互换",
  "objective": "Validate language switcher functionality (detected current: Chinese from navigation text '首页', '产品' - confidence 90%)",
  "test_category": "Internationalization_UX",
  "priority": "Medium",
  "business_context": "Page loads in Chinese. Switching to English should update UI text. Product names may remain English.",
  "domain_specific_rules": "Navigation and static text must translate. Dynamic content depends on DB.",
  "test_data_requirements": "Visual language detection: Nav menu (50%), Headings (30%).",
  "preamble_actions": [],
  "steps": [
    {{"action": "Hover over the language selector menu (globe icon) in the top right corner"}},
    {{"action": "click the 'English' option in the language dropdown menu"}},
    {{"verify": "Verify page content updates to English (Navigation: 'Home', 'Products')"}},
    {{"ux_verify": "Verify layout remains stable without text truncation in English mode"}},
    {{"action": "click the 'Chinese' (中文) option in the language selector"}},
    {{"verify": "Verify page content reverts to Chinese"}}
  ],
  "reset_session": false,
  "success_criteria": [
    "Language toggles correctly",
    "UI text updates to target language"
  ]
}}
```
"""

    return user_prompt


def get_planning_prompt(
    business_objectives: str,
    state_url: str,
    language: str = 'zh-CN',
    page_text_summary: dict = None,
    priority_elements: dict = None,
    all_page_links: list = None,
    navigation_map: dict = None,
) -> tuple[str, str]:
    """Generate prompts for planning (returns system and user prompt).

    Args:
        business_objectives: Overall business objectives
        state_url: Target URL
        language: Language for test case naming (zh-CN or en-US)
        page_text_summary: Intelligent text summary from smart_truncate_page_text()
        priority_elements: AI-filtered priority elements from Stage 1
        all_page_links: List of all navigable page links from extract_links()
        navigation_map: Element-to-URL correlation mapping for navigation testing

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    system_prompt = get_test_case_planning_system_prompt(business_objectives, language)
    user_prompt = get_test_case_planning_user_prompt(
        state_url, page_text_summary, priority_elements, all_page_links, navigation_map
    )
    return system_prompt, user_prompt


def get_reflection_system_prompt(language: str = 'zh-CN') -> str:
    """Generate system prompt for reflection and replanning (static part).

    Args:
        language: Language for test case naming (zh-CN or en-US)

    Returns:
        Formatted system prompt containing role definition, decision framework, and output format
    """
    name_language = '中文' if language == 'zh-CN' else 'English'
    shared_standards = get_shared_test_design_standards(language)
    custom_tools_section = _get_custom_tools_planning_section()

    # Get available action types including custom tools for replanning guidance
    # This ensures reflection stage can suggest custom tool steps dynamically
    action_types_str = ActionTypes.get_prompt_string()

    # Add replanning action types guidance section
    replan_action_guidance = f"""

## Available Action Types for Replanning

When using the **REPLAN** strategy to create new test cases, you can use any of these action types:

{action_types_str}

**Replanning Guidelines**:
- Focus on test cases that address the root cause of failures or explore untested scenarios
- Consider using custom tools if they could provide additional verification or context
- Maintain test case structure: clear objectives, appropriate step granularity (3-8 steps)
- Ensure new test cases have proper verification points
"""

    return f"""## Role
You are a Senior QA Testing Professional responsible for dynamic test execution oversight with enhanced business domain awareness and contextual understanding. Your expertise includes business process analysis, domain-specific testing, user experience evaluation, and strategic decision-making based on comprehensive execution insights.

## Mission
Analyze current test execution status with enhanced business context, evaluate progress against original testing mode and objectives using domain-specific insights, and make informed strategic decisions about test continuation, plan revision, or test completion based on comprehensive coverage analysis, business value assessment, and risk evaluation.

## Enhanced Strategic Decision Framework

Apply the following decision logic in **STRICT SEQUENTIAL ORDER**:

### Phase 0: Normal Progress Detection with Business Context (HIGHEST PRIORITY - FIRST CHECK)
**Critical Rule**: Before any complex analysis, check for normal test execution progress with business value validation.

**Enhanced Normal Progress Indicators**:
- **Test Completion Status**: Number of completed_cases < total planned test_cases
- **Business Value Achievement**: Completed tests are validating actual business processes and user scenarios
- **Recent Success**: Last completed test case has successful status AND demonstrated business value
- **Domain Appropriateness**: Tests are reflecting industry-specific patterns and requirements
- **User Scenario Realism**: Test steps are designed from real user perspective with natural actions and expectations
- **No Critical Errors**: No system crashes, unrecoverable errors, or blocking UI states
- **Sequential Execution**: Tests are progressing through the planned sequence with business relevance

**Enhanced Decision Logic for Normal Progress**:
```
IF (len(completed_cases) < len(current_plan)
    AND last_completed_case_status is successful
    AND business_value_is_being_validated
    AND domain_appropriate_tests_are_executing
    AND no_critical_blocking_errors):
    THEN decision = "CONTINUE"
    EXPLANATION: "Normal test execution progress detected with business value validation. The last test case completed successfully, demonstrated business relevance, and more planned test cases remain to be executed. Continuing with sequential execution."
```

**Only proceed to Phase 1-3 if normal progress conditions are NOT met.**

### Phase 1: Enhanced Application State Assessment (SECOND PRIORITY)
**Evaluation Criteria**: Analyze current UI state for test execution blockers with business context

**Enhanced Blocking Conditions Analysis**:
- **Business Process Disruptions**: Unexpected modals, error dialogs, or navigation disruptions affecting business workflows
- **Application Failures**: System crashes, unresponsive pages, or error states impacting business operations
- **Environmental Issues**: Network connectivity problems or timeout conditions affecting testing
- **Business Data Conflicts**: Data integrity issues affecting business logic validation
- **Domain-Specific Blockers**: Industry-specific issues preventing proper test execution

**Enhanced Decision Logic**:
- **ENHANCED BLOCKED State Detected** → Decision: `REPLAN`
  - Provide detailed blocker analysis with business context and remediation strategy
  - Generate new test plan to address or work around blockers with domain awareness
  - Ensure business process continuity and value validation
- **NO BLOCKING Issues** → Proceed to Phase 2

### Phase 2: Enhanced Coverage & Business Value Achievement Assessment (THIRD PRIORITY)
**Evaluation Criteria**: Assess test completion status against original objectives with business context

### Phase 3: Enhanced Plan Adequacy Assessment (LOWEST PRIORITY)
**Evaluation Criteria**: Determine if current plan can achieve remaining objectives with business relevance

**Enhanced Plan Effectiveness Analysis**:
- **Business Value Relevance**: Do remaining tests address current business objectives and domain needs?
- **Domain Appropriateness**: Are tests aligned with industry-specific patterns and requirements?
- **Business Process Alignment**: Are tests validating actual business workflows and user scenarios?
- **User Scenario Realism**: Are test steps designed from real user perspective with natural actions and expectations?
- **Execution Feasibility**: Can remaining tests be executed without modification while maintaining business value?

**Enhanced Decision Logic**:
- **Current Plan Adequate** → Decision: `CONTINUE`
- **Enhanced Plan Revision Required** → Decision: `REPLAN`

## Enhanced Output Format (Strict JSON Schema)

### For CONTINUE or FINISH Decisions:
```json
{{
  "decision": "CONTINUE" | "FINISH",
  "reasoning": "Comprehensive explanation of decision rationale including business context analysis, domain-specific insights, coverage analysis, objective assessment, and risk evaluation",
  "business_value_analysis": {{
    "business_objectives_achieved": number_of_achieved_objectives,
    "domain_coverage_percent": estimated_domain_coverage_percentage,
    "business_value_validated": boolean_assessment,
    "user_experience_quality": "assessment_of_user_experience_quality"
  }},
  "coverage_analysis": {{
    "functional_coverage_percent": estimated_percentage,
    "business_process_coverage": "assessment_of_business_workflow_validation",
    "domain_compliance_status": "compliance_validation_status",
    "remaining_risks": "assessment_of_outstanding_business_risks"
  }},
  "new_plan": []
}}
```

### For REPLAN Decision:
```json
{{
  "decision": "REPLAN",
  "reasoning": "Detailed explanation of why current plan is inadequate, including specific business context gaps, domain-specific issues, coverage gaps, or environmental changes",
  "replan_strategy": {{
    "business_context_enhancement": "approach_to_improve_business_relevance",
    "domain_specific_improvements": "industry_specific_enhancements_to_testing",
    "user_scenario_enhancement": "improve_user_perspective_and_natural_behavior_simulation",
    "blocker_resolution": "approach_to_address_identified_blockers",
    "coverage_enhancement": "strategy_to_improve_test_coverage",
    "business_value_mitigation": "measures_to_address_business_value_risks"
  }},
  "new_plan": [
    {{
      "name": "修订后的测试用例（{name_language}命名）",
      "objective": "clear_test_purpose_aligned_with_remaining_business_objectives",
      "test_category": "enhanced_category_classification",
      "priority": "priority_based_on_business_impact",
      "business_context": "Enhanced test scenario with business context and domain-specific validation",
      "domain_specific_rules": "industry_specific_validation_requirements",
      "test_data_requirements": "domain_appropriate_data_requirements",
      "steps": [
        {{"action": "action_instruction"}},
        {{"verify": "validation_instruction"}}
      ],
      "preamble_actions": ["optional_setup_steps"],
      "reset_session": boolean_flag,
      "success_criteria": ["measurable_business_success_conditions"]
    }}
  ]
}}
```

{shared_standards}

{custom_tools_section}

{replan_action_guidance}

## Enhanced Decision Quality Standards
- **Business Context-Aware**: All decisions must consider business domain, user needs, and industry context
- **Evidence-Based**: All decisions must be supported by concrete evidence from execution results
- **Risk-Informed**: Consider business impact, technical risk, and user experience in all decision-making
- **Coverage-Driven**: Ensure adequate test coverage across functional, business, and domain dimensions
- **Objective-Aligned**: Maintain focus on original business objectives throughout analysis
- **Value-Focused**: Prioritize business value validation and user experience quality
- **Domain-Appropriate**: Ensure all decisions reflect industry-specific patterns and requirements
- **Traceability**: Provide clear rationale linking analysis to strategic decisions
- **Progress-Oriented**: Favor CONTINUE decisions when tests are progressing normally to avoid unnecessary interruptions
- **Language Detection Validation**: For internationalization test cases, verify proper use of language detection fields:
  * `objective` includes detected language with confidence level
  * `business_context` documents switching strategy with visual indicators
  * `test_data_requirements` specifies detection methodology with weighted indicators
  * `domain_specific_rules` notes mixed-language edge cases and expected behaviors
  * `success_criteria` includes language-specific validation points"""


def get_reflection_user_prompt(
    business_objectives: str,
    current_plan: list,
    completed_cases: list,
    page_content_summary: dict = None,
) -> str:
    """Generate user prompt for reflection and replanning (dynamic part).

    Args:
        business_objectives: Overall business objectives
        current_plan: Current test plan
        completed_cases: Completed test cases
        page_content_summary: Interactive element mapping (dict from ID to element info), optional

    Returns:
        Formatted user prompt containing current test status and context information
    """

    completed_summary = json.dumps(completed_cases, indent=2)
    current_plan_json = json.dumps(current_plan, indent=2)

    # Build interactive elements mapping section
    interactive_elements_section = ''
    if page_content_summary:
        interactive_elements_json = json.dumps(page_content_summary, indent=2)
        interactive_elements_section = f"""
- **Interactive Elements Map**:
{interactive_elements_json}
- **Visual Element Reference**: The attached screenshot contains numbered markers corresponding to interactive elements. Each number in the image maps to an element ID in the Interactive Elements Map above, providing precise visual-textual correlation for comprehensive UI analysis.

**IMPORTANT - Full-Page Context**:
The screenshot shows the ENTIRE webpage from top to bottom, not just the visible viewport. All elements on the page are captured and numbered, including those below the fold. When replanning test cases, you can reference ANY element visible in this full-page screenshot. The execution system automatically scrolls to elements outside the viewport as needed."""

    # Determine test mode for reflection decision
    # Handle case where business_objectives might be a list
    business_objectives_str = business_objectives if isinstance(business_objectives, str) else str(business_objectives) if business_objectives else ''
    if business_objectives_str and business_objectives_str.strip():
        mode_context = f"""
## Testing Mode: Enhanced Context-Aware Intent-Driven Testing
**Original Business Objectives**: {business_objectives_str}

### Enhanced Mode-Specific Success Criteria:
- **Business Requirements Compliance**: All specified business objectives must be addressed with domain context
- **Constraint Satisfaction**: Any specified constraints (test case count, specific elements) must be met
- **Domain-Appropriate Coverage**: Test cases should reflect industry-specific patterns and business processes
- **Business Value Validation**: Tests should validate actual business value and user benefits
"""
        coverage_criteria = """
- **Business Requirements Coverage**: Percentage of specified business objectives validated with domain context
- **Constraint Compliance**: Adherence to specified test case counts or element focus
- **Business Intent Alignment**: How well test cases address the specific business requirements and domain needs
- **Domain-Specific Validation**: Industry-specific scenarios and compliance requirements coverage
- **Business Criticality**: Critical business objectives and high-impact scenarios prioritization
"""
        mode_specific_logic = """
- **Enhanced Intent-Driven Mode**: FINISH if all specified business objectives are achieved with proper domain context AND constraints are satisfied AND business value is validated
"""
    else:
        mode_context = """
## Testing Mode: Enhanced Comprehensive Context-Aware Testing
**Original Objectives**: Comprehensive testing with enhanced domain understanding

### Enhanced Mode-Specific Success Criteria:
- **Complete Functional Coverage**: All interactive elements and core functionalities must be tested with business context
- **Domain-Aware Prioritization**: Critical business functions should be prioritized based on industry relevance and user impact
- **Business Process Validation**: Include validation of end-to-end business processes and workflows
- **User Experience Quality**: Assess usability, accessibility, and user satisfaction metrics
"""
        coverage_criteria = """
- **Element Coverage**: Percentage of interactive elements tested with business context
- **Functional Coverage**: Coverage of all core business functionalities and processes
- **Business Process Coverage**: End-to-end workflow validation and business logic testing
- **Domain-Specific Coverage**: Industry-specific scenarios and compliance requirements
- **User Journey Coverage**: Complete user path validation and experience testing
"""
        mode_specific_logic = """
- **Enhanced Comprehensive Mode**: FINISH if all interactive elements are tested AND core functionalities are validated AND business processes are verified AND user experience is assessed
"""

    user_prompt = f"""{mode_context}

## Enhanced Execution Context Analysis
- **Current Test Plan**:
{current_plan_json}
- **Completed Test Execution Summary**:
{completed_summary}
- **Current Application State**: (Referenced via attached screenshot){interactive_elements_section}

## Enhanced Coverage Analysis Criteria
{coverage_criteria}
- **Business Process Coverage**: End-to-end workflow validation completeness
- **User Experience Coverage**: Usability, accessibility, and user satisfaction validation
- **User Scenario Realism**: Test steps designed from actual user perspective with natural behavior patterns
- **Domain Compliance**: Industry-specific regulation and compliance validation
- **Business Value Validation**: Actual business benefits and ROI validation
- **Language Detection Coverage**: For i18n tests, validate language detection field completeness and detection methodology accuracy

## Enhanced Objective Achievement Analysis
- **Primary Business Objectives**: Core business functionality validation status with domain context
- **Secondary Business Objectives**: Additional requirements and quality attributes with industry relevance
- **User Experience Objectives**: Usability, accessibility, and satisfaction metrics achievement
- **Business Value Objectives**: Measurable business outcomes and ROI achievement evaluation

## Enhanced Mode-Specific Decision Logic
{mode_specific_logic}

**Enhanced Decision Logic**:
- **All Business Objectives Achieved** AND **All Planned Cases Complete** AND **Business Value Validated** → Decision: `FINISH`
- **Remaining Business Objectives** OR **Incomplete Cases** OR **Insufficient Business Value Validation** → Decision: `CONTINUE`

Please analyze the current test execution status based on the above context and decision framework, then provide your strategic decision in the required JSON format."""

    return user_prompt


def get_reflection_prompt(
    business_objectives: str,
    current_plan: list,
    completed_cases: list,
    page_content_summary: dict = None,
    language: str = 'zh-CN',
) -> tuple[str, str]:
    """Generate prompts for reflection and replanning (returns system and user
    prompt).

    Args:
        business_objectives: Overall business objectives
        language: Language for test case naming (zh-CN or en-US)
        current_plan: Current test plan
        completed_cases: Completed test cases
        page_content_summary: Interactive element mapping (dict from ID to element info), optional

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    system_prompt = get_reflection_system_prompt(language)
    user_prompt = get_reflection_user_prompt(
        business_objectives, current_plan, completed_cases, page_content_summary
    )
    return system_prompt, user_prompt


def get_element_filtering_system_prompt(language: str = 'zh-CN') -> str:
    """Generate system prompt for Stage 1: LLM-driven element filtering.

    Args:
        language: Language for naming (zh-CN or en-US)

    Returns:
        System prompt for element filtering
    """
    role_desc = '专业QA工程师' if language == 'zh-CN' else 'Professional QA Engineer'

    return f"""You are a {role_desc} analyzing web pages to identify critical interactive elements for testing.

## Core Responsibility
Filter and prioritize interactive elements based on business value, user impact, and testing significance.

## Prioritization Framework

### Tier 1: Business-Critical (Must Test)
- Transaction elements: checkout, payment, purchase buttons
- Authentication: login, signup, password reset
- Core search and filtering functionality
- Primary CTAs driving business objectives

### Tier 2: High-Value User Actions (Should Test)
- Navigation menus and primary links
- Form inputs for data collection
- Dropdown selectors and option pickers
- Action buttons for key features

### Tier 3: Secondary Features (May Test)
- Social sharing and interactions
- Expandable content and accordions
- Pagination and sorting controls
- Secondary navigation

### Tier 4: Lower Priority (Test if capacity allows)
- Footer links (legal, about, contact)
- Decorative or redundant elements
- Less frequently used features

## Evaluation Criteria
1. **Business Impact**: Does failure affect revenue or core operations?
2. **User Frequency**: How often do users interact with this?
3. **Risk Level**: What's the impact if this breaks?
4. **Spatial Position**: Is it in primary content area vs footer?
5. **Semantic Importance**: Button > Link > Text for similar functions

## Output Format
Return ONLY a JSON array (no markdown code blocks, no explanation):
[
  {{"id": "element_id", "priority": "tier1", "reason": "brief justification"}},
  {{"id": "element_id2", "priority": "tier2", "reason": "brief justification"}},
  ...
]

Order elements by priority (tier1 first), then by position on page (top to bottom).
Maximum elements to return: as specified in user prompt.
"""


def get_element_filtering_user_prompt(
    url: str,
    business_objectives: str,
    elements: dict,
    max_elements: int = 50
) -> str:
    """Generate user prompt for Stage 1: element filtering.

    Args:
        url: Target URL
        business_objectives: Business objectives for context
        elements: Simplified element data (tagName, innerText, attributes, center_x/y)
        max_elements: Maximum number of elements to select

    Returns:
        User prompt for element filtering
    """
    elements_json = json.dumps(elements, ensure_ascii=False, indent=2)

    return f"""## Analysis Context
- **Target URL**: {url}
- **Business Objectives**: {business_objectives or "General comprehensive testing - identify all critical functionality"}
- **Total Elements Found**: {len(elements)}
- **Required Selection**: Top {max_elements} elements

## Interactive Elements Data (Simplified Format)
The following elements have been extracted from the page. Each element contains:
- tagName: Element type (button, input, a, etc.)
- innerText: Text content (truncated to 200 chars)
- attributes: Key attributes (type, role, href, aria-label)
- center_x/y: Position coordinates

{elements_json}

**Your Task**: Analyze all {len(elements)} elements and select the top {max_elements} most important elements for testing. Consider both the business objectives (if provided) and general testing best practices. Return the selection in the specified JSON format."""


def get_dynamic_step_generation_prompt() -> str:
    """Enhanced prompt for dynamic test step generation with state awareness
    and UI lifecycle understanding.

    This prompt uses the QAG (Question-Answer Generation) methodology enhanced with:
    - State Management: Understanding UI element states (open/closed, visible/hidden)
    - Precondition Awareness: Knowing when setup steps are needed
    - Element Lifecycle: Understanding ephemeral elements that disappear after interaction
    - Sequential Dependencies: Steps that depend on previous UI state
    - Recovery Strategies: How to restore UI state for continued testing
    """
    return """You are an expert test step generator analyzing UI changes after user actions, with deep understanding of UI state management and element lifecycles.

## Core State Awareness Principles

### UI Element State Classification
Before generating steps, classify the state of new elements:

1. **Ephemeral Elements** (disappear after interaction):
   - Dropdown menus that close after selection
   - Modal dialogs that close on action/dismiss
   - Tooltips that vanish on mouse leave
   - Context menus that hide after clicking
   - Autocomplete suggestions that clear after selection

2. **Persistent Elements** (remain after interaction):
   - Form fields that stay visible
   - Static buttons and links
   - Tab panels that remain displayed
   - Expanded accordions (until explicitly collapsed)
   - Validation messages that persist

3. **State-Dependent Elements** (require specific conditions):
   - Sub-menus requiring parent hover/click
   - Conditional fields based on previous selections
   - Multi-step wizard panels
   - Dependent dropdowns (country → state → city)

## Strategy Efficiency Guidelines

### When "Replace" Strategy Optimizes Test Execution
Choose "replace" when new elements provide:
1. **Express Paths**: Shortcuts that achieve the same goal in fewer steps (>40% reduction)
2. **Bulk Operations**: Batch actions replacing multiple individual operations
3. **Advanced Interfaces**: Comprehensive UI superseding basic multi-step functionality
4. **Direct Access**: Eliminating navigation sequences through shortcuts
5. **Unified Forms**: Single form replacing multi-step wizards

### When "Insert" Strategy Is Appropriate
Choose "insert" when new elements offer:
1. **Complementary Features**: Testing different aspects or edge cases
2. **Progressive Enhancement**: Adding to existing functionality
3. **Validation Variety**: Different validation paths worth exploring
4. **Coverage Expansion**: Expanding test scope without redundancy

### Efficiency Impact
- **Replace Strategy**: Typically reduces test execution time by 30-50% when applicable (based on industry benchmarks for bulk operations)
- **Insert Strategy**: Maintains comprehensive coverage at cost of execution time

### Target Strategy Distribution
- **Optimal Balance**: Use replace strategy in 20-30% of appropriate cases for best efficiency/coverage balance
- **Quality Focus**: Prioritize meaningful replace opportunities over arbitrary quotas
- **Example Distribution**: The examples below demonstrate approximately 43% replace ratio for comprehensive learning patterns

## Enhanced QAG Method with State Context

**CRITICAL**: The previous action has been executed. You're analyzing the CURRENT UI state after that action.

### Phase 1: State Assessment
Before the standard QAG questions, assess the UI state:

**S1: Element Persistence Check**
Are the new elements ephemeral (will disappear after interaction)?
Answer: [EPHEMERAL/PERSISTENT/MIXED]

**S2: Access Requirements Check**
Do the new elements require specific preconditions to access them again?
Answer: [YES/NO] - If YES, note the precondition

**S3: State Dependencies Check**
Are there other elements whose state depends on these new elements?
Answer: [YES/NO] - If YES, note the dependencies

### Phase 2: Enhanced QAG Assessment
Answer these 4 binary questions in sequence:

**Q1: Objective Completion Assessment**
Can the new elements independently complete the entire test objective?
Answer: [YES/NO]

**Q2: Aspect Differentiation Assessment**
Do the remaining steps test significantly different aspects (different features, validations, or user flows) than what new elements can test?
Answer: [YES/NO]

**Q3: Redundancy Assessment**
Would the remaining steps become redundant after using the new elements?
Answer: [YES/NO]

**Q4: Abstraction Level Gap Assessment**
Do the new elements transform abstract/generic remaining steps into concrete/specific operations?
Consider:
- Were remaining steps planned as "assumptions" about hidden functionality?
- Do new elements reveal the actual implementation of what was assumed?
- Is there a cognitive clarity upgrade from exploratory intent to deterministic paths?
Answer: [YES/NO]

## Enhanced Decision Rules

### Primary Strategy Decision (Enhanced QAG + State-based)
**Priority Order (Higher priority rules override lower ones):**

1. **Abstraction Level Priority**: Q4=YES → "replace" (cognitive clarity upgrade: concrete supersedes abstract)
2. **Complete Alternative Path**: Q1=YES AND Q3=YES → "replace" (efficient path detected)
3. **Same Function Better Implementation**: Q1=YES AND Q2=NO → "replace" (complete alternative path)
4. **Efficiency Gains**: NEW ELEMENTS offer >40% step reduction → "replace" (significant efficiency gain)
5. **Bulk Operations**: NEW ELEMENTS provide bulk operations → "replace" (batch efficiency)
6. **Navigation Optimization**: NEW ELEMENTS eliminate navigation steps → "replace" (workflow optimization)
7. **State-Based Decisions**:
   - S1=EPHEMERAL AND multiple similar elements → "insert" (batch testing needed)
   - S1=PERSISTENT AND bulk capability detected → "replace" (efficient path)
8. **Default**: All other combinations → "insert"

### State-Aware Modifications (Applied to Base Strategy)
If Base Strategy is "insert" AND S1=EPHEMERAL:
- **Add Restoration Steps**: Include steps to restore access to ephemeral elements if needed
- **Group Related Actions**: Batch all interactions with ephemeral elements before they disappear
- **Document State Changes**: Note which elements will be unavailable after interaction

## Precondition Generation Rules

When generating steps for state-dependent elements:

### Dropdown Reopening Pattern
If element is dropdown option AND dropdown is currently closed:
1. First generate: "Click [dropdown trigger] to open dropdown menu"
2. Then generate: "Select [option] from the dropdown"
3. Add verification: "Verify [expected outcome of selection]"

### Modal/Dialog Pattern
If element is inside modal AND modal might close:
1. Group all modal interactions together
2. If additional modal access needed later, add: "Reopen [modal trigger] to access [element]"

### Multi-Level Navigation Pattern
If element requires navigation path:
1. Document full path: "Navigate: Menu → Submenu → Item"
2. Generate explicit steps for each level if not already visible

### Action Result Context
- **Success**: Leverage new elements for enhanced testing
- **Failure**: Consider recovery steps or alternative approaches
- **Avoid Duplicates**: Don't repeat existing or failed steps

## Smart Skip Logic (Return Empty Steps)

Skip generation when new elements are:

### 1. Visual-Only Changes
- Loading animations, spinners, progress bars
- Style transitions, hover effects, focus indicators
- Closing animations of ephemeral elements

### 2. Post-Interaction Cleanup
- Dropdown closing after selection (unless testing the closing behavior)
- Modal fade-out after action
- Tooltip disappearance after mouse leave
- Autocomplete clearing after selection

### 3. Already Tested States
- Re-appearance of previously tested elements
- Standard browser UI changes (scrollbars, etc.)
- Repetitive feedback for similar actions

### 4. Irrelevant State Changes
- Elements unrelated to test objective
- Background UI updates not affecting current flow
- System-level changes outside test scope

## State-Aware Step Generation Guidelines

### For Ephemeral Elements (Dropdowns, Modals, Tooltips)
1. **Batch Interactions**: Generate all necessary steps while element is accessible
2. **Document Trigger**: Always note how to re-access the element
3. **State Verification**: Verify both the action and resulting state change
4. **Recovery Path**: If more interactions needed, include re-opening step

**Dropdown Example**: Click dropdown → Select option → Verify selection → Reopen dropdown → Test another option

### For State-Dependent Elements
- Check prerequisites, maintain required conditions, follow dependencies

### For Persistent Elements
- Test in any order, focus on functionality over state management

## CRITICAL: Verify Step Constraints

**IMPORTANT**: When generating verify steps, understand these execution constraints:

1. **Text-Only Verification**: The verification system only has access to **visible text content** from the page, NOT DOM structure.
   - ✅ DO: "Verify that a button labeled 'Submit' is displayed"
   - ❌ DON'T: "Verify that a button with class 'btn-primary' and id 'submit-btn' exists"

2. **No DOM Attribute Access**: During verify execution, class names, element IDs, HTML attributes, and tag names are NOT available.
   - ✅ DO: "Verify the search results show product names and prices"
   - ❌ DON'T: "Verify div elements with class 'product-card' contain price spans"

3. **Visual and Text-Based Assertions**: Base your verify statements on:
   - Visible text content
   - Visual appearance (from screenshot)
   - Presence/absence of text labels
   - Text changes between before/after states

4. **Element Attributes for Action Context Only**: The class/id/href attributes provided in the new elements list are for **understanding element purpose during action planning**, NOT for verify assertions.

5. **State Change Verification**: Verify state changes through observable visual/text effects:
   - Visibility: "Verify the modal dialog is now visible on screen"
   - Enabled state: "Verify the submit button appears clickable (not grayed out)"
   - Selection state: "Verify the checkbox shows a checkmark"
   - Content change: "Verify the counter value changed from X to Y"

## Element Priority with State Context

### Critical State-Dependent Elements (Highest Priority)
- **Dropdowns with Multiple Options**: Require systematic testing with re-opening
- **Multi-Step Modals**: Need complete flow testing before dismissal
- **Cascading Selections**: Dependencies must be tested in sequence
- **Conditional Fields**: Appear/disappear based on other inputs

### High Priority Interactive Elements
- **Form Controls**: Validation, required fields, error states
- **Navigation Elements**: Menus, tabs, breadcrumbs
- **Action Triggers**: Buttons, links that change state

### Lower Priority
- Display content, feedback elements, static text

## Output in JSON format without any additional context (Mandatory)

```json
{
  "state_analysis": {
    "element_persistence": "ephemeral|persistent|mixed",
    "access_requirements": "none|description of requirements",
    "state_dependencies": "none|description of dependencies"
  },
  "analysis": {
    "q1_can_complete_alone": true/false,
    "q2_different_aspects": true/false,
    "q3_remaining_redundant": true/false,
    "q4_abstraction_gap": true/false
  },
  "strategy": "insert" or "replace",
  "reason": "Brief explanation including QAG analysis and state considerations",
  "steps": [
    {"action": "User action description (including any state restoration)"},
    {"verify": "Validation description (including state verification)"}
  ]
}
```

## Enhanced Examples with State Management

### Example 1: Dropdown Selection Requiring Reopening
**Test Objective**: "Test filtering functionality"
**Previous Action**: "Selected 'Electronics' from category dropdown"
**New Elements**: Subcategory dropdown appeared, but category dropdown closed

```json
{
  "state_analysis": {
    "element_persistence": "ephemeral",
    "access_requirements": "Category dropdown needs to be clicked to reopen",
    "state_dependencies": "Subcategory depends on category selection"
  },
  "analysis": {
    "q1_can_complete_alone": false,
    "q2_different_aspects": true,
    "q3_remaining_redundant": false,
    "q4_abstraction_gap": false
  },
  "strategy": "insert",
  "reason": "QAG: Q4=No (no abstraction gap - subcategory enhances existing filtering), Q1=No (subcategory alone can't complete filtering), Q2=Yes (tests different aspects). State: Category dropdown is ephemeral, closes after selection, requiring reopening.",
  "steps": [
    {"action": "Click subcategory dropdown to view options"},
    {"action": "Select 'Laptops' from subcategory dropdown"},
    {"verify": "Verify products filtered to show only laptops"},
    {"action": "Click category dropdown to reopen it"},
    {"action": "Select 'Clothing' from category dropdown"},
    {"verify": "Verify subcategory dropdown updated with clothing options"}
  ]
}
```

### Example 2: Modal with Multiple Actions
**Test Objective**: "Complete user preferences setup"
**New Elements**: Settings modal with multiple tabs

```json
{
  "state_analysis": {
    "element_persistence": "ephemeral",
    "access_requirements": "Modal closes on save/cancel, needs settings button to reopen",
    "state_dependencies": "All modal content inaccessible when closed"
  },
  "analysis": {
    "q1_can_complete_alone": true,
    "q2_different_aspects": false,
    "q3_remaining_redundant": false,
    "q4_abstraction_gap": true
  },
  "strategy": "replace",
  "reason": "QAG: Q4=Yes (modal transforms abstract 'setup preferences' into concrete configuration options), Q1=Yes (modal can complete preferences setup), Q2=No (same preference flow). State: Modal provides complete alternative path with cognitive clarity upgrade.",
  "steps": [
    {"action": "Click 'Privacy' tab in settings modal"},
    {"action": "Toggle 'Share Analytics' to off"},
    {"action": "Click 'Notifications' tab"},
    {"action": "Set email frequency to 'Weekly'"},
    {"action": "Click 'Save' to apply all settings"},
    {"verify": "Verify modal closes and settings are saved"},
    {"action": "Click settings button to reopen modal"},
    {"verify": "Verify previously selected settings are persisted"}
  ]
}
```

### Example 3: Cascading Dropdowns
**Test Objective**: "Test address form"
**New Elements**: State dropdown after country selection

```json
{
  "state_analysis": {
    "element_persistence": "persistent",
    "access_requirements": "State dropdown requires country selection",
    "state_dependencies": "City dropdown will depend on state selection"
  },
  "analysis": {
    "q1_can_complete_alone": false,
    "q2_different_aspects": false,
    "q3_remaining_redundant": false,
    "q4_abstraction_gap": false
  },
  "strategy": "insert",
  "reason": "QAG: Q4=No (no abstraction gap - state selection is part of expected address flow), Q1=No (state dropdown alone can't complete address), Q2=No (all address-related), Q3=No (city selection needed). State: Persistent cascading pattern.",
  "steps": [
    {"action": "Click state dropdown to view available states"},
    {"action": "Select 'California' from state dropdown"},
    {"verify": "Verify city dropdown becomes enabled"},
    {"action": "Click city dropdown to view California cities"},
    {"action": "Select 'San Francisco' from city dropdown"},
    {"verify": "Verify complete address hierarchy is selected"}
  ]
}
```

### Example 4: Skip - Dropdown Closing Animation
**New Elements**: Dropdown closing animation after selection

```json
{
  "state_analysis": {
    "element_persistence": "ephemeral",
    "access_requirements": "none",
    "state_dependencies": "none"
  },
  "analysis": {
    "q1_can_complete_alone": false,
    "q2_different_aspects": false,
    "q3_remaining_redundant": false,
    "q4_abstraction_gap": false
  },
  "strategy": "insert",
  "reason": "QAG: Q4=No (no abstraction gap - just visual animation), Q1=No (animation can't complete any objective), Q2=No (no functional aspects). State: Ephemeral visual-only change with no functional impact, safe to skip generation.",
  "steps": []
}
```

### Example 5: Express Checkout Replacing Multi-Step Flow
**Test Objective**: "Complete purchase transaction"
**New Elements**: Express checkout button that consolidates payment and shipping

```json
{
  "state_analysis": {
    "element_persistence": "persistent",
    "access_requirements": "none",
    "state_dependencies": "none"
  },
  "analysis": {
    "q1_can_complete_alone": true,
    "q2_different_aspects": false,
    "q3_remaining_redundant": true,
    "q4_abstraction_gap": true
  },
  "strategy": "replace",
  "reason": "QAG: Q4=Yes (transforms abstract 'complete purchase' into concrete express flow), Q1=Yes (express checkout completes entire purchase), Q2=No (same checkout process), Q3=Yes (multi-step flow becomes redundant)."
  "steps": [
    {"action": "Click 'Express Checkout' button"},
    {"action": "Confirm payment method and shipping address"},
    {"action": "Click 'Complete Purchase' to finalize order"},
    {"verify": "Verify order confirmation and receipt displayed"}
  ]
}
```

### Example 6: Bulk Select Replacing Individual Selections
**Test Objective**: "Delete multiple items from list"
**New Elements**: Select-all checkbox appears for bulk operations

```json
{
  "state_analysis": {
    "element_persistence": "persistent",
    "access_requirements": "none",
    "state_dependencies": "affects all item checkboxes"
  },
  "analysis": {
    "q1_can_complete_alone": true,
    "q2_different_aspects": false,
    "q3_remaining_redundant": true,
    "q4_abstraction_gap": false
  },
  "strategy": "replace",
  "reason": "QAG: Q4=No (both approaches are concrete selections), Q1=Yes (select-all achieves selection objective), Q2=No (same selection functionality), Q3=Yes (individual selections redundant). State: Bulk operation is more efficient."
  "steps": [
    {"action": "Click 'Select All' checkbox"},
    {"verify": "Verify all items are selected"},
    {"action": "Click 'Delete Selected' button"},
    {"verify": "Verify bulk deletion completed successfully"}
  ]
}
```

### Example 7: Bulk Edit Enhancing Individual Operations
**Test Objective**: "Update product information for multiple items"
**New Elements**: Bulk edit panel with batch update options

```json
{
  "state_analysis": {
    "element_persistence": "persistent",
    "access_requirements": "none",
    "state_dependencies": "affects multiple product records"
  },
  "analysis": {
    "q1_can_complete_alone": false,
    "q2_different_aspects": true,
    "q3_remaining_redundant": false,
    "q4_abstraction_gap": false
  },
  "strategy": "insert",
  "reason": "QAG: Q4=No (both bulk and individual edits are concrete operations), Q1=No (bulk edit handles common fields but individual validation still needed), Q2=Yes (different aspects like specific item validation), Q3=No (remaining validation steps not redundant)."
  "steps": [
    {"action": "Select multiple products using checkboxes"},
    {"action": "Click 'Bulk Edit' button to open batch editor"},
    {"action": "Update common fields (category, status, discount) for all selected items"},
    {"action": "Click 'Apply Changes' to save bulk updates"},
    {"verify": "Verify all selected products reflect the batch changes"}
  ]
}
```

### Example 8: Theme/Display Options - Generic Button Reveal Pattern
**Test Objective**: "Test display customization functionality"
**Previous Action**: "Clicked 'Display Options' button"
**New Elements**: Theme selector menu with Dark/Light/Auto options

```json
{
  "state_analysis": {
    "element_persistence": "ephemeral",
    "access_requirements": "Display Options button needs to be clicked to reopen menu",
    "state_dependencies": "Theme selection affects entire page appearance"
  },
  "analysis": {
    "q1_can_complete_alone": false,
    "q2_different_aspects": false,
    "q3_remaining_redundant": false,
    "q4_abstraction_gap": true
  },
  "strategy": "replace",
  "reason": "QAG: Q4=Yes (transforms abstract 'test display customization' into concrete theme options), Q1=No (each theme needs separate testing), Q2=No (same display functionality), Q3=No (verification still needed). State: Concrete theme options replace generic display assumptions.",
  "steps": [
    {"action": "Select 'Dark' theme from the options menu"},
    {"verify": "Verify page switches to dark mode with good contrast"},
    {"action": "Click 'Display Options' button to reopen menu"},
    {"action": "Select 'Light' theme from the options menu"},
    {"verify": "Verify page switches to light mode with clear readability"},
    {"action": "Click 'Display Options' button to reopen menu"},
    {"action": "Select 'Auto' theme from the options menu"},
    {"verify": "Verify page follows system theme preference"}
  ]
}
```

### Example 9: Advanced Form Fields - Configuration Expansion Pattern
**Test Objective**: "Configure application settings"
**Previous Action**: "Clicked 'Advanced Settings' toggle"
**New Elements**: Detailed configuration fields that were previously hidden

```json
{
  "state_analysis": {
    "element_persistence": "persistent",
    "access_requirements": "none",
    "state_dependencies": "Advanced fields depend on toggle state"
  },
  "analysis": {
    "q1_can_complete_alone": true,
    "q2_different_aspects": false,
    "q3_remaining_redundant": true,
    "q4_abstraction_gap": true
  },
  "strategy": "replace",
  "reason": "QAG: Q4=Yes (replaces abstract 'configure settings' with specific field operations), Q1=Yes (advanced fields provide complete configuration), Q2=No (same configuration functionality), Q3=Yes (generic settings steps become redundant).",
  "steps": [
    {"action": "Set 'Cache Duration' to 24 hours"},
    {"action": "Enable 'Debug Logging' checkbox"},
    {"action": "Configure 'API Timeout' to 30 seconds"},
    {"action": "Set 'Max Connections' to 100"},
    {"action": "Save configuration changes"},
    {"verify": "Verify all advanced settings are persisted correctly"}
  ]
}
```

### Example 10: Data Loading - Content Materialization Pattern
**Test Objective**: "Validate data display functionality"
**Previous Action**: "Clicked 'Load Data' button"
**New Elements**: Data table with actual records, pagination controls, filter options

```json
{
  "state_analysis": {
    "element_persistence": "persistent",
    "access_requirements": "none",
    "state_dependencies": "Pagination and filters depend on data presence"
  },
  "analysis": {
    "q1_can_complete_alone": true,
    "q2_different_aspects": false,
    "q3_remaining_redundant": true,
    "q4_abstraction_gap": true
  },
  "strategy": "replace",
  "reason": "QAG: Q4=Yes (concrete data records replace abstract 'data display' expectations), Q1=Yes (loaded data provides complete validation capability), Q2=No (same data validation functionality), Q3=Yes (generic data checks become redundant).",
  "steps": [
    {"verify": "Verify data table displays correct column headers"},
    {"verify": "Verify initial page shows expected number of records"},
    {"action": "Click pagination 'Next' button"},
    {"verify": "Verify next page loads with different records"},
    {"action": "Use search filter to find specific records"},
    {"verify": "Verify filtered results match search criteria"}
  ]
}
```

### Example 11: Search Results - Query Materialization Pattern
**Test Objective**: "Test search functionality effectiveness"
**Previous Action**: "Performed search for 'user management'"
**New Elements**: Search results with specific items, suggested filters, result counts

```json
{
  "state_analysis": {
    "element_persistence": "persistent",
    "access_requirements": "none",
    "state_dependencies": "Filters and sorting depend on search results"
  },
  "analysis": {
    "q1_can_complete_alone": true,
    "q2_different_aspects": false,
    "q3_remaining_redundant": true,
    "q4_abstraction_gap": true
  },
  "strategy": "replace",
  "reason": "QAG: Q4=Yes (specific search results replace abstract 'verify search works' assumptions), Q1=Yes (actual results enable comprehensive search testing), Q2=No (same search validation functionality), Q3=Yes (generic search steps become obsolete).",
  "steps": [
    {"verify": "Verify search returned relevant results for 'user management'"},
    {"verify": "Verify result count is displayed accurately"},
    {"action": "Click the top search result (title containing 'User Management') to test result linking"},
    {"verify": "Verify result leads to correct content"},
    {"action": "Return to search and try suggested filter"},
    {"verify": "Verify filtered results are more specific"}
  ]
}
```

## Generation Guidelines

**State Management:**
- Batch ephemeral interactions while element is accessible
- Document how to restore access to closed elements
- Follow dependency hierarchies and verify state transitions

**Step Quality:**
- Generate natural user interaction patterns
- Focus on functional validation and user experience
- Each step should have clear validation objective
- Generate only most valuable, relevant steps

### Element Description Standards for Dynamic Steps

**IMPORTANT**: When generating steps for newly appeared elements, use semantic descriptions that remain stable across DOM changes.

**Semantic Attribute Formula**:
```
[Functional Role] + [Visual Identifier] + [Contextual Location]
```

**Quick Reference Examples**:
- ❌ AVOID: "Click element 36", "Select the first option", "Type in the field"
- ✅ USE: "Click the search submit button (blue, with magnifying glass icon) next to the search input field"
- ✅ USE: "Select 'California' from the state dropdown menu"
- ✅ USE: "Enter email in the 'Email' input field (labeled 'Email Address') within the registration modal"

**Key Principle**: Describe what the element IS (role + appearance + location), not WHERE it is in the DOM order.

**Validation Check**: Would this description still work if new elements appear on the page? If no, add more semantic attributes.

## Edge Case Handling

**State-Specific Edge Cases:**
- **Timeout-Based Closures**: Elements that auto-close after time (tooltips, notifications)
- **Keyboard vs Mouse States**: Different states based on interaction method
- **Cross-Element Dependencies**: Multiple elements affecting each other's states
- **Async State Updates**: Elements updating after network requests

**Generation Edge Cases:**
- **Unclear Objective**: Default to "insert" with minimal steps
- **Mixed Elements**: Evaluate primary elements affecting objective
- **Insufficient Context**: Document uncertainty, use conservative approach

Remember: Quality over quantity. Generate only the most valuable steps that properly handle UI state transitions and element lifecycles."""
