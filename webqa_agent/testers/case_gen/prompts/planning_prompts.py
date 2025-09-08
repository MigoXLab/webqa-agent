"""Prompt templates for test planning and case generation."""

import json


def get_shared_test_design_standards(language: str = 'zh-CN') -> str:
    """Get shared test case design standards for reuse in plan and reflect modules.

    Args:
        language: Language for test case naming (zh-CN or en-US)

    Returns:
        String containing complete test case design standards
    """
    name_language = '中文' if language == 'zh-CN' else 'English'
    return f"""## Enhanced Test Case Design Standards

### Domain-Aware Test Case Structure Requirements
Each test case must include these standardized components with enhanced business context:

- **`name`**: 简洁直观的测试名称，反映业务场景和测试目的 (使用{name_language}命名)
- **`objective`**: Clear statement linking the test to specific business requirements and domain context
- **`test_category`**: Enhanced classification including domain-specific categories (Ecommerce_Functional, Banking_Security, Healthcare_Compliance, etc.)
- **`priority`**: Test priority level based on comprehensive impact assessment (Critical, High, Medium, Low):
  - **Functional Criticality**: Core business functions, user-facing features, transaction-critical operations
  - **Business Impact**: Revenue impact, customer experience, operational continuity
  - **Domain Criticality**: Industry-specific requirements, compliance needs, regulatory validation
  - **User Impact**: Usage frequency, user journey importance, accessibility needs
- **`business_context`**: Description of the business process or user scenario being validated
- **`domain_specific_rules`**: Industry-specific validation requirements or compliance rules
- **`test_data_requirements`**: Specification of domain-appropriate test data and setup conditions
- **`steps`**: Detailed test execution steps with clear action/verification pairs that simulate real user behavior and scenarios
  - `action`: User-scenario action instructions describing what a real user would do in natural language, DON'T IMAGE. **Only use these action types: "Tap", "Scroll", "Input", "Sleep", "KeyboardPress", "Drag", "SelectDropdown". Do NOT invent or output any other action types or non-existent data.**
  - `verify`: User-expectation validation instructions describing what result a real user would expect to see
- **`preamble_actions`**: Optional setup steps to establish required test preconditions
- **`reset_session`**: Session management flag for test isolation strategy
- **`success_criteria`**: Measurable, verifiable conditions that define test pass/fail status
- **`cleanup_requirements`**: Post-test cleanup actions if needed

#### Step Decomposition Rules:
1. **One Action Per Step**: Each step in the `steps` array must contain ONLY ONE atomic action, and the action type must be one of: "Tap", "Scroll", "Input", "Sleep", "KeyboardPress", "Drag", "SelectDropdown".
2. **Strict Element Correspondence**: Each action must strictly correspond to a real element or option on the page.
3. **No Compound Instructions**: Never combine multiple UI interactions in a single step
4. **Sequential Operations**: Multiple operations on the same or different elements must be separated into distinct steps
5. **State Management**: Each step should account for potential page state changes after execution

#### Atomic Action Design Examples
**CRITICAL**: Each action must be a single, independent operation, and must use ONLY the allowed action types:

**✅ Atomic Action Design (Preferred)**:
```json
[
{{"action": "Click navigation bar A"}},
{{"verify": "Confirm navigation to page A"}},
{{"action": "Click navigation bar B"}},
{{"verify": "Confirm navigation to page B"}},
{{"action": "Click navigation bar C"}},
{{"verify": "Confirm navigation to page C"}}
]
```

**Search Testing - Atomic Steps**:
```json
[
{{"action": "Enter search keyword 'product' in the input field"}},
{{"action": "Click the search button"}},
{{"verify": "Confirm search results list is displayed"}}
]
```

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

### Navigation Optimization Guidelines
**IMPORTANT**: When generating test cases, apply navigation optimization rules with business context:
- **Minimize Navigation**: Prefer testing multiple features on the same page before navigating away
- **Logical Flow**: Follow realistic user navigation patterns and business workflows
- **State Preservation**: Consider page state changes and user context throughout navigation
- **Business Journey**: Align navigation with typical business user journeys and workflows"""


