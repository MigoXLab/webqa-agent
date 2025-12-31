# WebQA Agent Custom Tool Development - LLM Context Document

______________________________________________________________________

## **DOCUMENT TYPE**: LLM Context / System Prompt **AUDIENCE**: Large Language Models (Claude, GPT-4, Gemini, etc.) **PURPOSE**: Provide complete project context for AI-assisted custom tool development **VERSION**: 0.1.0 **LAST_UPDATED**: 2025-12-31

## PROJECT CONTEXT

### What is WebQA Agent?

WebQA Agent is an autonomous web browser testing framework using AI-powered agents.

- **Architecture**: LangGraph-based workflow orchestration
- **Browser Automation**: Playwright async API
- **AI Models**: OpenAI, Anthropic, Google Gemini support
- **Custom Tools**: Extensible testing capabilities via tool registry

### System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Custom Tool Class                        │
│                  (YourTool extends WebQABaseTool)               │
└────────────────────────────────┬────────────────────────────────┘
                                 │ inherits
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                         WebQABaseTool                           │
│  - format_success(), format_failure(), format_critical_error()  │
│  - update_action_context(), get_execution_context()             │
└────────────────────────────────┬────────────────────────────────┘
                                 │ uses
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                          ResponseTags                           │
│    [SUCCESS], [FAILURE], [CRITICAL_ERROR:TYPE], [WARNING]       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    @register_tool decorator                     │
└────────────────────────────────┬────────────────────────────────┘
                                 │ registers to
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ToolRegistry (Singleton)                     │
└────────────────────────────────┬────────────────────────────────┘
                                 │ provides tools to
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                       LangGraph Workflow                        │
│                    (graph.py orchestration)                     │
└────────────────────────────────┬────────────────────────────────┘
                                 │ executes
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Tool._arun(async)                         │
└────────────────────────────────┬────────────────────────────────┘
                                 │ updates
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                 ui_tester.last_action_context                   │
└────────────────────────────────┬────────────────────────────────┘
                                 │ consumed by
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Assertion Tools                          │
└─────────────────────────────────────────────────────────────────┘

                ┌─────────────────────────────────────────┐
                │        case_recorder.add_step()         │
                │             (HTML Report)               │
                └─────────────────────────────────────────┘
```

### Critical Files

- `webqa_agent/testers/case_gen/tools/base.py` - Base classes, response tags, metadata
- `webqa_agent/testers/case_gen/tools/registry.py` - Singleton registry, tool discovery
- `webqa_agent/testers/case_gen/graph.py` - LangGraph workflow orchestration
- `webqa_agent/testers/case_gen/agents/execute_agent.py` - Tool execution and control flow
- `webqa_agent/testers/case_gen/tools/element_action_tool.py` - Browser interaction reference
- `webqa_agent/testers/case_gen/tools/custom/link_detection_tool.py` - Custom tool example

### Project Directory Structure

```
webqa_agent/
├── testers/
│   └── case_gen/
│       ├── tools/
│       │   ├── base.py              # WebQABaseTool, WebQAToolMetadata, ResponseTags
│       │   ├── registry.py          # ToolRegistry singleton, @register_tool
│       │   ├── element_action_tool.py  # Browser interaction patterns (UITool)
│       │   ├── ux_tool.py          # UX testing tools
│       │   ├── custom/              # ← YOUR CUSTOM TOOLS HERE
│       │   │   ├── __init__.py
│       │   │   ├── link_detection_tool.py  # Example custom tool
│       │   │   └── {{your_tool}}.py        # Place your tool here
│       │   └── __init__.py
│       ├── graph.py                # LangGraph workflow orchestration
│       ├── agents/
│       │   └── execute_agent.py    # Tool execution and control flow
│       └── state/
│           └── schemas.py          # State management schemas
├── browser/
│   └── session.py                  # Browser session pool management
├── llm/
│   └── llm_api.py                  # Multi-provider LLM client
└── actions/
    └── action_handler.py           # Browser action execution

