# Custom Tool Development

Quick reference for creating custom WebQA Agent tools.

## Quick Start

Minimal working example:

```python
from typing import Any, Type
from pydantic import BaseModel, Field
from webqa_agent.testers.case_gen.tools.base import (
    WebQABaseTool,
    WebQAToolMetadata,
)
from webqa_agent.testers.case_gen.tools.registry import register_tool

class HelloToolSchema(BaseModel):
    message: str = Field(description="Message to display")

@register_tool
class HelloTool(WebQABaseTool):
    name: str = "hello_world"
    description: str = "Prints a greeting message"
    args_schema: Type[BaseModel] = HelloToolSchema

    ui_tester_instance: Any = Field(...)

    @classmethod
    def get_metadata(cls):
        return WebQAToolMetadata(
            name="hello_world",
            category="custom",
            description_short="Simple greeting tool",
        )

    async def _arun(self, message: str) -> str:
        return self.format_success(f"Hello, {message}!")
```

Test: `webqa-agent gen -c config.yaml`

## Core Components

**Base Classes**:

- `WebQABaseTool` - Base class for all tools
- `WebQAToolMetadata` - Tool metadata
- `ResponseTags` - Response tags (SUCCESS, FAILURE, CRITICAL_ERROR:TYPE)
- `ToolRegistry` - Tool registration system

**Required Methods**:

- `get_metadata()` - Tool metadata (classmethod)
- `_arun()` - Async execution (MUST be async, NOT sync `_run`)

**Response Helpers**:

- `format_success(msg)` - Return success
- `format_failure(msg, hints)` - Recoverable error
- `format_critical_error(type, msg)` - Abort test
- `format_warning(msg)` - Non-blocking issue
- `format_cannot_verify(msg, reason)` - Verification failed

## File Structure

```
webqa_agent/testers/case_gen/tools/
├── base.py              # Base classes
├── registry.py          # Registration system
├── custom/              # Your tools here
│   └── my_tool.py
└── __init__.py

tests/custom_tools/
└── test_my_tool.py      # Your tests
```

## API Reference

### WebQABaseTool

```python
from webqa_agent.testers.case_gen.tools.base import WebQABaseTool

class MyTool(WebQABaseTool):
    name: str = "my_tool"
    description: str = "Tool description"
    args_schema: Type[BaseModel] = MyToolSchema
    ui_tester_instance: Any = Field(...)

    @classmethod
    def get_metadata(cls) -> WebQAToolMetadata:
        return WebQAToolMetadata(...)

    async def _arun(self, **kwargs) -> str:
        return self.format_success("Done")
```

### WebQAToolMetadata

```python
WebQAToolMetadata(
    name="my_tool",
    category="custom",  # action, assertion, ux, custom
    step_type="my_tool",
    description_short="Brief description",
    description_long="Detailed description with examples",
    examples=['{"action": "my_tool", "params": {...}}'],
    use_when=["When to use"],
    dont_use_when=["When NOT to use"],
    priority=55,  # 1-100 (core: 70-90, custom: 30-60)
    dependencies=["package1", "package2"]
)
```

### ResponseTags

**Success/Failure**:

- `[SUCCESS]` - Continue to next step
- `[FAILURE]` - Trigger adaptive recovery (if enabled)
- `[WARNING]` - Non-blocking issue
- `[CANNOT_VERIFY]` - Verification prerequisite failed

**Critical Errors** (abort test immediately):

- `[CRITICAL_ERROR:ELEMENT_NOT_FOUND]`
- `[CRITICAL_ERROR:NAVIGATION_FAILED]`
- `[CRITICAL_ERROR:PERMISSION_DENIED]`
- `[CRITICAL_ERROR:PAGE_CRASHED]`
- `[CRITICAL_ERROR:NETWORK_ERROR]`
- `[CRITICAL_ERROR:SESSION_EXPIRED]`
- `[CRITICAL_ERROR:UNSUPPORTED_PAGE]`
- `[CRITICAL_ERROR:VALIDATION_ERROR]`

## Common Mistakes

1. **Forgot ResponseTag**: Must use `format_success/failure/critical_error`

   ```python
   # Wrong
   return "Operation completed"

   # Correct
   return self.format_success("Operation completed")
   ```

2. **Sync method**: Use `async def _arun`, NOT `def _run`

   ```python
   # Wrong
   def _run(self, param: str):
       return self.format_success("Done")

   # Correct
   async def _arun(self, param: str):
       return self.format_success("Done")
   ```

3. **No @register_tool**: Tool won't be discovered

   ```python
   # Wrong
   class MyTool(WebQABaseTool):
       ...

   # Correct
   @register_tool
   class MyTool(WebQABaseTool):
       ...
   ```

4. **Missing dependencies**: Declare in `get_metadata().dependencies`

   ```python
   dependencies=["aiohttp", "beautifulsoup4"]
   ```

5. **JSON serialization**: Convert exceptions to strings for `case_recorder`

   ```python
   model_io=json.dumps({'error': str(exception)}, ensure_ascii=False)
   ```