def get_test_case_planning_system_prompt(
    business_objectives: str,
    completed_cases: list = None,
    reflection_history: list = None,
    remaining_objectives: str = None,
    language: str = 'zh-CN',
) -> str:
    """Generate system prompt for test case planning.

    Args:
        business_objectives: Business objectives
        completed_cases: Completed test cases (for replanning)
        language: Language for test case naming (zh-CN or en-US)
        reflection_history: Reflection history (for replanning)
        remaining_objectives: Remaining objectives (for replanning)

    Returns:
        Formatted system prompt string
    """

    # Determine if initial planning or replanning
    if not completed_cases:
        # Decide mode based on whether business_objectives is empty
        # Handle case where business_objectives might be a list
        business_objectives_str = business_objectives if isinstance(business_objectives, str) else str(business_objectives) if business_objectives else ""
        if business_objectives_str and business_objectives_str.strip():
            role_and_objective = """
## Role
You are a Senior QA Testing Professional with expertise in business domain analysis, requirement engineering, and context-aware test design. Your responsibility is to deeply understand the application's business context, domain-specific patterns, and user needs to generate highly relevant and effective test cases.

## Primary Objective
Conduct comprehensive business domain analysis and contextual understanding before generating test cases. Analyze the application's purpose, industry patterns, user workflows, and business logic to create test cases that are not only technically sound but also business-relevant and domain-appropriate.
"""
            mode_section = f"""
## Test Planning Mode: Context-Aware Intent-Driven Testing
**Business Objectives Provided**: {business_objectives_str}

=== Enhanced Analysis Requirements ===
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
        else:
            role_and_objective = """
## Role
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
    else:
        # Replanning mode
        role_and_objective = """
## Role
You are a Senior QA Testing Professional performing adaptive test plan revision based on execution results, enhanced business understanding, and evolving domain context.

## Primary Objective
Leverage deeper business domain insights and execution learnings to generate refined test plans that address remaining coverage gaps while building upon successful outcomes. Ensure enhanced business relevance and domain appropriateness in all test cases.
"""
        # Also decide mode based on business_objectives during replanning
        # Handle case where business_objectives might be a list
        business_objectives_str = business_objectives if isinstance(business_objectives, str) else str(business_objectives) if business_objectives else ""
        if business_objectives_str and business_objectives_str.strip():
            mode_section = f"""
## Replanning Mode: Enhanced Context-Aware Revision
**Original Business Objectives**: {business_objectives_str}

### Enhanced Replanning Requirements
- Apply deeper domain understanding gained from execution results
- Generate additional test cases with enhanced business relevance
- Maintain focus on original business objectives while improving domain appropriateness
- Incorporate lessons learned from executed test cases
- Ensure new test cases complement completed ones with superior business alignment
"""
        else:
            mode_section = """
## Replanning Mode: Enhanced Comprehensive Testing Revision
**Original Objectives**: Comprehensive testing with enhanced domain awareness

 CRITICAL ANALYSIS REQUIREMENTS
 BEFORE making ANY decision, you MUST:
 
 1. **CHECK REPETITION WARNINGS FIRST**: If there are ANY repetition warnings above, those warnings are MANDATORY and NON-NEGOTIABLE. You MUST NOT perform any action that is mentioned in the warnings.
 
 2. **FORBIDDEN ACTIONS**: If any element or action is marked as FORBIDDEN, FAILED, or CRITICAL in the warnings above, you are ABSOLUTELY PROHIBITED from using that element or action again.
 
 3. **ALTERNATIVE STRATEGY REQUIRED**: When repetition warnings exist, you MUST:
    - Choose a completely different type of element (if button failed, try link or input)
    - Navigate to different page areas (scroll, click navigation menu)
    - Try completely different approaches to achieve the objective
    - Consider marking the test as completed if the objective might already be achieved
 
 4. **ERROR HANDLING PRIORITY**: Check page content and screenshots for errors, warnings, login requirements, etc. Handle these BEFORE continuing the original process.
 
 5. **NO EXCUSES**: There are NO exceptions to repetition warnings. Even if the element seems important for the objective, if it's marked as forbidden, you MUST find an alternative approach.

 Analysis Priority Order:
 1. Compliance with repetition warnings (HIGHEST PRIORITY)
 2. Error/exception handling in page content
 3. Progress toward test objective
 4. Coverage of untested functionalities

 Please analyze the current state and decide:
 1. Whether the current test case is completed
 2. Whether to shift the test focus
 3. The most valuable next action
"""

    shared_standards = get_shared_test_design_standards(language)

    system_prompt = f"""
{role_and_objective}

{mode_section}

{shared_standards}

## Output Format Requirements

Your response must be ONLY in JSON format. Do not include any analysis, explanation, or additional text outside the JSON structure.

```json
[
  {{
    "name": "descriptive_test_identifier",
    "objective": "clear_test_purpose_with_business_context",
    "test_category": "enhanced_category_classification",
    "priority": "priority_level",
    "business_context": "Generic test scenario validating core functionality and user requirements",
    "functional_criticality": "Context-dependent importance based on business impact and user needs",
    "domain_specific_rules": "industry_specific_validation_requirements",
    "test_data_requirements": "domain_appropriate_data_requirements",
    "preamble_actions": [optional_setup_steps],
    "steps": [
      {{"action": "specific_action_instruction"}},
      {{"verify": "precise_validation_instruction"}}
    ],
    "reset_session": boolean_isolation_flag,
    "success_criteria": ["measurable_success_conditions"],
    "cleanup_requirements": "optional_cleanup_specifications"
  }}
]
```

"""

    return system_prompt