tests/
└── custom_tools/                   # ← YOUR TESTS HERE
    ├── __init__.py
    └── test_{{your_tool}}.py       # Place your tests here

config/
└── config.yaml                     # Main configuration file
```

**Key Locations**:

- **Custom Tools**: `webqa_agent/testers/case_gen/tools/custom/`
- **Tests**: `tests/custom_tools/`
- **Config**: `config/config.yaml`

______________________________________________________________________

## MANDATORY CONSTRAINTS

### Hard Requirements (MUST follow)

1. **Inheritance**: All tools MUST inherit from `WebQABaseTool`
2. **Decorator**: All tools MUST use `@register_tool` decorator
3. **Async Execution**: All tools MUST implement `async def _arun()` (NOT sync `def _run()`)
4. **Response Tags**: All returns MUST include one of:
   - `[SUCCESS]` - Continue to next step
   - `[FAILURE]` - Trigger adaptive recovery
   - `[CRITICAL_ERROR:TYPE]` - Abort test immediately
   - `[WARNING]` - Non-blocking issue
   - `[CANNOT_VERIFY]` - Verification prerequisite failed

### Response Tag Types

**CRITICAL_ERROR Types** (cause immediate abort):

- `ELEMENT_NOT_FOUND` - Element not found/inaccessible
- `NAVIGATION_FAILED` - Page navigation failed
- `PERMISSION_DENIED` - Access denied
- `PAGE_CRASHED` - Browser crashed
- `NETWORK_ERROR` - Network issues
- `SESSION_EXPIRED` - Authentication expired
- `UNSUPPORTED_PAGE` - PDF/plugin pages
- `VALIDATION_ERROR` - Form validation failed

### File Location Rules

- **Custom tools**: `webqa_agent/testers/case_gen/tools/custom/your_tool.py`
- **Tests**: `tests/custom_tools/test_your_tool.py`
- **Config**: `config/config.yaml` (for test configuration)

### Naming Conventions (STRICT)

- **Class Name**: PascalCaseTool (e.g., `TitleCheckerTool`)
- **File Name**: snake_case_tool.py (e.g., `title_checker.py`)
- **Tool Name** (in metadata): snake_case (e.g., `check_page_title`)
- **Step Type**: snake_case or `custom_xxx` (e.g., `custom_api_test`)

______________________________________________________________________

## CODE TEMPLATES

### Minimal Working Tool Template

```python
"""
File: webqa_agent/testers/case_gen/tools/custom/{{TOOL_NAME_SNAKE}}.py

{{TOOL_DESCRIPTION}}
"""
from typing import Any, Type
from pydantic import BaseModel, Field
from webqa_agent.testers.case_gen.tools.base import (
    WebQABaseTool,
    WebQAToolMetadata,
)
from webqa_agent.testers.case_gen.tools.registry import register_tool

# Step 1: Define parameter schema
class {{TOOL_NAME_PASCAL}}Schema(BaseModel):
    {{PARAM_NAME}}: {{PARAM_TYPE}} = Field(
        description="{{PARAM_DESCRIPTION}}"
    )
    # Add more parameters as needed

