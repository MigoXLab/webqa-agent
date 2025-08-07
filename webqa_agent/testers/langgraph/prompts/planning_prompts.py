"""测试计划和用例生成相关的提示词模板."""

import json


def get_test_case_planning_prompt(
    state_url: str,
    business_objectives: str,
    page_content_summary: dict,
    page_structure: str,
    completed_cases: list = None,
    reflection_history: list = None,
    remaining_objectives: str = None,
) -> str:
    """生成测试用例规划的提示词.

    Args:
        state_url: 目标URL
        business_objectives: 业务目标
        page_content_summary: 页面内容摘要（交互元素）
        page_structure: 完整的页面文本结构
        completed_cases: 已完成的测试用例（用于重新规划）
        reflection_history: 反思历史（用于重新规划）
        remaining_objectives: 剩余目标（用于重新规划）

    Returns:
        格式化的提示词字符串
    """

    # 判断是初始规划还是重新规划
    if not completed_cases:
        # 根据business_objectives是否为空决定模式
        if business_objectives and business_objectives.strip():
            role_and_objective = """
## Role
You are a Senior QA Testing Professional with expertise in business domain analysis, requirement engineering, and context-aware test design. Your responsibility is to deeply understand the application's business context, domain-specific patterns, and user needs to generate highly relevant and effective test cases.

## Primary Objective
Conduct comprehensive business domain analysis and contextual understanding before generating test cases. Analyze the application's purpose, industry patterns, user workflows, and business logic to create test cases that are not only technically sound but also business-relevant and domain-appropriate.
"""
            context_section = ""
            mode_section = f"""
## Test Planning Mode: Context-Aware Intent-Driven Testing
**Business Objectives Provided**: {business_objectives}

### Enhanced Context Analysis Requirements
1. **Business Domain Understanding**:
   - Identify the industry domain (e.g., e-commerce, banking, healthcare, education)
   - Analyze business model and revenue streams (if discernible)
   - Understand user roles and their specific needs
   - Recognize domain-specific regulations and compliance requirements

2. **Application Purpose Analysis**:
   - Determine primary application purpose (informational, transactional, social, etc.)
   - Identify key user journeys and critical workflows
   - Understand the value proposition and core functionalities
   - Recognize competitive differentiators and unique features

3. **Strategic Test Planning**:
   - Generate test cases that validate both functional requirements and business objectives
   - Ensure domain-specific scenarios are covered (e.g., checkout for e-commerce, loan applications for banking)
   - Include industry-specific compliance and security validation
   - Focus on user experience and business process efficiency

4. **Requirements Compliance**:
   - Directly address all stated business objectives
   - Respect any specified constraints (test case count, specific elements)
   - Cover both positive and negative scenarios for business-critical functionalities
   - Include appropriate boundary conditions and edge cases relevant to the domain
"""
        else:
            role_and_objective = """
## Role
You are a Senior QA Testing Professional with expertise in comprehensive web application analysis and domain-aware testing. Your responsibility is to conduct deep application analysis, understand business context, and design complete test suites that ensure software quality through systematic validation of all functional, business, and domain-specific requirements.

## Primary Objective
Perform comprehensive application analysis including business domain understanding, user workflow identification, and contextual awareness before generating test cases. Apply established QA methodologies including domain-specific testing patterns, business process validation, and risk-based testing prioritization.
"""
            context_section = ""
            mode_section = """
## Test Planning Mode: Comprehensive Context-Aware Testing
**Business Objectives**: Not provided - Performing comprehensive testing with domain analysis

### Enhanced Analysis Requirements
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

3. **User Experience Context**:
   - Analyze user journey patterns and usage scenarios
   - Identify pain points and usability requirements
   - Understand accessibility and inclusivity needs
   - Recognize performance and reliability expectations

4. **Comprehensive Test Strategy**:
   - Generate test cases covering all interactive elements and core functionalities
   - Include domain-specific validation scenarios
   - Address business process integrity and data consistency
   - Prioritize based on business impact and user criticality
"""
    else:
        # 重新规划模式
        role_and_objective = """
## Role
You are a Senior QA Testing Professional performing adaptive test plan revision based on execution results, enhanced business understanding, and evolving domain context.

## Primary Objective
Leverage deeper business domain insights and execution learnings to generate refined test plans that address remaining coverage gaps while building upon successful outcomes. Ensure enhanced business relevance and domain appropriateness in all test cases.
"""
        last_reflection = reflection_history[-1] if reflection_history else {}
        context_section = f"""
## Revision Context with Enhanced Business Understanding
- **Completed Test Execution Summary**: {json.dumps(completed_cases, indent=2)}
- **Previous Reflection Analysis**: {json.dumps(last_reflection, indent=2)}
- **Remaining Coverage Objectives**: {remaining_objectives}
- **Enhanced Domain Insights**: Apply deeper business context learned from execution results
"""
        # 重新规划时也根据business_objectives决定模式
        if business_objectives and business_objectives.strip():
            mode_section = f"""
## Replanning Mode: Enhanced Context-Aware Revision
**Original Business Objectives**: {business_objectives}

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

### Enhanced Replanning Requirements
- Apply business domain insights discovered during test execution
- Address remaining untested functionalities with improved contextual understanding
- Fill coverage gaps identified from execution history with domain-appropriate tests
- Generate enhanced test cases that better reflect business processes and user needs
- Incorporate usability and user experience considerations based on learnings
"""

    prompt = f"""
{role_and_objective}

{mode_section}

## Application Under Test (AUT)
- **Target URL**: {state_url}
- **Interactive Elements Map**: {json.dumps(page_content_summary)}
- **Visual Element Reference (Referenced via attached screenshot) **: The attached screenshot contains numbered markers corresponding to interactive elements. Each number in the image maps to an element ID in the Interactive Elements Map above, providing precise visual-textual correlation for comprehensive UI analysis.
- **Complete Page Structure**: {page_structure}

{context_section}

## Enhanced QA Analysis Framework: Deep Context Understanding

### Phase 1: Business Domain & Context Analysis
Perform comprehensive business and domain analysis within an `<analysis_scratchpad>` section:

#### 1.1 Domain Identification and Business Context
- **Industry Domain Analysis**: Identify the specific industry (e.g., e-commerce, finance, healthcare, education, media)
- **Business Model Understanding**: Analyze revenue models, customer segments, and value propositions
- **User Role Identification**: Map different user types (customers, administrators, partners, etc.) and their needs
- **Regulatory Context**: Identify applicable regulations (GDPR, PCI-DSS, HIPAA, etc.) and compliance requirements

#### 1.2 Application Purpose and Value Analysis
- **Primary Purpose Classification**: Informational, transactional, social, utility, entertainment, etc.
- **Core Value Proposition**: What problem does this application solve for users?
- **Key Differentiators**: Unique features or capabilities that set this application apart
- **Success Metrics**: What indicates success for this application (conversions, engagement, efficiency, etc.)

#### 1.3 Business Process and Workflow Mapping
- **Core Business Processes**: Identify key business workflows (e.g., purchase flow, user registration, content management)
- **Data Flow Analysis**: Map how information moves through the application
- **Decision Points**: Identify critical business logic and validation points
- **External Integrations**: Recognize third-party services and APIs

#### 1.4 User Experience and Journey Analysis
- **Primary User Journeys**: Map main user paths from entry to goal completion
- **User Motivations**: Understand why users are interacting with the application
- **Success Criteria**: Define what constitutes success from the user's perspective
- **Pain Points**: Identify potential user frustrations or obstacles

### Phase 2: Functional & Technical Analysis

#### 2.1 Functional Module Identification
- **UI Component Analysis**: Examine interactive elements (forms, buttons, dropdowns, navigation) and their relationships
- **Business Logic Mapping**: Connect UI components to underlying business processes and rules
- **Integration Points**: Identify external system interactions (APIs, databases, third-party services)
- **Data Flow Analysis**: Map information flow through the application

#### 2.2 User Journey & Workflow Analysis
- **Primary User Paths**: Identify main user workflows from entry to goal completion
- **Alternative Scenarios**: Document secondary paths and edge cases
- **Error Scenarios**: Anticipate failure points and error handling requirements
- **User Role Considerations**: Account for different user types and permission levels

#### 2.3 Test Coverage Planning
- **Functional Coverage**: Ensure all business requirements are testable
- **UI Coverage**: Validate all interactive elements and their states
- **Data Coverage**: Test with various data types, formats, and boundary conditions
- **Domain Coverage**: Include industry-specific scenarios and validation rules

#### 2.4 Risk Assessment & Prioritization
- **Business Risk Analysis**: Identify impact of failures on business operations and revenue
- **User Experience Impact**: Prioritize user-facing functionality and usability
- **Technical Complexity**: Evaluate implementation complexity and associated risks
- **Compliance and Security**: Assess regulatory requirements and security implications
- **Functional Criticality Assessment**: 
  - **Core Function Analysis**: Identify essential business functions vs. auxiliary features
  - **Transaction Criticality**: Assess revenue impact and operational dependencies
  - **User Journey Impact**: Evaluate importance in user workflows and task completion
  - **Usage Frequency Analysis**: Consider high-traffic vs. rarely used features
  - **Workflow Dependency**: Map prerequisite relationships and functionality dependencies

### Phase 3: Strategic Test Case Design
Generate test cases following established QA design patterns with enhanced business relevance.

## Enhanced Test Case Design Standards

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
  - `action`: User-scenario action instructions describing what a real user would do in natural language
  - `verify`: User-expectation validation instructions describing what result a real user would expect to see
- **`preamble_actions`**: Optional setup steps to establish required test preconditions
- **`reset_session`**: Session management flag for test isolation strategy
- **`success_criteria`**: Measurable, verifiable conditions that define test pass/fail status
- **`cleanup_requirements`**: Post-test cleanup actions if needed

### Navigation Optimization Guidelines
**IMPORTANT**: To avoid redundant navigation operations:

1. **When `reset_session=true`**:
   - The system will automatically navigate to the target URL before test execution
   - Do NOT include navigation steps in the `steps` array (e.g., "Navigate to homepage")
   - Only include navigation in `preamble_actions` if you need to navigate to a different page within the same domain

2. **When `reset_session=false`**:
   - Navigation steps can be included in `steps` if needed
   - Use `preamble_actions` for setup navigation to specific test states

3. **Smart Navigation Detection**:
   - Navigation instructions include: "navigate", "go to", "open", "visit", "browse", "load", "导航", "打开", "访问", "跳转", "前往"
   - URL patterns like "https://", "www.", ".com", etc. are also considered navigation
   - The system will automatically skip redundant navigation when already on the target page

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

### Test Environment Considerations
- **Test Isolation**: Each test case should be independent and repeatable
- **State Management**: Clear definition of required initial conditions
- **Cleanup Strategy**: Proper test data and session cleanup procedures

### Atomic Step Decomposition Principle
**CRITICAL**: Every test step must represent a single, atomic UI interaction that can be executed independently. This ensures test reliability and prevents execution failures.

#### Step Decomposition Rules:
1. **One Action Per Step**: Each step in the `steps` array must contain ONLY ONE action or ONE verification
2. **No Compound Instructions**: Never combine multiple UI interactions in a single step
3. **Sequential Operations**: Multiple operations on the same or different elements must be separated into distinct steps
4. **State Management**: Each step should account for potential page state changes after execution

#### Correct vs Incorrect Examples:

**❌ INCORRECT - Compound Instructions:**
```json
[
{{"action": "依次点击链接A、B、C验证导航功能"}},
{{"verify": "验证所有链接都能正常跳转到对应页面"}}
]
```

**✅ CORRECT - Atomic Steps:**
```json
[
{{"action": "点击链接A"}},
{{"verify": "验证成功跳转到A页面"}},
{{"action": "返回主页面"}},
{{"action": "点击链接B"}},
{{"verify": "验证成功跳转到B页面"}},
{{"action": "返回主页面"}},
{{"action": "点击链接C"}},
{{"verify": "验证成功跳转到C页面"}}
]
```

**❌ INCORRECT - Multiple Operations:**
```json
[
{{"action": "填写用户名和密码，然后点击登录按钮"}},
{{"verify": "验证登录成功并跳转到首页"}}
]
```

**✅ CORRECT - Sequential Steps:**
```json
[
{{"action": "在用户名输入框中输入testuser"}},
{{"verify": "验证用户名输入正确显示"}},
{{"action": "在密码输入框中输入TestPass123!"}},
{{"verify": "验证密码以掩码形式正确显示"}},
{{"action": "点击登录按钮"}},
{{"verify": "验证登录成功并跳转到首页"}}
]
```

**❌ INCORRECT - Complex Navigation Instructions:**
```json
[
{{"action": "打开并点击导航栏中的所有菜单项"}},
{{"verify": "验证所有菜单项功能正常"}}
]
```

**✅ CORRECT - Individual Navigation Steps:**
```json
[
{{"action": "点击导航栏中的首页菜单项"}},
{{"verify": "验证成功跳转到首页"}},
{{"action": "点击导航栏中的产品菜单项"}},
{{"verify": "验证成功跳转到产品页面"}},
{{"action": "点击导航栏中的联系我们菜单项"}},
{{"verify": "验证成功跳转到联系页面"}}
]
```

#### Complex Pattern Detection:
Watch for these patterns that indicate step splitting is needed:
- **Multiple action verbs**: "点击A和B", "填写X和Y", "打开并点击"
- **Sequential indicators**: "依次", "然后", "之后", "next", "then"
- **Multiple target elements**: "链接A、B、C", "fields X, Y, Z"
- **Compound operations**: "fill form and submit", "navigate and click"

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

**Technical Step (Avoid)**:
```json
{{"action": "Enter valid email address 'testuser@example.com' in the email field"}}
{{"verify": "Verify email validation passes without error messages"}}
```

**User-Scenario Step (Preferred)**:
```json
{{"action": "Type your email address in the signup form like you normally would"}}
{{"verify": "See that the form accepts your email and doesn't show any error messages"}}
```

**Technical Step (Avoid)**:
```json
{{"action": "Click the submit button to create the record"}}
{{"verify": "Verify the record is persisted in the database"}}
```

**User-Scenario Step (Preferred)**:
```json
{{"action": "Click the submit button to finish creating your account"}}
{{"verify": "See the confirmation message showing your account was successfully created"}}
```

## Core Test Scenario Templates & Patterns

### Pattern 1: User Authentication & Core Workflows
**Core Business Function Template - Covers registration, login, and critical business processes**

```json
{{
  "name": "用户认证功能验证-注册和登录流程",
  "objective": "Validate user authentication workflows including registration and login processes",
  "test_category": "Security_Functional",
  "priority": "Critical",
  "business_context": "User authentication is fundamental to application security, user experience, and business operations. This template covers the core authentication workflows that enable user access and personalized experiences.",
  "functional_criticality": "Critical - Essential for security, user access, and all business transactions",
  "domain_specific_rules": "Authentication security standards, session management, credential validation",
  "test_data_requirements": "Valid credentials, test user accounts, unique identifiers",
  "preamble_actions": [],
  "steps": [
    {{"action": "Find and click the sign-up or registration button to start account creation"}},
    {{"action": "Fill in the registration form with your information like you normally would"}},
    {{"action": "Submit the registration form to create your account"}},
    {{"verify": "See confirmation that your account was created successfully"}},
    {{"action": "Locate the login form and sign in with your new credentials"}},
    {{"verify": "Verify you're logged in and can access your personal dashboard"}}
  ],
  "reset_session": true,
  "success_criteria": [
    "User registration process completes successfully",
    "Authentication system validates credentials correctly",
    "User is properly authenticated and granted appropriate access",
    "Session management works correctly"
  ],
  "cleanup_requirements": "Remove test user account and clean up session data"
}}
```

### Pattern 2: Form Validation & Error Handling
**Universal Interaction Template - Applicable to all forms and data input scenarios**

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
  ]
}}
```

### Pattern 3: Search & Data Retrieval
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
    {{"action": "Locate the search box or search interface"}},
    {{"action": "Enter a common search term related to the content"}},
    {{"action": "Start the search and observe the process"}},
    {{"verify": "See loading indicators while search is processing"}},
    {{"verify": "Notice search results appear that match your query"}},
    {{"verify": "See result count and any additional search options"}},
    {{"action": "Try searching with unclear or ambiguous terms"}},
    {{"action": "Test search filters or advanced options if available"}},
    {{"verify": "Verify the system handles various input types gracefully"}}
  ],
  "reset_session": true,
  "success_criteria": [
    "Search functionality processes various input types correctly",
    "Loading states provide appropriate user feedback",
    "Search results are relevant to the query terms",
    "System handles edge cases and ambiguous queries gracefully"
  ]
}}
```

### Pattern 4: Data Management (CRUD Operations)
**Data Operations Template - Covers create, read, update, delete operations**

```json
{{
  "name": "数据管理操作-CRUD功能验证",
  "objective": "Validate core data management operations including creation, modification, and deletion",
  "test_category": "Functional_Data",
  "priority": "High",
  "business_context": "Data management operations are fundamental to most business applications, enabling users to create, manage, and maintain information. This template covers the essential CRUD operations.",
  "functional_criticality": "High - Essential for business operations and data integrity",
  "domain_specific_rules": "Data validation rules, integrity constraints, business logic",
  "test_data_requirements": "Valid test data, unique identifiers, modification values",
  "preamble_actions": [
    {{"action": "Navigate to the data management interface"}}
  ],
  "steps": [
    {{"action": "Initiate creation of a new data entry"}},
    {{"action": "Fill in required fields with appropriate test data"}},
    {{"action": "Save or submit the new entry"}},
    {{"verify": "See confirmation that the entry was created successfully"}},
    {{"verify": "Locate and verify the new entry in the list or table"}},
    {{"action": "Modify the newly created entry to test updates"}},
    {{"action": "Save the changes and verify they are applied"}},
    {{"verify": "Confirm the modifications are reflected correctly"}},
    {{"action": "Delete the test entry following proper deletion process"}},
    {{"verify": "Verify the entry is removed and no longer accessible"}}
  ],
  "reset_session": true,
  "success_criteria": [
    "Data creation works correctly with proper validation",
    "Data updates are applied and persisted accurately",
    "Data deletion works with proper confirmation and cleanup",
    "Data integrity is maintained throughout all operations"
  ],
  "cleanup_requirements": "Ensure all test data is properly removed and system is restored to clean state"
}}
```

## Template Usage Guidelines

### Core Principles
1. **Adaptability**: These templates are designed to be flexible and adaptable to different application contexts
2. **Combinability**: Templates can be combined to cover complex workflows
3. **Extensibility**: Build upon these core patterns for application-specific scenarios
4. **User-Centric**: All steps should be designed from the user's perspective

### Template Selection Strategy
- **Pattern 1**: Use for any authentication, user management, or critical business workflows
- **Pattern 2**: Use for all forms, data input, validation, and error handling scenarios
- **Pattern 3**: Use for search, filtering, data retrieval, and information discovery features
- **Pattern 4**: Use for data creation, modification, deletion, and management operations

### Customization Guidelines
1. **Business Context**: Adapt the business_context to match the specific application domain
2. **Domain Rules**: Update domain_specific_rules with industry-specific requirements
3. **Test Data**: Modify test_data_requirements based on actual data needs
4. **Steps**: Adjust steps to match the specific user workflow while maintaining user-scenario approach
5. **Success Criteria**: Tailor success criteria to the specific business requirements

## Output Format Requirements

Your response must follow this exact structure:

1. **Analysis Scratchpad**: Complete structured analysis following the QA framework
2. **JSON Test Plan**: Well-formed JSON array containing all generated test cases

### Required Enhanced Output Structure:
```
<analysis_scratchpad>
**1. Business Domain & Context Analysis:**
[Detailed analysis of industry domain, business model, user roles, and regulatory context]

**2. Application Purpose & Value Analysis:**
[Analysis of primary purpose, value proposition, key differentiators, and success metrics]

**3. Business Process & Workflow Mapping:**
[Mapping of core business processes, data flow, decision points, and external integrations]

**4. User Experience & Journey Analysis:**
[Analysis of user journeys, motivations, success criteria, and potential pain points]

**5. Functional Module Identification:**
[Detailed analysis of UI components, business logic, integration points, and data flow]

**6. User Journey & Workflow Analysis:**
[Analysis of primary and alternative user paths, error scenarios, and user role considerations]

**7. Test Coverage Planning:**
[Coverage strategy across functional, UI, data, and domain dimensions]

**8. Risk Assessment & Prioritization:**
[Risk analysis including business impact, user experience, technical complexity, compliance, and functional criticality]

**9. Test Case Generation Strategy:**
[Approach for test case selection with enhanced business relevance, domain appropriateness, and functional prioritization]
</analysis_scratchpad>

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

## Enhanced Quality Assurance Standards
- **Business Relevance**: Ensure all test cases map to specific business processes and user scenarios
- **Domain Appropriateness**: Generate test cases that reflect industry-specific patterns and requirements
- **Contextual Awareness**: Consider application purpose, user motivations, and business context
- **Completeness**: Ensure comprehensive coverage of identified requirements and domain scenarios
- **Traceability**: Each test case must trace back to specific business objectives and domain requirements
- **Maintainability**: Design tests that can be easily updated as the application evolves
- **Reliability**: Create stable tests that produce consistent results across executions
- **Efficiency**: Balance thorough testing with practical execution time constraints
- **Compliance**: Include industry-specific regulatory and compliance validation where applicable
"""

    return prompt


