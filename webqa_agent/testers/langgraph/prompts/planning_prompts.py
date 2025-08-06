"""
测试计划和用例生成相关的提示词模板
"""
import json


def get_test_case_planning_prompt(
    state_url: str,
    business_objectives: str,
    page_content_summary: dict,
    page_structure: str,
    completed_cases: list = None,
    reflection_history: list = None,
    remaining_objectives: str = None
) -> str:
    """
    生成测试用例规划的提示词
    
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
You are a Senior QA Test Architect with expertise in requirement analysis and targeted test design. Your responsibility is to analyze business objectives and generate precise test cases that directly address specified requirements.

## Primary Objective
Analyze the provided business objectives and generate a focused test plan that validates specific requirements, user scenarios, or functionality as explicitly requested. Apply intent recognition to understand the scope and depth of testing needed based on the business objectives.
"""
            context_section = ""
            mode_section = f"""
## Test Planning Mode: Intent-Driven Testing
**Business Objectives Provided**: {business_objectives}

### Intent Analysis Requirements
1. **Specific Requirements Identification**: Parse the business objectives to identify:
   - Number of test cases required (if specified)
   - Specific web elements or components to focus on
   - Testing scope limitations or priorities
   - Special validation requirements or acceptance criteria

2. **Requirements Compliance**: Ensure generated test cases:
   - Directly address all stated business objectives
   - Respect any specified constraints (e.g., number of test cases, specific elements)
   - Cover both positive and negative scenarios for the stated requirements
   - Include appropriate boundary conditions and edge cases

3. **Test Case Selection Strategy**:
   - If test case count is specified: Generate exactly that number of comprehensive test cases
   - If specific elements mentioned: Focus testing primarily on those elements
   - If "test all elements" specified: Include comprehensive coverage of all interactive elements
   - Otherwise: Generate focused test cases that best achieve the stated objectives
"""
        else:
            role_and_objective = """
## Role
You are a Senior QA Test Architect with expertise in comprehensive web application testing. Your responsibility is to design complete test suites that ensure software quality through systematic validation of all functional requirements, user workflows, and quality assurance requirements.

## Primary Objective
Analyze the target web application and generate a complete test plan that provides thorough coverage of all core functionalities, user scenarios, and quality assurance requirements. Apply established QA methodologies including equivalence partitioning, boundary value analysis, and risk-based testing prioritization.
"""
            context_section = ""
            mode_section = """
## Test Planning Mode: Comprehensive Testing
**Business Objectives**: Not provided - Performing comprehensive testing

### Coverage Requirements
1. **Complete Functional Coverage**: Generate test cases for all interactive elements and core functionalities
2. **User Journey Testing**: Include end-to-end workflows for major user paths
3. **Risk-Based Prioritization**: Focus on critical business functions and high-impact scenarios
4. **Quality Assurance**: Include validation, error handling, and edge case testing

### Test Case Generation Strategy
- Analyze all interactive elements in the page_content_summary
- Generate comprehensive test cases covering all major functionalities
- Include appropriate mix of positive, negative, and boundary test scenarios
- Prioritize test cases based on business impact and usage frequency
"""
    else:
        # 重新规划模式
        role_and_objective = """
## Role
You are a Senior QA Test Architect performing dynamic test plan revision based on execution results and changing requirements.

## Primary Objective
Based on the execution history, reflection analysis, and current application state, generate a revised test plan that addresses remaining coverage gaps while building upon successful test outcomes. Ensure the new plan provides logical continuation from completed test activities.
"""
        last_reflection = reflection_history[-1] if reflection_history else {}
        context_section = f"""
## Revision Context
- **Completed Test Execution Summary**: {json.dumps(completed_cases, indent=2)}
- **Previous Reflection Analysis**: {json.dumps(last_reflection, indent=2)}
- **Remaining Coverage Objectives**: {remaining_objectives}
"""
        # 重新规划时也根据business_objectives决定模式
        if business_objectives and business_objectives.strip():
            mode_section = f"""
## Replanning Mode: Intent-Driven Revision
**Original Business Objectives**: {business_objectives}

### Replanning Requirements
- Maintain focus on original business objectives while addressing execution gaps
- Generate additional test cases that specifically target unmet requirements
- Respect any original constraints (test case count, element focus, etc.)
- Ensure new test cases complement completed ones for full coverage
"""
        else:
            mode_section = """
## Replanning Mode: Comprehensive Testing Revision
**Original Objectives**: Comprehensive testing of all functionalities

### Replanning Requirements
- Address remaining untested functionalities and interactive elements
- Fill coverage gaps identified from execution history
- Ensure comprehensive validation of all core business functions
- Generate additional test cases for areas needing further validation
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

## QA Analysis Framework: Chain-of-Thought Process

### Step 1: Requirements Analysis & Test Scope Definition
Perform comprehensive analysis within an `<analysis_scratchpad>` section using the structured approach below:

#### 1.1 Functional Module Identification
- **UI Component Analysis**: Examine interactive elements (forms, buttons, dropdowns, navigation) and their relationships
- **Business Logic Mapping**: Connect UI components to underlying business processes
- **Integration Points**: Identify external system interactions (APIs, databases, third-party services)
- **Data Flow Analysis**: Map information flow through the application

#### 1.2 User Journey & Workflow Analysis  
- **Primary User Paths**: Identify main user workflows from entry to goal completion
- **Alternative Scenarios**: Document secondary paths and edge cases
- **Error Scenarios**: Anticipate failure points and error handling requirements
- **User Role Considerations**: Account for different user types and permission levels

#### 1.3 Test Coverage Planning
- **Functional Coverage**: Ensure all business requirements are testable
- **UI Coverage**: Validate all interactive elements and their states
- **Data Coverage**: Test with various data types, formats, and boundary conditions
- **Browser/Platform Coverage**: Consider cross-platform compatibility requirements

#### 1.4 Risk Assessment & Prioritization
- **High-Risk Areas**: Identify critical business functions and failure-prone components
- **Impact Analysis**: Assess potential business impact of component failures
- **Technical Complexity**: Evaluate implementation complexity and associated risks
- **User Experience Impact**: Prioritize user-facing functionality and usability

### Step 2: Test Case Design & Generation
Generate test cases following established QA design patterns and industry best practices.

## Test Case Design Standards

### Test Case Structure Requirements
Each test case must include these standardized components:

- **`name`**: 简洁直观的中文测试名称，让用户能够直接了解测试内容
- **`objective`**: Clear statement of what business requirement or technical aspect is being validated
- **`test_category`**: Classification (Functional, UI, Integration, Negative, Boundary, etc.)
- **`priority`**: Test priority level (Critical, High, Medium, Low) based on risk assessment
- **`test_data_requirements`**: Specification of required test data and setup conditions
- **`steps`**: Detailed test execution steps with clear action/verification pairs
  - `action`: Action instructions with specific, measurable activities
  - `verify`: Validation instructions with precise success criteria
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

### Scenario-Specific Test Data Guidelines
- **Authentication Testing**: Use valid/invalid credential pairs, test accounts with different permission levels
- **Search Functionality**: Use realistic search terms, ambiguous queries, and special characters. Search engines should return results for any input.
- **Form Validation**: Test with valid data, empty fields, oversized input, special characters, and format violations
- **File Operations**: Use various file formats, size limits, and naming conventions. Include valid and invalid file types.
- **Data Operations**: Use unique test data to avoid conflicts, include special characters and unicode in text fields
- **Pagination**: Test with data sets that span multiple pages, empty pages, and single page scenarios

### Test Environment Considerations
- **Test Isolation**: Each test case should be independent and repeatable
- **State Management**: Clear definition of required initial conditions
- **Cleanup Strategy**: Proper test data and session cleanup procedures
- **Cross-browser Compatibility**: Consider different browser behaviors and standards

## Test Scenario Templates & Patterns

### Pattern 1: User Registration/Authentication Flow
```json
{{
  "name": "用户注册功能验证-有效凭据",
  "objective": "Validate successful user registration with valid credentials and proper system response",
  "test_category": "Functional_Critical",
  "priority": "High",
  "test_data_requirements": "Valid email format, password meeting complexity requirements, unique username",
  "preamble_actions": [],
  "steps": [
    {{"action": "Navigate to the registration form by clicking the 'Sign Up' button"}},
    {{"action": "Enter valid email address 'testuser@example.com' in the email field"}},
    {{"action": "Enter secure password 'TestPass123!' in the password field"}},
    {{"action": "Enter matching password in the confirm password field"}},
    {{"action": "Click the 'Create Account' button to submit registration"}},
    {{"verify": "Verify successful registration confirmation message is displayed"}},
    {{"verify": "Verify user is redirected to welcome or dashboard page"}}
  ],
  "reset_session": true,
  "success_criteria": [
    "Registration form accepts valid input without validation errors",
    "Account creation confirmation is displayed to user",
    "User is successfully authenticated and redirected to appropriate page"
  ],
  "cleanup_requirements": "Remove test user account from system"
}}
```

### Pattern 2: Form Validation & Error Handling (reset_session=false)
```json
{{
  "name": "表单验证-必填字段为空时的错误处理",
  "objective": "Validate proper error handling and user feedback for incomplete form submissions",
  "test_category": "Negative_Testing",
  "priority": "Medium",
  "test_data_requirements": "Empty or invalid data for required fields",
  "preamble_actions": [
    {{"action": "Navigate to the target form page"}}
  ],
  "steps": [
    {{"action": "Attempt to submit form with required fields left empty"}},
    {{"verify": "Verify appropriate validation messages appear for each required field"}},
    {{"verify": "Verify form submission is prevented until all required fields are completed"}},
    {{"action": "Fill in all required fields with valid data"}},
    {{"action": "Submit the completed form"}},
    {{"verify": "Verify successful form submission and appropriate success feedback"}}
  ],
  "reset_session": false,
  "success_criteria": [
    "Form validation prevents submission with incomplete data",
    "Clear, actionable error messages guide user to correct input",
    "Form submits successfully once all validation requirements are met"
  ]
}}
```

### Pattern 3: Form Validation with Session Reset (reset_session=true)
```json
{{
  "name": "表单验证-必填字段为空时的错误处理（重置会话）",
  "objective": "Validate proper error handling and user feedback for incomplete form submissions with clean session",
  "test_category": "Negative_Testing",
  "priority": "Medium",
  "test_data_requirements": "Empty or invalid data for required fields",
  "preamble_actions": [],
  "steps": [
    {{"action": "Attempt to submit form with required fields left empty"}},
    {{"verify": "Verify appropriate validation messages appear for each required field"}},
    {{"verify": "Verify form submission is prevented until all required fields are completed"}},
    {{"action": "Fill in all required fields with valid data"}},
    {{"action": "Submit the completed form"}},
    {{"verify": "Verify successful form submission and appropriate success feedback"}}
  ],
  "reset_session": true,
  "success_criteria": [
    "Form validation prevents submission with incomplete data",
    "Clear, actionable error messages guide user to correct input",
    "Form submits successfully once all validation requirements are met"
  ]
}}
```

**Note**: In Pattern 3, since `reset_session=true`, there's no navigation step in the `steps` array because the system automatically navigates to the target URL before execution. The `preamble_actions` is empty because no additional setup navigation is needed.
```

### Pattern 4: Search Functionality Testing (Realistic Search Engine Behavior)
```json
{{
  "name": "搜索功能验证-实际搜索引擎行为测试",
  "objective": "Validate search functionality with realistic expectations for search engines",
  "test_category": "Functional_Integration",
  "priority": "High",
  "test_data_requirements": "Valid search terms, ambiguous terms, special characters, very short terms",
  "preamble_actions": [],
  "steps": [
    {{"action": "Enter common search term '人工智能' in the search field"}},
    {{"action": "Click the search button or press Enter to initiate search"}},
    {{"verify": "Verify loading indicator appears during search processing"}},
    {{"verify": "Verify search results are displayed with relevant content"}},
    {{"verify": "Verify result count and related search suggestions if applicable"}},
    {{"action": "Enter ambiguous term 'xyz123' in the search field"}},
    {{"action": "Initiate search with the ambiguous term"}},
    {{"verify": "Verify search engine still returns results (may include related suggestions or alternative interpretations)"}}
  ],
  "reset_session": true,
  "success_criteria": [
    "Search functionality processes any input and returns appropriate results",
    "Loading states provide proper user feedback during processing",
    "Search engines handle ambiguous terms gracefully (showing related results or suggestions)",
    "Search results are relevant to the query terms"
  ]
}}
```

### Pattern 5: Login/Authentication Testing
```json
{{
  "name": "用户登录验证-有效凭据和权限检查",
  "objective": "Validate user authentication with valid credentials and proper permission checks",
  "test_category": "Security_Functional",
  "priority": "Critical",
  "test_data_requirements": "Valid username/password, test user account with known permissions",
  "preamble_actions": [],
  "steps": [
    {{"action": "Enter valid username in the username field"}},
    {{"action": "Enter valid password in the password field"}},
    {{"action": "Click the login button to authenticate"}},
    {{"verify": "Verify successful login confirmation message is displayed"}},
    {{"verify": "Verify user is redirected to appropriate dashboard or home page"}},
    {{"verify": "Verify user-specific features or content are accessible based on permissions"}}
  ],
  "reset_session": true,
  "success_criteria": [
    "Authentication system accepts valid credentials",
    "User is properly authenticated and redirected",
    "User permissions are correctly applied post-login"
  ]
}}
```

### Pattern 6: Login/Authentication Negative Testing
```json
{{
  "name": "用户登录验证-无效凭据和错误处理",
  "objective": "Validate proper error handling for invalid login attempts",
  "test_category": "Security_Negative",
  "priority": "High",
  "test_data_requirements": "Invalid username/password combinations, non-existent accounts",
  "preamble_actions": [],
  "steps": [
    {{"action": "Enter invalid username in the username field"}},
    {{"action": "Enter invalid password in the password field"}},
    {{"action": "Click the login button to authenticate"}},
    {{"verify": "Verify appropriate error message is displayed"}},
    {{"verify": "Verify user remains on login page"}},
    {{"verify": "Verify system does not grant access to protected areas"}},
    {{"action": "Enter valid username with invalid password"}},
    {{"action": "Click the login button to authenticate"}},
    {{"verify": "Verify password-specific error message is shown"}}
  ],
  "reset_session": false,
  "success_criteria": [
    "System properly rejects invalid credentials",
    "Clear error messages guide users to correct input",
    "Security is maintained for invalid login attempts"
  ]
}}
```

### Pattern 7: Data Creation (CRUD Operations)
```json
{{
  "name": "数据创建功能验证-表单提交和数据持久化",
  "objective": "Validate data creation through form submission and database persistence",
  "test_category": "Functional_Data",
  "priority": "High",
  "test_data_requirements": "Valid data for all required fields, unique test data",
  "preamble_actions": [
    {{"action": "Navigate to the data creation form page"}}
  ],
  "steps": [
    {{"action": "Fill in all required fields with valid test data"}},
    {{"action": "Enter optional data in appropriate fields"}},
    {{"action": "Click the submit or save button to create the record"}},
    {{"verify": "Verify success confirmation message is displayed"}},
    {{"verify": "Verify new record appears in the data list or table"}},
    {{"verify": "Verify data integrity by checking created record details"}}
  ],
  "reset_session": true,
  "success_criteria": [
    "Form accepts valid input without validation errors",
    "Data is successfully persisted to database",
    "User interface reflects successful creation",
    "Data integrity is maintained"
  ]
}}
```

### Pattern 8: Data Deletion (CRUD Operations)
```json
{{
  "name": "数据删除功能验证-记录删除和确认",
  "objective": "Validate data deletion with proper confirmation and state management",
  "test_category": "Functional_Data",
  "priority": "High",
  "test_data_requirements": "Existing test record that can be safely deleted",
  "preamble_actions": [
    {{"action": "Navigate to the data management page"}}
  ],
  "steps": [
    {{"action": "Locate the test record in the data list or table"}},
    {{"action": "Click the delete button for the test record"}},
    {{"verify": "Verify deletion confirmation dialog appears"}},
    {{"action": "Confirm the deletion action"}},
    {{"verify": "Verify success message is displayed"}},
    {{"verify": "Verify record is no longer visible in the data list"}},
    {{"verify": "Verify related data or references are handled appropriately"}}
  ],
  "reset_session": false,
  "success_criteria": [
    "System requires confirmation before deletion",
    "Record is successfully removed from database",
    "User interface reflects deletion immediately",
    "Data consistency is maintained after deletion"
  ]
}}
```

### Pattern 9: File Upload Functionality
```json
{{
  "name": "文件上传功能验证-格式检查和大小限制",
  "objective": "Validate file upload functionality with format validation and size limits",
  "test_category": "Functional_Integration",
  "priority": "Medium",
  "test_data_requirements": "Valid test files (various formats), oversized files, invalid formats",
  "preamble_actions": [
    {{"action": "Navigate to the file upload page"}}
  ],
  "steps": [
    {{"action": "Select a valid file within size limits"}},
    {{"action": "Click the upload button to start file transfer"}},
    {{"verify": "Verify upload progress indicator is displayed"}},
    {{"verify": "Verify success confirmation message appears after upload"}},
    {{"verify": "Verify uploaded file is listed or accessible"}},
    {{"action": "Attempt to upload a file exceeding size limits"}},
    {{"verify": "Verify appropriate size limit error message is displayed"}},
    {{"action": "Attempt to upload a file with invalid format"}},
    {{"verify": "Verify format validation error message is shown"}}
  ],
  "reset_session": false,
  "success_criteria": [
    "Valid files are uploaded successfully",
    "Size limits are enforced with clear error messages",
    "Format validation works correctly",
    "User feedback is provided throughout the process"
  ]
}}
```

### Pattern 10: Page Navigation and Routing
```json
{{
  "name": "页面导航验证-路由和面包屑导航",
  "objective": "Validate page navigation, routing, and breadcrumb functionality",
  "test_category": "UI_Navigation",
  "priority": "Medium",
  "test_data_requirements": "Multiple accessible pages with navigation structure",
  "preamble_actions": [],
  "steps": [
    {{"action": "Click on the main navigation menu item"}},
    {{"verify": "Verify page transitions to correct destination"}},
    {{"verify": "Verify URL changes appropriately"}},
    {{"verify": "Verify page title and content match navigation selection"}},
    {{"action": "Click on breadcrumb navigation item"}},
    {{"verify": "Verify navigation to parent or ancestor page"}},
    {{"action": "Use browser back and forward buttons"}},
    {{"verify": "Verify proper navigation history management"}},
    {{"action": "Test direct URL access to internal pages"}},
    {{"verify": "Verify proper access control and content display"}}
  ],
  "reset_session": false,
  "success_criteria": [
    "Navigation elements function correctly",
    "URL routing matches page content",
    "Browser navigation is properly handled",
    "Breadcrumbs provide accurate navigation path"
  ]
}}
```

### Pattern 11: Pagination and Sorting
```json
{{
  "name": "分页和排序功能验证-大数据集处理",
  "objective": "Validate pagination functionality and sorting of large data sets",
  "test_category": "Functional_Data",
  "priority": "Medium",
  "test_data_requirements": "Data set with multiple pages, sortable columns",
  "preamble_actions": [
    {{"action": "Navigate to page with paginated data"}}
  ],
  "steps": [
    {{"action": "Verify initial page displays correct number of items"}},
    {{"action": "Click next page button or link"}},
    {{"verify": "Verify page transitions to show next set of items"}},
    {{"verify": "Verify page number or indicator updates correctly"}},
    {{"action": "Click previous page button or link"}},
    {{"verify": "Verify page transitions back to previous items"}},
    {{"action": "Click on column header to sort by that column"}},
    {{"verify": "Verify data is re-sorted according to selected column"}},
    {{"action": "Click same column header again to reverse sort"}},
    {{"verify": "Verify sort order is reversed"}}
  ],
  "reset_session": false,
  "success_criteria": [
    "Pagination controls function correctly",
    "Page transitions maintain data consistency",
    "Sorting functionality works on all sortable columns",
    "Sort order toggling works correctly"
  ]
}}
```

### Pattern 12: Comment/Feedback System
```json
{{
  "name": "评论反馈系统验证-提交和审核流程",
  "objective": "Validate comment submission and moderation workflow",
  "test_category": "Functional_User_Interaction",
  "priority": "Low",
  "test_data_requirements": "Valid comment text, test user account",
  "preamble_actions": [
    {{"action": "Navigate to page with comment system"}},
    {{"action": "Login with test user account if required"}}
  ],
  "steps": [
    {{"action": "Enter valid comment text in comment field"}},
    {{"action": "Click submit button to post comment"}},
    {{"verify": "Verify comment appears in the list (may be pending approval)"}},
    {{"verify": "Verify appropriate success message is displayed"}},
    {{"action": "Enter comment with special characters or formatting"}},
    {{"action": "Submit formatted comment"}},
    {{"verify": "Verify formatting is handled correctly"}},
    {{"action": "Test comment length limits with very long comment"}},
    {{"verify": "Verify length validation works appropriately"}}
  ],
  "reset_session": false,
  "success_criteria": [
    "Comment system accepts valid input",
    "Special characters and formatting are handled correctly",
    "Length limits are enforced",
    "User feedback is provided throughout the process"
  ]
}}
```

## Output Format Requirements

Your response must follow this exact structure:

1. **Analysis Scratchpad**: Complete structured analysis following the QA framework
2. **JSON Test Plan**: Well-formed JSON array containing all generated test cases

### Required Output Structure:
```
<analysis_scratchpad>
**1. Functional Module Identification:**
[Detailed analysis of UI components, business logic, and integration points]

**2. User Journey & Workflow Analysis:**  
[Analysis of primary and alternative user paths, error scenarios]

**3. Test Coverage Planning:**
[Coverage strategy across functional, UI, data, and platform dimensions]

**4. Risk Assessment & Prioritization:**
[Risk analysis and priority assignment rationale]

**5. Test Case Generation Strategy:**
[Approach for test case selection and design rationale]
</analysis_scratchpad>

```json
[
  {{
    "name": "descriptive_test_identifier",
    "objective": "clear_test_purpose_statement",
    "test_category": "category_classification",
    "priority": "priority_level",
    "test_data_requirements": "data_requirements_specification",
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

## Quality Assurance Standards
- **Completeness**: Ensure comprehensive coverage of identified requirements
- **Traceability**: Each test case must trace back to specific business objectives
- **Maintainability**: Design tests that can be easily updated as the application evolves
- **Reliability**: Create stable tests that produce consistent results across executions
- **Efficiency**: Balance thorough testing with practical execution time constraints
"""
    
    return prompt