# Step 2: Register and define tool class
@register_tool
class {{TOOL_NAME_PASCAL}}Tool(WebQABaseTool):
    """{{TOOL_DESCRIPTION}}"""

    name: str = "{{TOOL_NAME_SNAKE}}"
    description: str = "{{BRIEF_DESCRIPTION}}"
    args_schema: Type[BaseModel] = {{TOOL_NAME_PASCAL}}Schema

    # Required for browser access
    ui_tester_instance: Any = Field(...)

    # Step 3: Define metadata for registration
    @classmethod
    def get_metadata(cls) -> WebQAToolMetadata:
        return WebQAToolMetadata(
            name="{{TOOL_NAME_SNAKE}}",
            category="custom",  # Options: action, assertion, ux, custom
            step_type="{{TOOL_NAME_SNAKE}}",
            description_short="{{ONE_LINE_DESCRIPTION}}",
            description_long="{{DETAILED_DESCRIPTION}}",
            examples=[
                '{"action": "{{TOOL_NAME_SNAKE}}", "params": {"{{PARAM_NAME}}": "value"}}',
            ],
            use_when=[
                "{{SCENARIO_1}}",
                "{{SCENARIO_2}}",
            ],
            dont_use_when=[
                "{{ANTI_PATTERN_1}}",
            ],
            priority=55,  # 1-100, core tools: 70-90, custom: 30-60
            dependencies=[],  # e.g., ["aiohttp", "beautifulsoup4"]
        )

    # Step 4: Implement async execution logic
    async def _arun(
        self,
        {{PARAM_NAME}}: {{PARAM_TYPE}},
        # Add more parameters matching schema
    ) -> str:
        """Execute tool logic and return response with tag."""
        try:
            # Get browser page if needed
            page = await self.ui_tester_instance.get_current_page()

            # Implement your logic here
            result = await self._execute_logic({{PARAM_NAME}})

            # Update context for downstream tools (RECOMMENDED for action tools)
            self.update_action_context(
                self.ui_tester_instance,
                {
                    'description': f'Executed {{TOOL_NAME_SNAKE}}',
                    'action_type': '{{TOOL_NAME_PASCAL}}',
                    'status': 'success',
                    'result': result,
                    'timestamp': __import__('datetime').datetime.now().isoformat(),
                }
            )

            # Return success with tag
            return self.format_success(f"Operation completed: {result}")

        except Exception as e:
            # For recoverable errors
            return self.format_failure(
                f"Operation failed: {str(e)}",
                recovery_hints=[
                    "Try alternative approach",
                    "Check prerequisites",
                ]
            )
```

### Advanced Features Template

#### Context Management

```python
async def _arun(self, param: str) -> str:
    # Execute action
    result = await self._perform_action(param)

    # Update context for subsequent tools
    self.update_action_context(
        self.ui_tester_instance,
        {
            'description': 'Action description',
            'action_type': 'MyAction',
            'status': 'success',
            'result': {
                'message': 'Success',
                'data': result  # Key data for next tools
            },
            'timestamp': __import__('datetime').datetime.now().isoformat(),
        }
    )

    return self.format_success("Done")

# In subsequent assertion tools:
async def _arun(self, ...):
    context = self.get_execution_context(self.ui_tester_instance)
    if context:
        previous_data = context['last_action']['result']['data']
        # Use previous_data for validation
```

#### case_recorder Integration (for HTML reports)

```python
async def _arun(self, param: str) -> str:
    import json

    result = await self._execute(param)

    # Record step in HTML report
    if self.case_recorder:
        self.case_recorder.add_step(
            description=f"Custom operation: {param}",
            screenshots=[],  # Optional
            model_io=json.dumps({
                'input': param,
                'output': result,
                'metadata': {...}
            }, ensure_ascii=False),
            actions=[],
            status='passed',
            step_type='action',
        )

    return self.format_success(f"Result: {result}")
```

#### Accessing LLM Config and Other Context

```python
@classmethod
def get_required_params(cls) -> Dict[str, str]:
    """Declare required initialization parameters."""
    return {
        'ui_tester_instance': 'ui_tester_instance',
        'llm_config': 'llm_config',  # Access LLM configuration
        'case_recorder': 'case_recorder',  # Access case recorder
    }

async def _arun(self, param: str) -> str:
    # Now can access self.llm_config
    model_name = self.llm_config.get('model', 'gpt-4')
    # Adjust behavior based on model
```

______________________________________________________________________

## ERROR PATTERNS TO AVOID

### ❌ WRONG: Missing Response Tag

```python
async def _arun(self, param: str):
    return "Operation completed"  # Missing [SUCCESS] tag
```

**Symptom**: Test hangs, execute_agent can't determine success/failure
**Fix**: Use `self.format_success("Operation completed")`

### ❌ WRONG: Using Sync Method

```python
def _run(self, param: str):  # Sync method
    return self.format_success("Done")
```

**Symptom**: `NotImplementedError: Sync execution not supported`
**Fix**: Use `async def _arun(self, param: str):`

### ❌ WRONG: Not Using @register_tool

```python
class MyTool(WebQABaseTool):  # No decorator
    ...
