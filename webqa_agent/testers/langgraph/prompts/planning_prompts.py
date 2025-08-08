"""测试计划和用例生成相关的提示词模板."""

import json


def get_shared_test_design_standards() -> str:
    """获取共享的测试用例设计标准，用于plan和reflect模块复用.
    
    Returns:
        包含完整测试用例设计标准的字符串
    """
    return """## Enhanced Test Case Design Standards

### Domain-Aware Test Case Structure Requirements
Each test case must include these standardized components with enhanced business context:

- **`name`**: 简洁直观的中文测试名称，反映业务场景和测试目的
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
{{"action": "点击导航栏A"}},
{{"verify": "确认跳转到A页面"}},
{{"action": "点击导航栏B"}},
{{"verify": "确认跳转到B页面"}},
{{"action": "点击导航栏C"}},
{{"verify": "确认跳转到C页面"}}
]
```

**Search Testing - Atomic Steps**:
```json
[
{{"action": "点击搜索框"}},
{{"action": "输入搜索关键词'产品'"}},
{{"action": "点击搜索按钮"}},
{{"verify": "确认显示搜索结果列表"}}
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
{{"verify": "记录浏览器控制台中任何异常、堆栈跟踪或网络请求失败的证据（截屏并保存日志）"}},
{{"verify": "检查DOM元素的CSS属性和JavaScript事件绑定"}},
{{"verify": "验证HTTP响应状态码为200并检查响应头"}}
```

**✅ User-Scenario Verify Step (Preferred)**:
```json
{{"verify": "确认页面显示'登录成功'提示信息"}},
{{"verify": "检查是否跳转到用户主页"}},
{{"verify": "确认表单显示错误提示'请输入有效邮箱'"}}
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
) -> str:
    """生成测试用例规划的系统提示词.

    Args:
        business_objectives: 业务目标
        completed_cases: 已完成的测试用例（用于重新规划）
        reflection_history: 反思历史（用于重新规划）
        remaining_objectives: 剩余目标（用于重新规划）

    Returns:
        格式化的系统提示词字符串
    """

    # 判断是初始规划还是重新规划
    if not completed_cases:
        # 根据business_objectives是否为空决定模式
        # 处理business_objectives可能是列表的情况
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
        # 重新规划模式
        role_and_objective = """
## Role
You are a Senior QA Testing Professional performing adaptive test plan revision based on execution results, enhanced business understanding, and evolving domain context.

## Primary Objective
Leverage deeper business domain insights and execution learnings to generate refined test plans that address remaining coverage gaps while building upon successful outcomes. Ensure enhanced business relevance and domain appropriateness in all test cases.
"""
        # 重新规划时也根据business_objectives决定模式
        # 处理business_objectives可能是列表的情况
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

    shared_standards = get_shared_test_design_standards()
    
    system_prompt = f"""
{role_and_objective}

{mode_section}

{shared_standards}

## Output Format Requirements

Your response must follow this exact structure:

1. **Analysis Scratchpad**: Complete structured analysis following the QA framework
2. **JSON Test Plan**: Well-formed JSON array containing all generated test cases

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
    """生成测试用例规划的用户提示词.

    Args:
        state_url: 目标URL
        page_content_summary: 页面内容摘要（交互元素）
        page_structure: 完整的页面文本结构
        completed_cases: 已完成的测试用例（用于重新规划）
        reflection_history: 反思历史（用于重新规划）
        remaining_objectives: 剩余目标（用于重新规划）

    Returns:
        格式化的用户提示词字符串
    """

    context_section = ""
    if completed_cases:
        # 重新规划模式
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

请帮助我基于以上信息进行测试用例规划。请按照系统提示中的要求进行深入分析，并生成符合规范的测试用例。
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


def get_reflection_system_prompt() -> str:
    """生成反思和重新规划的系统提示词（静态部分）.

    Returns:
        格式化的系统提示词，包含角色定义、决策框架和输出格式
    """
    
    shared_standards = get_shared_test_design_standards()
    
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
      "name": "修订后的测试用例（中文命名）",
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
    """生成反思和重新规划的用户提示词（动态部分）.

    Args:
        business_objectives: 总体业务目标
        current_plan: 当前测试计划
        completed_cases: 已完成的用例
        page_structure: 当前UI文本结构
        page_content_summary: 可交互元素映射（ID到元素信息的字典），可选

    Returns:
        格式化的用户提示词，包含当前测试状态和上下文信息
    """

    completed_summary = json.dumps(completed_cases, indent=2)
    current_plan_json = json.dumps(current_plan, indent=2)

    # 构建交互元素映射部分
    interactive_elements_section = ""
    if page_content_summary:
        interactive_elements_json = json.dumps(page_content_summary, indent=2)
        interactive_elements_section = f"""
- **Interactive Elements Map**:
{interactive_elements_json}
- **Visual Element Reference**: The attached screenshot contains numbered markers corresponding to interactive elements. Each number in the image maps to an element ID in the Interactive Elements Map above, providing precise visual-textual correlation for comprehensive UI analysis."""

    # 确定测试模式用于反思决策
    # 处理business_objectives可能是列表的情况
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
) -> tuple[str, str]:
    """生成反思和重新规划的提示词（返回system和user prompt）.

    Args:
        business_objectives: 总体业务目标
        current_plan: 当前测试计划
        completed_cases: 已完成的用例
        page_structure: 当前UI文本结构
        page_content_summary: 可交互元素映射（ID到元素信息的字典），可选

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    system_prompt = get_reflection_system_prompt()
    user_prompt = get_reflection_user_prompt(
        business_objectives, current_plan, completed_cases, page_structure, page_content_summary
    )
    return system_prompt, user_prompt