## Context Management

**Update context** (for action tools):

```python
async def _arun(self, param: str) -> str:
    from datetime import datetime
    result = await self._execute(param)

    self.update_action_context(
        self.ui_tester_instance,
        {
            'description': 'Executed action',
            'action_type': 'MyAction',
            'status': 'success',
            'result': result,
            'timestamp': datetime.now().isoformat(),
        }
    )

    return self.format_success("Done")
```

**Read context** (for assertion tools):

```python
async def _arun(self, ...) -> str:
    context = self.get_execution_context(self.ui_tester_instance)
    if context:
        previous_data = context['last_action']['result']
        # Use previous_data
```

## Advanced Features

**Access LLM config**:

```python
@classmethod
def get_required_params(cls) -> Dict[str, str]:
    return {
        'ui_tester_instance': 'ui_tester_instance',
        'llm_config': 'llm_config',
        'case_recorder': 'case_recorder',
    }

async def _arun(self, param: str) -> str:
    model = self.llm_config.get('model', 'gpt-4')
    # Adjust behavior based on model
```

**Record to HTML report**:

```python
if self.case_recorder:
    self.case_recorder.add_step(
        description="Custom operation",
        model_io=json.dumps({'input': param, 'output': result}, ensure_ascii=False),
        status='passed',
        step_type='action',
    )
```

## Verification

```bash
# Check registration
python -c "from webqa_agent.testers.case_gen.tools.registry import get_registry; print('my_tool' in get_registry().get_tool_names())"

# Run tests
pytest tests/custom_tools/test_my_tool.py -v

# Format & lint
black webqa_agent/ && isort webqa_agent/ && flake8 webqa_agent/testers/case_gen/tools/custom/my_tool.py
```

## Configuration Example

To use your custom tool:

1. Place your tool in `webqa_agent/testers/case_gen/tools/custom/`
2. Decorate with `@register_tool` - the LLM will automatically discover it
3. Configure your test with business objectives

**Important**: In AI mode (`type: ai`), test steps are NOT defined in YAML. The LLM automatically generates test steps based on `business_objectives` and selects tools based on their descriptions and metadata.

```yaml
# config/config.yaml
target:
  url: https://example.com
  description: Test custom functionality

# Test Configuration - NO test_steps in AI mode!
test_config:
  function_test:
    enabled: true
    type: "ai"  # AI mode - LLM generates test steps
    business_objectives: "Test custom functionality using my_tool"
    dynamic_step_generation:
      enabled: true  # Enable adaptive recovery
      max_dynamic_steps: 10
      min_elements_threshold: 1

# LLM Configuration
llm_config:
  model: claude-sonnet-4-5-20250929  # Or gpt-4, gemini-2.5-flash-lite
  api_key: ${ANTHROPIC_API_KEY}  # Use environment variable
  temperature: 1.0  # Required for Claude Extended Thinking
  max_tokens: 20000  # Must be larger than reasoning.budget_tokens

# Browser Configuration
browser_config:
  headless: false  # Set to true for CI/CD
  viewport: {width: 1280, height: 720}
  language: en-US
```

**How the LLM selects your tool**:

- LLM reads tool `description` and `get_metadata()` output
- Chooses tools based on `use_when` hints and current page context
- Your tool is invoked when LLM determines it's appropriate for the test objective

**Configuration Tips**:

- Use environment variables for API keys (never commit credentials)
- Adjust `temperature` based on your model (OpenAI: 0.1, Anthropic/Gemini: 1.0)
- Set `headless: true` in Docker/CI environments

## Real-World Example

Page title checker:

```python
import re
from typing import Any, Type
from pydantic import BaseModel, Field
from webqa_agent.testers.case_gen.tools.base import (
    WebQABaseTool,
    WebQAToolMetadata,
)
from webqa_agent.testers.case_gen.tools.registry import register_tool

class TitleCheckerSchema(BaseModel):
    expected_title: str = Field(description="Expected page title pattern (regex)")
    case_sensitive: bool = Field(default=False, description="Case-sensitive matching")

@register_tool
class TitleCheckerTool(WebQABaseTool):
    name: str = "check_page_title"
    description: str = "Validates page title"
    args_schema: Type[BaseModel] = TitleCheckerSchema
    ui_tester_instance: Any = Field(...)

    @classmethod
    def get_metadata(cls):
        return WebQAToolMetadata(
            name="check_page_title",
            category="custom",
            step_type="check_page_title",
            description_short="Validates page title against pattern",
            examples=[
                '{"action": "check_page_title", "params": {"expected_title": "Dashboard"}}',
            ],
            use_when=["After navigation", "In SPAs"],
            priority=55,
        )

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

## See Also

- `webqa_agent/testers/case_gen/tools/base.py` - Base classes
- `webqa_agent/testers/case_gen/tools/element_action_tool.py` - UITool reference
- `webqa_agent/testers/case_gen/tools/custom/link_detection_tool.py` - Custom tool example
- `webqa_agent/testers/case_gen/tools/registry.py` - Tool registry