```

**Symptom**: Tool not discovered, not available in workflow
**Fix**: Add `@register_tool` before class definition

### ❌ WRONG: JSON Serialization Error

```python
if self.case_recorder:
    self.case_recorder.add_step(
        model_io={'exception': some_exception_obj}  # Not JSON serializable
    )
```

**Symptom**: `TypeError: Object of type Exception is not JSON serializable`
**Fix**: Convert to string: `model_io=json.dumps({'error': str(exception)}, ensure_ascii=False)`

### ❌ WRONG: Undeclared Dependencies

```python
import requests  # Used but not declared

@classmethod
def get_metadata(cls):
    return WebQAToolMetadata(
        name="my_tool",
        dependencies=[]  # Missing 'requests'
    )
```

**Symptom**: `ModuleNotFoundError` for users
**Fix**: Declare in metadata: `dependencies=["requests"]`

### ❌ WRONG: Not Updating Context (for action tools)

```python
async def _arun(self, param: str):
    result = self._process(param)
    return self.format_success("Done")
    # Missing update_action_context() call
```

**Symptom**: Subsequent assertion tools show "Status: UNKNOWN", can't verify previous action
**Fix**: Call `self.update_action_context()` after successful execution

______________________________________________________________________

## TESTING REQUIREMENTS

### Verification Checklist

1. **Syntax Check**:

   ```bash
   python -m py_compile webqa_agent/testers/case_gen/tools/custom/my_tool.py
   ```

2. **Registration Check**:

   ```python
   from webqa_agent.testers.case_gen.tools.registry import get_registry
   assert 'my_tool' in get_registry().get_tool_names()
   ```

3. **Unit Tests** (pytest):

   ```python
   # tests/custom_tools/test_my_tool.py
   import pytest
   from webqa_agent.testers.case_gen.tools.custom.my_tool import MyTool

   @pytest.mark.asyncio
   async def test_my_tool_success():
       tool = MyTool(ui_tester_instance=mock_tester)
       result = await tool._arun(param="test")
       assert "[SUCCESS]" in result

   @pytest.mark.asyncio
   async def test_my_tool_failure():
       tool = MyTool(ui_tester_instance=mock_tester)
       result = await tool._arun(param="invalid")
       assert "[FAILURE]" in result
   ```

4. **Integration Test** (config.yaml):

   **Important**: In AI mode (`type: ai`), test steps are NOT defined in YAML.
   The LLM automatically generates test steps based on `business_objectives`.

   ```yaml
   test_config:
     function_test:
       enabled: true
       type: "ai"  # AI mode - LLM generates test steps
       business_objectives: "Test functionality using my_tool"
       dynamic_step_generation:
         enabled: true
         max_dynamic_steps: 10
   ```

   Run: `webqa-agent run -c config.yaml`

### Code Quality Standards

```bash
# Format code
black webqa_agent/testers/case_gen/tools/custom/my_tool.py

# Sort imports
isort webqa_agent/testers/case_gen/tools/custom/my_tool.py

# Lint (must pass)
flake8 webqa_agent/testers/case_gen/tools/custom/my_tool.py
```

______________________________________________________________________

## EXECUTION FLOW

### How Tools Are Executed

1. **Registration**: `@register_tool` decorator registers tool in ToolRegistry singleton
2. **Discovery**: LangGraph workflow queries registry for available tools
3. **Selection**: LLM selects tool based on metadata descriptions
4. **Instantiation**: Registry creates tool instance with required params
5. **Execution**: Workflow calls `tool._arun(**params)`
6. **Response Parsing**: execute_agent parses response tag
7. **Control Flow**:
   - `[SUCCESS]` → Continue to next step
   - `[FAILURE]` → Trigger adaptive recovery (if enabled)
   - `[CRITICAL_ERROR:TYPE]` → Abort test, save results
   - `[WARNING]` → Log and continue
   - `[CANNOT_VERIFY]` → Skip verification, continue

### Adaptive Recovery (when dynamic_step_generation enabled)

- **ELEMENT_NOT_FOUND**: Two-layer recovery (retry + LLM replanning)
- **Other FAILURE**: LLM-driven recovery (GoBack, timeout adjustment, alternative action)
- **Loop Detection**: Aborts if same error pattern repeats 2+ times

______________________________________________________________________

## COMMON USE CASES

### 1. API Testing Tool

```python
import aiohttp
import jsonschema
from typing import Dict, Type
from pydantic import BaseModel, Field