def get_reflection_prompt(
    business_objectives: str,
    current_plan: list,
    completed_cases: list,
    page_structure: str,
    page_content_summary: dict = None,
) -> str:
    """生成反思和重新规划的提示词.

    Args:
        business_objectives: 总体业务目标
        current_plan: 当前测试计划
        completed_cases: 已完成的用例
        page_structure: 当前UI文本结构
        page_content_summary: 可交互元素映射（ID到元素信息的字典），可选

    Returns:
        格式化的反思提示词
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
    if business_objectives and business_objectives.strip():
        mode_context = f"""
## Testing Mode: Enhanced Context-Aware Intent-Driven Testing
**Original Business Objectives**: {business_objectives}

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

    prompt = f"""
## Role
You are a Senior QA Testing Professional responsible for dynamic test execution oversight with enhanced business domain awareness and contextual understanding. Your expertise includes business process analysis, domain-specific testing, user experience evaluation, and strategic decision-making based on comprehensive execution insights.

## Mission
Analyze current test execution status with enhanced business context, evaluate progress against original testing mode and objectives using domain-specific insights, and make informed strategic decisions about test continuation, plan revision, or test completion based on comprehensive coverage analysis, business value assessment, and risk evaluation.

{mode_context}

## Enhanced Execution Context Analysis
- **Current Test Plan**:
{current_plan_json}
- **Completed Test Execution Summary**:
{completed_summary}
- **Current Application State**: (Referenced via attached screenshot){interactive_elements_section}
- **Current UI Text Structure**:
{page_structure}

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

**Enhanced Coverage Analysis**:
{coverage_criteria}- **Business Process Coverage**: End-to-end workflow validation completeness
- **User Experience Coverage**: Usability, accessibility, and user satisfaction validation
- **User Scenario Realism**: Test steps designed from actual user perspective with natural behavior patterns
- **Domain Compliance**: Industry-specific regulation and compliance validation
- **Business Value Validation**: Actual business benefits and ROI validation

**Enhanced Objective Achievement Analysis**:
- **Primary Business Objectives**: Core business functionality validation status with domain context
- **Secondary Business Objectives**: Additional requirements and quality attributes with industry relevance
- **User Experience Objectives**: Usability, accessibility, and satisfaction metrics achievement
- **Business Value Objectives**: Measurable business outcomes and ROI achievement evaluation

**Enhanced Mode-Specific Decision Logic**:
{mode_specific_logic}

**Enhanced Decision Logic**:
- **All Business Objectives Achieved** AND **All Planned Cases Complete** AND **Business Value Validated** → Decision: `FINISH`
- **Remaining Business Objectives** OR **Incomplete Cases** OR **Insufficient Business Value Validation** → Decision: `CONTINUE`

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
      "steps": [
        {{"action": "action_instruction"}},
        {{"verify": "validation_instruction"}}
      ],
      "reset_session": boolean_flag,
      "success_criteria": ["measurable_business_success_conditions"]
    }}
  ]
}}
```

### Atomic Step Decomposition Principle for Replanning
**CRITICAL**: When generating new test cases during replanning, apply the same atomic step                                                                                  
decomposition rules:

1. **One Action Per Step**: Each step must contain ONLY ONE action or verification                                                                                          
2. **Decompose Complex Instructions**: Break down compound operations into individual steps                                                                                 
3. **State Management**: Consider page state changes between steps
4. **Sequential Execution**: Maintain clear execution order

**Examples for Replanning Context**:
❌ **Avoid**: `{{"action": "点击多个导航链接测试页面跳转"}}`
✅ **Use**: 
```json
[
{{"action": "点击第一个导航链接"}},
{{"verify": "验证页面跳转成功"}},
{{"action": "返回主页面"}},
{{"action": "点击第二个导航链接"}},
{{"verify": "验证页面跳转成功"}}
]
```

## Enhanced Test Case Design Standards for Replanning

### Navigation Optimization Guidelines for Enhanced Replanning
**IMPORTANT**: When generating new test cases during replanning, apply the same navigation optimization rules with business context:

1. **When `reset_session=true`**:
   - The system will automatically navigate to the target URL before test execution
   - Do NOT include navigation steps in the `steps` array (e.g., "Navigate to homepage")
   - Only include navigation in `preamble_actions` if you need to navigate to a different page within the same domain

2. **When `reset_session=false`**:
   - Navigation steps can be included in `steps` if needed
   - Use `preamble_actions` for setup navigation to specific test states

3. **Smart Navigation Detection**:
   - Navigation instructions include: "navigate", "go to", "open", "visit", "browse", "load", "导航", "打开", "访问", "跳转", "前往"
   - URL patterns like "https://", "www.", ".com", etc. are also considered navigation
   - The system will automatically skip redundant navigation when already on the target page

### Enhanced Session Management Considerations
- **reset_session=true**: Use for test isolation, when you need a clean browser state for business-critical tests
- **reset_session=false**: Use for continuous testing, when you want to maintain state between related business processes
- **Mixed Strategies**: You can generate both types of test cases in the same plan as needed based on business workflow requirements

### Enhanced Business Context Integration
- **Business Process Continuity**: Ensure test cases maintain business workflow integrity
- **Domain-Specific Validation**: Include industry-specific validation rules and compliance requirements
- **User Experience Focus**: Consider usability, accessibility, and user satisfaction in all test cases
- **User Scenario Realism**: Design test steps from real user perspective with natural actions and expectations
- **Business Value Alignment**: Ensure each test case validates specific business value and user benefits

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
"""

    return prompt