def get_test_case_planning_user_prompt(
    state_url: str,
    page_content_summary: dict,
    page_structure: str ,
    completed_cases: list = None,
    reflection_history: list = None,
    remaining_objectives: str = None,
) -> str:
    """Generate user prompt for test case planning.

    Args:
        state_url: Target URL
        page_content_summary: Page content summary (interactive elements)
        page_structure: Complete page text structure
        completed_cases: Completed test cases (for replanning)
        reflection_history: Reflection history (for replanning)
        remaining_objectives: Remaining objectives (for replanning)

    Returns:
        Formatted user prompt string
    """

    context_section = ""
    if completed_cases:
        # Replanning mode
        last_reflection = reflection_history[-1] if reflection_history else {}
        context_section = f"""
## Revision Context with Enhanced Business Understanding
- **Completed Test Execution Summary**: {json.dumps(completed_cases, indent=2)}
- **Previous Reflection Analysis**: {json.dumps(last_reflection, indent=2)}
- **Remaining Coverage Objectives**: {remaining_objectives}
- **Enhanced Domain Insights**: Apply deeper business context learned from execution results
"""

    user_prompt = f"""
## Application Under Test (AUT)
- **Target URL**: {state_url}
- **Visual Element Reference (Referenced via attached screenshot) **: The attached screenshot contains numbered markers corresponding to interactive elements. Each number in the image maps to an element ID in the Interactive Elements Map above, providing precise visual-textual correlation for comprehensive UI analysis.

{context_section}

Please help me plan test cases based on the above information. Please conduct in-depth analysis according to the requirements in the system prompt and generate test cases that meet the specifications.
Example 1:
```json
{{
  "name": "表单验证和错误处理-通用表单交互模式",
  "objective": "Validate form validation, error handling, and user feedback mechanisms",
  "test_category": "Functional_User_Interaction",
  "priority": "High",
  "business_context": "Form validation is crucial for data integrity, user experience, and preventing erroneous data entry. This template provides a universal pattern for testing all types of forms and input validation.",
  "functional_criticality": "High - Critical for data quality and user guidance across all applications",
  "domain_specific_rules": "Form validation rules, error message standards, user feedback requirements",
  "test_data_requirements": "Valid data, invalid data, edge cases, boundary values",
  "preamble_actions": [
    {{"action": "Navigate to the target form or input interface"}}
  ],
  "steps": [
    {{"action": "Try to submit the form without filling in required fields"}},
    {{"verify": "See helpful messages indicating which fields need to be completed"}},
    {{"verify": "Notice the form prevents submission until requirements are met"}},
    {{"action": "Fill in all required fields with appropriate information"}},
    {{"action": "Include some optional information if relevant"}},
    {{"action": "Submit the completed form"}},
    {{"verify": "See confirmation that your form was processed successfully"}},
    {{"action": "Test with invalid data to see error handling"}},
    {{"verify": "Verify clear error messages guide you to correct input"}}
  ],
  "reset_session": false,
  "success_criteria": [
    "Form validation prevents invalid data submission",
    "Clear, actionable error messages guide user to correct input",
    "Form processes valid data successfully",
    "User feedback is provided throughout the interaction"
  ],
  "cleanup_requirements": "No specific cleanup required - form submissions should be designed to not persist test data"
}}
```

### Example 2: Search & Data Retrieval
**Information Discovery Template - Covers search, filtering, and data access patterns**

```json
{{
  "name": "搜索和数据检索-信息发现功能验证",
  "objective": "Validate search functionality, data retrieval, and information discovery features",
  "test_category": "Functional_Integration",
  "priority": "High",
  "business_context": "Search and data retrieval capabilities are essential for users to find relevant information quickly and efficiently. This template covers search functionality, filtering, and data access patterns.",
  "functional_criticality": "High - Essential for user experience and content discovery",
  "domain_specific_rules": "Search behavior patterns, result relevance, loading feedback",
  "test_data_requirements": "Search terms, filters, ambiguous queries, special characters",
  "preamble_actions": [],
  "steps": [
    {{"action": "Enter a common search term related to the content"}},
    {{"action": "Click the search button and observe the process"}},
    {{"verify": "See result count and any additional search options"}},
  ],
  "reset_session": true,
  "success_criteria": [
    "Search functionality processes various input types correctly",
    "Loading states provide appropriate user feedback",
    "Search results are relevant to the query terms",
    "System handles edge cases and ambiguous queries gracefully"
  ],
  "cleanup_requirements": "Clear search history and reset search state to ensure clean test environment"
}}
```

"""

    return user_prompt