class APIValidatorSchema(BaseModel):
    endpoint: str = Field(description="API endpoint to validate")
    expected_schema: Dict = Field(description="JSON schema to validate against")

@register_tool
class APIValidatorTool(WebQABaseTool):
    """Validates API responses against JSON schema."""

    name: str = "validate_api_response"
    description: str = "Validates API responses against JSON schema"
    args_schema: Type[BaseModel] = APIValidatorSchema

    ui_tester_instance: Any = Field(...)

    @classmethod
    def get_metadata(cls):
        return WebQAToolMetadata(
            name="validate_api_response",
            category="custom",
            step_type="validate_api",
            description_short="Validates API responses against JSON schema",
            priority=60,
            dependencies=["aiohttp", "jsonschema"]
        )

    async def _arun(self, endpoint: str, expected_schema: Dict) -> str:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint) as resp:
                    if resp.status != 200:
                        return self.format_failure(
                            f"API returned {resp.status}",
                            recovery_hints=["Check endpoint URL", "Verify authentication"]
                        )
                    data = await resp.json()

            jsonschema.validate(instance=data, schema=expected_schema)
            return self.format_success(f"API validation passed for {endpoint}")

        except jsonschema.ValidationError as e:
            return self.format_failure(f"Schema validation failed: {e.message}")
        except Exception as e:
            return self.format_critical_error("NETWORK_ERROR", str(e))
```

### 2. Screenshot Comparison Tool

```python
from PIL import Image
import imagehash
import io

@register_tool
class ScreenshotCompareTool(WebQABaseTool):
    """Compares current page screenshot with baseline."""

    async def _arun(self, baseline_path: str, threshold: float = 0.95) -> str:
        page = await self.ui_tester_instance.get_current_page()

        current_screenshot = await page.screenshot()
        current_image = Image.open(io.BytesIO(current_screenshot))
        baseline_image = Image.open(baseline_path)

        current_hash = imagehash.average_hash(current_image)
        baseline_hash = imagehash.average_hash(baseline_image)
        similarity = 1 - (current_hash - baseline_hash) / len(current_hash.hash) ** 2

        if similarity >= threshold:
            return self.format_success(f"Screenshot match: {similarity:.2%}")
        else:
            return self.format_failure(
                f"Screenshot mismatch: {similarity:.2%} (threshold: {threshold:.2%})",
                recovery_hints=["Update baseline if UI changed intentionally"]
            )
```

### 3. Page Title Checker

```python
import re

@register_tool
class TitleCheckerTool(WebQABaseTool):
    """Validates page title against expected pattern."""

    async def _arun(self, expected_title: str, case_sensitive: bool = False) -> str:
        try:
            page = await self.ui_tester_instance.get_current_page()
            actual_title = await page.title()

            flags = 0 if case_sensitive else re.IGNORECASE
            if re.search(expected_title, actual_title, flags):
                return self.format_success(f"Title matches: '{actual_title}'")
            else:
                return self.format_failure(
                    f"Title mismatch. Expected: '{expected_title}', Actual: '{actual_title}'",
                    recovery_hints=["Check pattern", "Wait for dynamic title"]
                )
        except Exception as e:
            return self.format_critical_error("PAGE_CRASHED", str(e))
```

### 4. Form Auto-Fill Tool

```python
from typing import Dict

class FormAutoFillSchema(BaseModel):
    form_data: Dict[str, str] = Field(description="Field name to value mapping")