def get_reflection_prompt(
    business_objectives: str,
    current_plan: list,
    completed_cases: list,
    page_structure: str,
    page_content_summary: dict = None
) -> str:
    """
    生成反思和重新规划的提示词
    
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
## Testing Mode: Intent-Driven Testing
**Original Business Objectives**: {business_objectives}

### Mode-Specific Success Criteria:
- **Requirements Compliance**: All specified business objectives must be addressed
- **Constraint Satisfaction**: Any specified constraints (test case count, specific elements) must be met
- **Focused Coverage**: Test cases should directly target stated requirements rather than comprehensive coverage
"""
        coverage_criteria = """
- **Requirements Coverage**: Percentage of specified business objectives validated
- **Constraint Compliance**: Adherence to specified test case counts or element focus
- **Intent Alignment**: How well test cases address the specific requirements mentioned in objectives
- **Priority Weighted Coverage**: Critical business objectives and high-impact scenarios should be prioritized over general coverage
"""
        mode_specific_logic = """
- **Intent-Driven Mode**: FINISH if all specified business objectives are achieved AND constraints are satisfied
"""
    else:
        mode_context = """
## Testing Mode: Comprehensive Testing
**Original Objectives**: Comprehensive testing of all functionalities

### Mode-Specific Success Criteria:
- **Complete Functional Coverage**: All interactive elements and core functionalities must be tested
- **Risk-Based Prioritization**: Critical business functions should be prioritized and validated
- **Quality Assurance**: Include validation, error handling, and edge case testing across all components
"""
        coverage_criteria = """
- **Element Coverage**: Percentage of interactive elements tested
- **Functional Coverage**: Coverage of all core business functionalities
- **Risk Coverage**: Critical and high-priority scenarios completion status
- **Priority-Based Assessment**: Business-critical functions (login, core transactions, data integrity) should be prioritized over UI elements
"""
        mode_specific_logic = """
- **Comprehensive Mode**: FINISH if all interactive elements are tested AND core functionalities are validated
"""

    prompt = f"""
## Role
You are a Senior QA Test Manager responsible for dynamic test execution oversight and strategic decision-making. Your expertise includes test progress analysis, risk assessment, and adaptive test planning based on real-time execution results.

## Mission
Analyze current test execution status, evaluate progress against the original testing mode and objectives, and make informed strategic decisions about test continuation, plan revision, or test completion based on comprehensive coverage analysis and risk assessment.

{mode_context}

## Execution Context Analysis
- **Current Test Plan**: 
{current_plan_json}
- **Completed Test Execution Summary**:
{completed_summary}
- **Current Application State**: (Referenced via attached screenshot){interactive_elements_section}
- **Current UI Text Structure**:
{page_structure}

## Strategic Decision Framework

Apply the following decision logic in **STRICT SEQUENTIAL ORDER**:

### Phase 0: Normal Progress Detection (HIGHEST PRIORITY - FIRST CHECK)
**Critical Rule**: Before any complex analysis, check for normal test execution progress.

**Normal Progress Indicators**:
- **Test Completion Status**: Number of completed_cases < total planned test_cases
- **Recent Success**: Last completed test case has successful status (passed/success)
- **No Critical Errors**: No system crashes, unrecoverable errors, or blocking UI states
- **Sequential Execution**: Tests are progressing through the planned sequence

**Decision Logic for Normal Progress**:
```
IF (len(completed_cases) < len(current_plan) 
    AND last_completed_case_status is successful 
    AND no_critical_blocking_errors):
    THEN decision = "CONTINUE"
    EXPLANATION: "Normal test execution progress detected. The last test case completed successfully and more planned test cases remain to be executed. Continuing with sequential execution."
```

**Only proceed to Phase 1-3 if normal progress conditions are NOT met.**

### Phase 1: Application State Assessment (SECOND PRIORITY)
**Evaluation Criteria**: Analyze current UI state for test execution blockers

**Blocking Conditions Analysis**:
- **Critical UI Changes**: Unexpected modals, error dialogs, or navigation disruptions
- **Application Failures**: System crashes, unresponsive pages, or error states
- **Environmental Issues**: Network connectivity problems or timeout conditions
- **Test Data Conflicts**: Data integrity issues affecting subsequent tests

**Decision Logic**:
- **BLOCKED State Detected** → Decision: `REPLAN`
  - Provide detailed blocker analysis and remediation strategy
  - Generate new test plan to address or work around the blocker
- **NO BLOCKING Issues** → Proceed to Phase 2

### Phase 2: Coverage & Objective Achievement Assessment (THIRD PRIORITY)
**Evaluation Criteria**: Assess test completion status against original objectives

**Coverage Analysis**:
{coverage_criteria}- **User Journey Coverage**: End-to-end workflow validation completeness
- **Edge Case Coverage**: Boundary conditions and error scenarios testing

**Objective Achievement Analysis**:
- **Primary Objectives**: Core business functionality validation status
- **Secondary Objectives**: Additional requirements and quality attributes
- **Success Criteria**: Measurable outcomes achievement evaluation

**Mode-Specific Decision Logic**:
{mode_specific_logic}

**Decision Logic**:
- **All Objectives Achieved** AND **All Planned Cases Complete** → Decision: `FINISH`
- **Remaining Objectives** OR **Incomplete Cases** → Decision: `CONTINUE`

### Phase 3: Plan Adequacy Assessment (LOWEST PRIORITY)
**Evaluation Criteria**: Determine if current plan can achieve remaining objectives

**Plan Effectiveness Analysis**:
- **Test Case Relevance**: Do remaining tests address current objectives?
- **Test Environment Alignment**: Are tests compatible with current application state?
- **Execution Feasibility**: Can remaining tests be executed without modification?

**Decision Logic**:
- **Current Plan Adequate** → Decision: `CONTINUE`
- **Plan Revision Required** → Decision: `REPLAN`

## Output Format (Strict JSON Schema)

### For CONTINUE or FINISH Decisions:
```json
{{
  "decision": "CONTINUE" | "FINISH",
  "reasoning": "Comprehensive explanation of decision rationale including coverage analysis, objective assessment, and risk evaluation",
  "coverage_analysis": {{
    "functional_coverage_percent": estimated_percentage,
    "objectives_completed": number_of_completed_objectives,
    "remaining_risks": "assessment_of_outstanding_risks"
  }},
  "new_plan": []
}}
```

### For REPLAN Decision:
```json
{{
  "decision": "REPLAN",
  "reasoning": "Detailed explanation of why current plan is inadequate, including specific blockers, coverage gaps, or environmental changes",
  "replan_strategy": {{
    "blocker_resolution": "approach_to_address_identified_blockers",
    "coverage_enhancement": "strategy_to_improve_test_coverage",
    "risk_mitigation": "measures_to_address_outstanding_risks"
  }},
  "new_plan": [
    {{
      "name": "修订后的测试用例（中文命名）",
      "objective": "clear_test_purpose_aligned_with_remaining_objectives",
      "test_category": "category_classification",
      "priority": "priority_based_on_risk_assessment",
      "steps": [
        {{"action": "action_instruction"}},
        {{"verify": "validation_instruction"}}
      ],
      "reset_session": boolean_flag,
      "success_criteria": ["measurable_success_conditions"]
    }}
  ]
}}
```

## Test Case Design Standards for Replanning

### Navigation Optimization Guidelines for Replanning
**IMPORTANT**: When generating new test cases during replanning, apply the same navigation optimization rules:

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

### Session Management Considerations
- **reset_session=true**: Use for test isolation, when you need a clean browser state
- **reset_session=false**: Use for continuous testing, when you want to maintain state between tests
- **Mixed Strategies**: You can generate both types of test cases in the same plan as needed

## Decision Quality Standards
- **Evidence-Based**: All decisions must be supported by concrete evidence from execution results
- **Risk-Informed**: Consider business impact and technical risk in all decision-making
- **Coverage-Driven**: Ensure adequate test coverage before declaring completion
- **Objective-Aligned**: Maintain focus on original business objectives throughout analysis
- **Traceability**: Provide clear rationale linking analysis to strategic decisions
- **Progress-Oriented**: Favor CONTINUE decisions when tests are progressing normally to avoid unnecessary interruptions
"""
    
    return prompt