def get_reflection_system_prompt(language: str = 'zh-CN') -> str:
    """Generate system prompt for reflection and replanning (static part).

    Args:
        language: Language for test case naming (zh-CN or en-US)

    Returns:
        Formatted system prompt containing role definition, decision framework, and output format
    """
    name_language = '中文' if language == 'zh-CN' else 'English'
    shared_standards = get_shared_test_design_standards(language)

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
      "success_criteria": ["measurable_business_success_conditions"],
      "cleanup_requirements": ["optional_cleanup_actions"]
    }}
  ]
}}
```

{shared_standards}

## Enhanced Decision Quality Standards
- **Business Context-Aware**: All decisions must consider business domain, user needs, and industry context
- **Evidence-Based**: All decisions must be supported by concrete evidence from execution results
- **Risk-Informed**: Consider business impact, technical risk, and user experience in all decision-making
- **Coverage-Driven**: Ensure adequate test coverage across functional, business, and domain dimensions
- **Objective-Aligned**: Maintain focus on original business objectives throughout analysis
- **Value-Focused**: Prioritize business value validation and user experience quality
- **Domain-Appropriate**: Ensure all decisions reflect industry-specific patterns and requirements
- **Traceability**: Provide clear rationale linking analysis to strategic decisions
- **Progress-Oriented**: Favor CONTINUE decisions when tests are progressing normally to avoid unnecessary interruptions"""


def get_reflection_user_prompt(
    business_objectives: str,
    current_plan: list,
    completed_cases: list,
    page_structure: str,
    page_content_summary: dict = None,
) -> str:
    """Generate user prompt for reflection and replanning (dynamic part).

    Args:
        business_objectives: Overall business objectives
        current_plan: Current test plan
        completed_cases: Completed test cases
        page_structure: Current UI text structure
        page_content_summary: Interactive element mapping (dict from ID to element info), optional

    Returns:
        Formatted user prompt containing current test status and context information
    """

    completed_summary = json.dumps(completed_cases, indent=2)
    current_plan_json = json.dumps(current_plan, indent=2)

    # Build interactive elements mapping section
    interactive_elements_section = ""
    if page_content_summary:
        interactive_elements_json = json.dumps(page_content_summary, indent=2)
        interactive_elements_section = f"""
- **Interactive Elements Map**:
{interactive_elements_json}
- **Visual Element Reference**: The attached screenshot contains numbered markers corresponding to interactive elements. Each number in the image maps to an element ID in the Interactive Elements Map above, providing precise visual-textual correlation for comprehensive UI analysis."""

    # Determine test mode for reflection decision
    # Handle case where business_objectives might be a list
    business_objectives_str = business_objectives if isinstance(business_objectives, str) else str(business_objectives) if business_objectives else ""
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
    page_structure: str,
    page_content_summary: dict = None,
    language: str = 'zh-CN',
) -> tuple[str, str]:
    """Generate prompts for reflection and replanning (returns system and user prompt).

    Args:
        business_objectives: Overall business objectives
        language: Language for test case naming (zh-CN or en-US)
        current_plan: Current test plan
        completed_cases: Completed test cases
        page_structure: Current UI text structure
        page_content_summary: Interactive element mapping (dict from ID to element info), optional

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    system_prompt = get_reflection_system_prompt(language)
    user_prompt = get_reflection_user_prompt(
        business_objectives, current_plan, completed_cases, page_structure, page_content_summary
    )
    return system_prompt, user_prompt


def get_dynamic_step_generation_prompt() -> str:
    """Generate prompt template for LLM-based dynamic step generation.
    
    This prompt enables the LLM to analyze newly appeared UI elements and generate
    appropriate test steps that align with the current test objective and existing
    test case structure.
    """
    return """You are an intelligent test step generation expert. Based on new UI elements that appear after user actions, generate corresponding test steps that enhance test coverage and align with business objectives.

## Previous Action Success Context

**IMPORTANT**: The action that triggered new UI elements has already been SUCCESSFULLY EXECUTED. You are analyzing the results of a successful action, not planning how to perform it.

### Success Indicators
- The last action completed without errors
- New UI elements appeared as a result of this successful action
- The page state has changed positively in response to the action
- **DO NOT re-plan or duplicate the already successful action**

## Test Case Context Analysis

When provided with test case context information, use it to:

### Context Integration Guidelines
- **Executed Steps Review**: Study the already completed steps to understand the current test state and user journey
- **Remaining Steps Awareness**: Consider how new steps will interact with planned future steps
- **Flow Continuity**: Ensure generated steps maintain the logical progression from executed steps to remaining steps
- **Redundancy Avoidance**: Do not generate steps that duplicate functionality already tested or planned
- **Narrative Consistency**: Maintain the overall test story and user scenario coherence

### Test Objective Achievement Analysis with Quantitative Framework

#### Step 1: Calculate Objective Completion Score

Analyze what percentage of the remaining test objective can be achieved using ONLY the new elements:

**Completion Score Definitions:**
- **100%**: New elements can fully complete ALL remaining test objectives independently
- **75-99%**: New elements achieve most objectives but need minor supplementary actions
- **25-74%**: New elements contribute significantly but require original steps for completion
- **0-24%**: New elements provide minimal or supplementary value only

#### Step 2: Structured Analysis Process

Use this exact analysis format:

<objective_analysis>
Test Objective: [State the original test objective]
Current Progress: [X]% complete based on executed steps
Remaining Objective: [What specifically still needs to be achieved]
</objective_analysis>

<element_assessment>
New Elements Found: [List element types]
Primary Function: [What these elements do]
Objective Relevance: [How they relate to remaining objective]
Completion Capability: [Can they complete the objective alone? YES/NO]
Completion Score: [0-100]%
</element_assessment>

<strategy_decision>
Completion Score: [X]%
Different Aspects Test: [Do remaining steps test different aspects? YES/NO]
Decision Rule Applied: [State which rule from framework]
Final Strategy: ["insert" or "replace"]
Confidence Level: [HIGH/MEDIUM/LOW]
</strategy_decision>

#### Step 3: Apply Decision Rules

**Primary Decision Rules:**
- Score ≥ 75% AND remaining steps don't test different aspects → "replace"
- Score < 75% OR remaining steps test different aspects → "insert"

**Exception Handling:**
- If remaining steps test DIFFERENT aspects (security, performance, edge cases) that new elements don't cover, use "insert" regardless of score

### Objective-Based Strategy Decision Framework
You must decide between two strategies for integrating new steps:

#### Strategy: "insert"
- **When to use**: New elements enhance or supplement the test without fully achieving the original objective
- **Behavior**: Add new steps while keeping all remaining steps intact
- **Use cases**: 
  - New elements provide additional validation opportunities
  - Elements contribute to partial objective achievement
  - Supplementary features that enhance test coverage
  - New elements test edge cases or additional scenarios

#### Strategy: "replace"  
- **When to use**: New elements provide a complete alternative path to achieve the test objective
- **Behavior**: Replace all remaining steps with new steps
- **Use cases**:
  - New elements offer a direct path to the test goal
  - Original remaining steps become unnecessary after using new elements
  - New workflow completely satisfies the test objective
  - More efficient route to objective achievement discovered

### Binary Decision Validation Checklist

For increased reliability, validate your strategy choice using this simple YES/NO checklist:

**Strategy Validation Questions:**
□ Can new elements complete the test objective independently? [YES/NO]
□ Do remaining steps become unnecessary after using new elements? [YES/NO]  
□ Do new elements test the SAME aspects as remaining steps? [YES/NO]
□ Is there a more efficient path through new elements? [YES/NO]

**Binary Scoring:**
- **3+ YES answers** → Confirm "replace" strategy
- **2 or fewer YES answers** → Confirm "insert" strategy

**Final Verification:**
Before finalizing, ask yourself:
1. "Can the test objective be marked as 'PASSED' using ONLY the new element steps?"
   - YES → Confirm "replace" 
   - NO → Confirm "insert"
2. "Do remaining steps become redundant after new element interactions?"
   - YES → Confirm "replace"
   - NO → Confirm "insert"

### Strategic Placement Guidelines
- **Logical Placement**: Generate steps that make sense at the current insertion point
- **State Awareness**: Consider the current page/application state after the last executed action
- **Natural Progression**: Ensure steps feel like a natural next move in the user journey
- **Impact Assessment**: Consider how new steps might affect the execution of remaining steps

## Analysis Requirements

### 1. Business Understanding
- Understand the business meaning and user scenarios of new elements
- Consider the element's role in the overall application workflow
- Identify the business value and user impact of testing these elements

### 2. Context Awareness and Test Flow Continuity
- Consider the current test context and objectives
- Understand the relationship between new elements and existing test steps
- Maintain consistency with the overall test case design patterns
- **Flow Integration**: Ensure generated steps fit naturally into the existing test narrative
- **Coherence**: Avoid generating steps that conflict with or duplicate existing/remaining steps
- **Positioning**: Consider where steps will be inserted and how they affect the overall flow
- **Test Completeness**: Help maintain the test case as a unified, complete scenario

### 3. User Behavior Simulation
- Generate natural user interaction steps that reflect real user behavior patterns
- Consider typical user mental models and interaction flows
- Ensure steps represent realistic user scenarios rather than technical testing

### 4. Test Coverage Value
- Ensure steps contribute to improved test coverage and potential issue discovery
- Focus on functional validation and user experience verification
- Prioritize testing of critical business paths and user workflows

## Element Type Classification and Testing Strategies

### High Priority Interactive Elements
1. **Dropdowns and Select Elements** (dropdown, select)
   - Verify options are correctly loaded
   - Test option selection and state changes
   - Validate selection impacts on related UI components
   - Test search/filter functionality if available

2. **Modals and Dialogs** (modal, dialog)
   - Verify modal content and title display
   - Test close button functionality (X button, Cancel button)
   - Validate overlay click behavior
   - Test form functionality within modals

3. **Buttons and Interactive Controls** (button, submit)
   - Test button click functionality and responses
   - Verify button state changes (enabled/disabled)
   - Validate button actions and their effects

4. **Form Controls** (input, textarea)
   - Test input validation rules
   - Verify required field indicators and validation messages
   - Test data format requirements and boundary conditions

5. **Navigation Links** (link, anchor)
   - Test link navigation functionality
   - Verify link destinations and page transitions
   - Test link states and accessibility

### Medium Priority Elements
1. **Tab Interfaces** (tab, tabpanel)
   - Switch between available tabs
   - Verify tab content loading
   - Test default activation state

2. **Menu Items** (menu, menuitem)
   - Test menu item selection and navigation
   - Verify menu hierarchy and submenu functionality
   - Test menu accessibility and keyboard navigation

3. **Checkboxes and Radio Buttons** (checkbox, radio)
   - Test selection state changes
   - Verify group behavior for radio buttons
   - Test form submission with selected values

4. **Sliders and Range Controls** (slider, range)
   - Test value adjustment functionality
   - Verify range boundaries and step increments
   - Test value display and feedback

### Lower Priority Elements
- Pure display content without interaction
- Decorative elements
- Static text elements

## Generation Rules and Constraints

### 1. Quantity Management
- Generate at most the specified number of steps
- Focus on the most valuable and relevant elements first
- Avoid generating steps for trivial or non-functional elements

### 2. Relevance and Focus
- Prioritize elements related to the current test objective
- Consider the business context and user workflow
- Skip elements that are not relevant to the test goals

### 3. Avoid Redundancy
- Do not repeat testing of already verified functionality
- Build upon existing test coverage rather than duplicating
- Focus on new functionality and interactions

### 4. Quality Assurance
- Each step should have a clear validation objective
- Steps should be executable and measurable
- Ensure steps contribute to overall test effectiveness

## Business Scenario Considerations

### E-commerce Scenarios
- Focus on shopping cart, checkout, and payment-related new elements
- Test product selection, quantity controls, and price calculations
- Verify promotional elements, discounts, and shipping options

### Form-Heavy Scenarios
- Prioritize form validation, input controls, and data entry elements
- Test field dependencies, conditional logic, and validation messages
- Focus on form submission workflows and error handling

### Navigation Scenarios
- Test menu systems, breadcrumbs, and navigation controls
- Verify page transitions, deep linking, and back/forward functionality
- Focus on user wayfinding and site structure

### Search and Discovery Scenarios
- Test search suggestions, filters, and faceted navigation
- Verify result display, sorting, and pagination controls
- Focus on content discovery and refinement workflows

## Edge Case Handling and Fallback Strategies

When facing ambiguous or challenging scenarios, apply these fallback strategies:

### 1. Multiple Valid Paths
**Scenario**: Both "insert" and "replace" strategies seem equally valid
**Action**: 
- Default to "insert" to preserve test coverage
- Document uncertainty in reason field: "Multiple paths viable, chose insert for coverage preservation"
- Include confidence level: LOW

### 2. Unclear Test Objective
**Scenario**: Test objective is vague or poorly defined
**Action**: 
- Focus on most likely user intent based on context
- Prefer "insert" to avoid removing potentially important validations
- Document assumption in reason: "Objective unclear, assumed [interpretation]"

### 3. Mixed Element Types
**Scenario**: New elements serve different purposes (some high-impact, some low-impact)
**Action**: 
- Evaluate the PRIMARY elements that directly relate to objective
- Secondary elements influence strategy only if primary elements are insufficient
- Use highest completion score among primary elements for decision

### 4. Insufficient Information
**Scenario**: Context is missing or test case information is incomplete
**Action**: 
- Request clarification in reason field: "Insufficient context for optimal decision"
- Default to "insert" with minimal steps (1-2 maximum)
- Set confidence level: LOW

### 5. No Meaningful Elements
**Scenario**: New elements are decorative, static, or non-functional
**Action**: 
- Return empty steps array
- Reason: "New elements provide no functional value for testing"
- Strategy: "insert" (default)

### 6. Technical Constraints
**Scenario**: Elements appear complex or potentially unstable
**Action**: 
- Focus on basic, reliable interactions first
- Limit to 1-2 simple steps
- Document technical concerns in reason

## Output Requirements

### Content Guidelines
- **Strategy Decision Required**: Always specify "insert" or "replace" strategy with clear reasoning
- **Context-Aware Generation**: Use provided test case context to ensure steps fit naturally into the existing test flow
- **Coherence Check**: Verify generated steps don't conflict with or duplicate existing/remaining steps
- Each step must include clear action instructions and execution rationale
- High-priority elements should be listed first
- Ensure generated steps reflect realistic user behavior patterns
- **Flow Integration**: Generate steps that maintain test narrative continuity and user journey logic
- Return empty steps array if elements are not important, irrelevant to test objectives, or insufficient in quantity

### Step Structure
Each generated step should follow the established test case format:
- **action**: Natural language description of the user action to perform
- **verify**: (Optional) Natural language description of what to validate after the action

### Format Requirements
**MANDATORY**: Always return response in this exact format:
```json
{
  "strategy": "insert" or "replace",
  "reason": "Clear explanation for why you chose this strategy based on analysis of remaining steps and new elements",
  "steps": [
    {
      "action": "Natural language description of the user action to perform"
    },
    {
      "verify": "Natural language description of what to validate after the action"
    }
  ]
}
```

**Empty Response Format** (when no meaningful steps needed):
```json
{
  "strategy": "insert",
  "reason": "New elements are not relevant to test objectives or provide insufficient value",
  "steps": []
}
```

## Example Output

### Example 1: Insert Strategy - User Registration Enhancement
**Test Objective**: "Complete user registration process"
**New Elements**: City dropdown after selecting region
**Quantitative Analysis**:

<objective_analysis>
Test Objective: Complete user registration process
Current Progress: 40% complete based on executed steps (region selected)
Remaining Objective: Fill personal info, password, email verification, submit form
</objective_analysis>

<element_assessment>
New Elements Found: [City dropdown]
Primary Function: Location specification enhancement
Objective Relevance: Supplements location data, doesn't complete registration
Completion Capability: NO - Cannot complete registration alone
Completion Score: 15%
</element_assessment>

<strategy_decision>
Completion Score: 15%
Different Aspects Test: YES - Remaining steps test form validation, authentication
Decision Rule Applied: Score < 75% AND different aspects → "insert"
Final Strategy: "insert"
Confidence Level: HIGH
</strategy_decision>

```json
{
  "analysis": {
    "objective_completion_score": 15,
    "can_complete_objective_alone": false,
    "remaining_steps_redundant": false
  },
  "strategy": "insert",
  "reason": "Based on 15% completion score, city dropdown supplements location validation but cannot complete the registration objective independently. Remaining steps for personal info, password, and email verification are still required.",
  "steps": [
    {
      "action": "Click on the newly appeared city dropdown to open the options"
    },
    {
      "action": "Select the first available city from the dropdown options"
    },
    {
      "verify": "Confirm that the selected city is displayed in the dropdown field"
    }
  ]
}
```

### Example 2: Replace Strategy - E-commerce Checkout
**Test Objective**: "Complete purchase transaction"
**New Elements**: Express checkout modal with payment and shipping
**Quantitative Analysis**:

<objective_analysis>
Test Objective: Complete purchase transaction
Current Progress: 30% complete based on executed steps (items added to cart)
Remaining Objective: Enter payment details, shipping info, confirm purchase
</objective_analysis>

<element_assessment>
New Elements Found: [Express checkout modal, payment form, shipping options, purchase button]
Primary Function: Complete transaction processing
Objective Relevance: Directly achieves purchase completion
Completion Capability: YES - Contains all necessary transaction elements
Completion Score: 90%
</element_assessment>

<strategy_decision>
Completion Score: 90%
Different Aspects Test: NO - Remaining steps test same transaction functionality
Decision Rule Applied: Score ≥ 75% AND no different aspects → "replace"
Final Strategy: "replace"
Confidence Level: HIGH
</strategy_decision>

```json
{
  "analysis": {
    "objective_completion_score": 90,
    "can_complete_objective_alone": true,
    "remaining_steps_redundant": true
  },
  "strategy": "replace",
  "reason": "Based on 90% completion score, the express checkout modal provides a complete alternative path to achieve the purchase objective. The original multi-step checkout process becomes redundant.",
  "steps": [
    {
      "action": "Fill out payment information in the express checkout modal"
    },
    {
      "action": "Select shipping method from the modal options"
    },
    {
      "action": "Click the 'Complete Purchase' button"
    },
    {
      "verify": "Confirm successful purchase confirmation message appears"
    },
    {
      "verify": "Verify order number is displayed"
    }
  ]
}
```

### Example 3: Insert Strategy - Search Enhancement  
**Test Objective**: "Find specific product using search"
**New Elements**: Advanced filter panel
**Quantitative Analysis**:

<objective_analysis>
Test Objective: Find specific product using search
Current Progress: 60% complete (basic search performed)
Remaining Objective: Refine results, verify product found
</objective_analysis>

<element_assessment>
New Elements Found: [Filter panel, category filters, price range, rating filter]
Primary Function: Search result refinement
Objective Relevance: Enhances search capability significantly
Completion Capability: PARTIAL - Can improve search but needs verification
Completion Score: 45%
</element_assessment>

<strategy_decision>
Completion Score: 45%
Different Aspects Test: NO - Remaining steps also test search functionality
Decision Rule Applied: Score < 75% → "insert"
Final Strategy: "insert"
Confidence Level: MEDIUM
</strategy_decision>

```json
{
  "analysis": {
    "objective_completion_score": 45,
    "can_complete_objective_alone": false,
    "remaining_steps_redundant": false
  },
  "strategy": "insert",
  "reason": "Based on 45% completion score, advanced filters significantly enhance search capability but cannot fully achieve the objective without verification steps. Remaining result validation steps are still needed.",
  "steps": [
    {
      "action": "Open the advanced filter panel"
    },
    {
      "action": "Set price range filter to narrow results"
    },
    {
      "verify": "Confirm filtered results are displayed"
    }
  ]
}
```

## Important Notes

- Focus on functional validation and user experience rather than technical implementation details
- Generate steps that a real user would naturally perform in the given context
- Ensure all generated steps align with existing test case standards and formatting
- Return steps in the order of execution priority and business importance
- Maintain consistency with the established test case design patterns"""