@register_tool
class FormAutoFillTool(WebQABaseTool):
    """Auto-fills form fields from structured data."""

    name: str = "auto_fill_form"
    description: str = "Automatically fills form fields with provided data"
    args_schema: Type[BaseModel] = FormAutoFillSchema

    ui_tester_instance: Any = Field(...)

    @classmethod
    def get_metadata(cls):
        return WebQAToolMetadata(
            name="auto_fill_form",
            category="custom",
            step_type="auto_fill_form",
            description_short="Auto-fills form fields from structured data",
            examples=[
                '{"action": "auto_fill_form", "params": {"form_data": {"username": "test", "email": "test@example.com"}}}'
            ],
            use_when=["Testing registration forms", "Filling multi-field forms", "E2E testing with form submissions"],
            priority=60,
        )

    async def _arun(self, form_data: Dict[str, str]) -> str:
        """Fill form fields based on field names or IDs."""
        try:
            page = await self.ui_tester_instance.get_current_page()
            filled_fields = []

            for field_name, value in form_data.items():
                # Try multiple selectors: name, id, placeholder
                selectors = [
                    f'[name="{field_name}"]',
                    f'#{field_name}',
                    f'[placeholder*="{field_name}" i]',
                    f'input[type="text"]:has-text("{field_name}")',
                ]

                field_filled = False
                for selector in selectors:
                    try:
                        field = await page.locator(selector).first
                        if await field.is_visible():
                            await field.fill(value)
                            filled_fields.append(field_name)
                            field_filled = True
                            break
                    except:
                        continue

                if not field_filled:
                    return self.format_failure(
                        f"Could not find field: {field_name}",
                        recovery_hints=[
                            "Check field name/ID spelling",
                            "Ensure form is visible on page",
                            f"Try manual selector for '{field_name}'"
                        ]
                    )

            # Update context for verification tools
            self.update_action_context(
                self.ui_tester_instance,
                {
                    'description': 'Auto-filled form fields',
                    'action_type': 'FormAutoFill',
                    'status': 'success',
                    'result': {
                        'fields_filled': filled_fields,
                        'total_fields': len(form_data)
                    },
                    'timestamp': __import__('datetime').datetime.now().isoformat(),
                }
            )

            return self.format_success(f"Successfully filled {len(filled_fields)} form fields: {', '.join(filled_fields)}")

        except Exception as e:
            return self.format_critical_error("VALIDATION_ERROR", f"Form fill failed: {str(e)}")
```

### 5. Database Query Validation Tool

```python
import asyncpg  # PostgreSQL example
from typing import List, Dict, Any

class DBQuerySchema(BaseModel):
    query: str = Field(description="SQL query to execute")
    expected_row_count: int = Field(default=None, description="Expected number of rows")
    expected_columns: List[str] = Field(default=None, description="Expected column names")

@register_tool
class DBQueryValidatorTool(WebQABaseTool):
    """Validates database queries for integration testing."""

    name: str = "validate_db_query"
    description: str = "Executes and validates database queries"
    args_schema: Type[BaseModel] = DBQuerySchema

    ui_tester_instance: Any = Field(...)

    @classmethod
    def get_metadata(cls):
        return WebQAToolMetadata(
            name="validate_db_query",
            category="custom",
            step_type="validate_db_query",
            description_short="Validates database queries and results",
            examples=[
                '{"action": "validate_db_query", "params": {"query": "SELECT * FROM users WHERE active=true", "expected_row_count": 5}}'
            ],
            use_when=[
                "Verifying data persistence after form submission",
                "Testing database-backed features",
                "E2E testing with database state validation"
            ],
            dont_use_when=[
                "Production databases (use test databases only)",
                "Modifying data (SELECT queries only for safety)"
            ],
            priority=55,
            dependencies=["asyncpg"]  # Or psycopg2, mysql-connector, etc.
        )

    async def _arun(
        self,
        query: str,
        expected_row_count: int = None,
        expected_columns: List[str] = None
    ) -> str:
        """Execute query and validate results (read-only for safety)."""
        try:
            # Enforce read-only queries for safety
            if not query.strip().upper().startswith('SELECT'):
                return self.format_critical_error(
                    "VALIDATION_ERROR",
                    "Only SELECT queries are allowed for safety. Use database migration tools for modifications."
                )

            # Connect to test database (from config or env vars)
            db_url = self.ui_tester_instance.config.get('test_db_url')
            if not db_url:
                return self.format_cannot_verify(
                    "Database query validation",
                    "test_db_url not configured"
                )

            conn = await asyncpg.connect(db_url)
            try:
                rows = await conn.fetch(query)
                result = [dict(row) for row in rows]

                # Validate row count
                if expected_row_count is not None and len(result) != expected_row_count:
                    return self.format_failure(
                        f"Row count mismatch. Expected: {expected_row_count}, Actual: {len(result)}",
                        recovery_hints=[
                            "Check query WHERE conditions",
                            "Verify test data setup",
                            f"Current result: {result[:3]}..."  # Show first 3 rows
                        ]
                    )

                # Validate columns
                if expected_columns and result:
                    actual_columns = set(result[0].keys())
                    expected_set = set(expected_columns)
                    if actual_columns != expected_set:
                        missing = expected_set - actual_columns
                        extra = actual_columns - expected_set
                        return self.format_failure(
                            f"Column mismatch. Missing: {missing}, Extra: {extra}",
                            recovery_hints=["Check query SELECT clause", "Verify table schema"]
                        )

                return self.format_success(
                    f"Query validated: {len(result)} rows, columns: {list(result[0].keys()) if result else []}"
                )

            finally:
                await conn.close()

        except Exception as e:
            return self.format_critical_error("NETWORK_ERROR", f"Database query failed: {str(e)}")
```

______________________________________________________________________

## METADATA BEST PRACTICES

### Priority Guidelines

- **Core System Tools**: 70-90 (e.g., Tap, Input, Scroll)
- **High-Value Custom Tools**: 55-65 (e.g., API validators, specialized assertions)
- **General Custom Tools**: 40-55 (e.g., utility tools, helpers)
- **Experimental Tools**: 30-40 (e.g., beta features, edge cases)

### Writing Good Descriptions

**description_short** (one line for LLM tool selection):

- ✅ Good: "Validates API responses against JSON schema"
- ❌ Bad: "A tool that can be used to validate APIs"

**description_long** (detailed explanation):

- Include: What it does, when to use it, key parameters, output format
- Example: "Checks if the current page title matches the expected pattern. Supports regex for flexible matching. Returns \[SUCCESS\] on match, \[FAILURE\] with recovery hints on mismatch."

**examples** (JSON format for LLM):

```python
examples=[
    '{"action": "check_page_title", "params": {"expected_title": "Dashboard"}}',
    '{"action": "check_page_title", "params": {"expected_title": "Product.*", "case_sensitive": true}}'
]
```

**use_when** (positive hints for LLM):

```python
use_when=[
    "After navigation to verify correct page loaded",
    "During form submission to check redirect success",
    "In SPAs to confirm route changes"
]
```

**dont_use_when** (negative hints to prevent misuse):

```python
dont_use_when=[
    "For content verification (use assertions instead)",
    "When title is dynamic/unpredictable"
]
```

______________________________________________________________________

## REFERENCE: Base Classes API

### WebQABaseTool Methods

#### Response Formatting

**`format_success(message: str, **context) -> str`**

- Returns: `"[SUCCESS] {message}"`
- Optional context: `dom_diff`, `page_state`

**`format_failure(message: str, recovery_hints: List[str] = None) -> str`**

- Returns: `"[FAILURE] {message}"`
- Triggers adaptive recovery when enabled

**`format_critical_error(error_type: str, message: str) -> str`**

- Returns: `"[CRITICAL_ERROR:{error_type}] {message}"`
- Causes immediate test abort
- Valid error_type values: ELEMENT_NOT_FOUND, NAVIGATION_FAILED, PERMISSION_DENIED, PAGE_CRASHED, NETWORK_ERROR, SESSION_EXPIRED, UNSUPPORTED_PAGE, VALIDATION_ERROR

**`format_warning(message: str) -> str`**

- Returns: `"[WARNING] {message}"`
- Non-blocking issue logging

**`format_cannot_verify(message: str, reason: str) -> str`**

- Returns: `"[CANNOT_VERIFY] {message}. Reason: {reason}"`
- Verification prerequisite failed

#### Context Management

**`update_action_context(ui_tester: Any, context: Dict[str, Any]) -> None`**

- Updates `ui_tester.last_action_context` for downstream tools
- Recommended for action category tools

**`get_execution_context(ui_tester: Any) -> Optional[Dict[str, Any]]`**

- Returns context from previous actions
- Used by assertion tools for context-aware verification

### WebQAToolMetadata Fields

```python
WebQAToolMetadata(
    name="tool_name_snake",           # Required: Tool identifier
    category="custom",                # action, assertion, ux, custom
    step_type="custom_tool_name",    # For planning prompts
    description_short="One line",     # Brief description
    description_long="Detailed",      # Full description with examples
    examples=["JSON example"],        # Usage examples
    use_when=["scenario 1"],          # When to use hints
    dont_use_when=["anti-pattern"],   # When NOT to use
    priority=55,                      # 1-100 priority
    dependencies=["package"],         # Python package dependencies
)
```

______________________________________________________________________

## CODEBASE REFERENCE

### Key Files to Reference

**Base Classes**: `webqa_agent/testers/case_gen/tools/base.py:1-519`

- `WebQABaseTool`, `WebQAToolMetadata`, `ResponseTags`, `ActionTypes`

**Registry**: `webqa_agent/testers/case_gen/tools/registry.py`

- Singleton pattern, auto-discovery, dependency checking

**Element Actions**: `webqa_agent/testers/case_gen/tools/element_action_tool.py`

- Reference for browser interaction patterns

**Custom Tool Example**: `webqa_agent/testers/case_gen/tools/custom/link_detection_tool.py`

- Real-world custom tool implementation

### Import Patterns

```python
# Standard imports for all tools
from typing import Any, Type, Dict, List, Optional
from pydantic import BaseModel, Field
from webqa_agent.testers.case_gen.tools.base import (
    WebQABaseTool,
    WebQAToolMetadata,
    ResponseTags,
)
from webqa_agent.testers.case_gen.tools.registry import register_tool

# Browser interactions
from playwright.async_api import Page, Error as PlaywrightError

# JSON handling
import json
from datetime import datetime

# Logging
import logging
logger = logging.getLogger(__name__)
```

______________________________________________________________________

## FINAL CHECKLIST

Before completing tool development, verify:

- [ ] Class inherits from `WebQABaseTool`
- [ ] `@register_tool` decorator present
- [ ] `async def _arun()` implemented (not sync `_run`)
- [ ] All returns use response formatting helpers
- [ ] `get_metadata()` returns complete `WebQAToolMetadata`
- [ ] Parameter schema defined with Pydantic `BaseModel`
- [ ] Dependencies declared in metadata
- [ ] Action context updated (for action tools)
- [ ] Docstrings on class and methods
- [ ] Unit tests written
- [ ] Integration test config created
- [ ] Code formatted with black/isort
- [ ] No flake8 warnings
- [ ] Tool registered successfully (verification script passes)
- [ ] HTML report includes tool outputs (if using case_recorder)

______________________________________________________________________

## CONTEXT COMPLETENESS NOTE

This document provides comprehensive context for LLM-assisted custom tool development. When generating tools:

1. **Reference Templates**: Use exact code templates provided above
2. **Follow Constraints**: Adhere to ALL mandatory requirements
3. **Avoid Anti-Patterns**: Check error patterns section before coding
4. **Test Thoroughly**: Follow verification checklist
5. **Ask Questions**: If requirements are unclear, ask user for clarification

**Goal**: Generate correctly implemented, production-ready custom tools that integrate seamlessly with WebQA Agent's LangGraph workflow without hallucinations or common errors.

______________________________________________________________________

**END OF LLM CONTEXT DOCUMENT**
