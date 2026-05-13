# Agent Step Boundary Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix planning hallucination (file names), preamble over-execution (shared system prompt + executor), and main step over-execution (unanchored step messages).

**Architecture:** Four coordinated changes: (1) planning prompt receives actual file catalog instead of boolean; (2) new lean preamble system prompt + executor factory creates three isolated executor profiles; (3) step-type-aware message templates replace unanchored rotating templates. All changes are L1/L2 soft enforcement with interfaces reserved for L3–L5 hardening.

**Tech Stack:** LangChain AgentExecutor, ChatPromptTemplate, LangGraph state, Python 3.11

______________________________________________________________________

## File Structure

| File                                               | Change       | Responsibility                                                                               |
| -------------------------------------------------- | ------------ | -------------------------------------------------------------------------------------------- |
| `webqa_agent/prompts/test_planning_prompts.py`     | Modify       | `has_test_files: bool` → `file_catalog: str`; inject actual filenames into planning prompt   |
| `webqa_agent/prompts/agent_execution_prompts.py`   | Add function | `get_preamble_system_prompt()` — lean prompt excluding test objective                        |
| `webqa_agent/executor/gen/agents/execute_agent.py` | Refactor     | `_create_agent_executor()` factory + 3 executor profiles + `STEP_MESSAGE_TEMPLATES` constant |
| `webqa_agent/executor/gen/graph.py`                | Modify       | Pass `file_catalog` string to planning prompt instead of boolean                             |
| `tests/test_planning_prompts.py`                   | Create       | Tests for file_catalog injection                                                             |
| `tests/test_agent_execution_prompts.py`            | Create       | Tests for preamble prompt exclusions                                                         |
| `tests/test_execute_agent_boundary.py`             | Create       | Tests for factory function and step templates                                                |

______________________________________________________________________

## Background: Key Code Locations

Before starting, read these sections to orient yourself:

- `webqa_agent/prompts/test_planning_prompts.py:739-753` — `get_test_case_planning_system_prompt` signature (the `has_test_files` param to replace)
- `webqa_agent/prompts/test_planning_prompts.py:1005-1014` — `if has_test_files:` block to replace
- `webqa_agent/prompts/test_planning_prompts.py:1204-1238` — `get_planning_prompt` (outer wrapper, also has `has_test_files`)
- `webqa_agent/executor/gen/graph.py:373-383` — call site passing `has_test_files=...`
- `webqa_agent/prompts/agent_execution_prompts.py:641-648` — end of `get_execute_system_prompt` (add `get_preamble_system_prompt` after this)
- `webqa_agent/executor/gen/agents/execute_agent.py:63-64` — imports from agent_execution_prompts (add `get_preamble_system_prompt`)
- `webqa_agent/executor/gen/agents/execute_agent.py:74` — blank line before `agent_worker_node` (add factory + constant here)
- `webqa_agent/executor/gen/agents/execute_agent.py:121-137` — system_prompt_string setup (preamble prompt created from here)
- `webqa_agent/executor/gen/agents/execute_agent.py:251-267` — existing single executor creation (replace with factory calls)
- `webqa_agent/executor/gen/agents/execute_agent.py:456` — preamble `agent_executor.ainvoke` (change to `preamble_executor`)
- `webqa_agent/executor/gen/agents/execute_agent.py:679` — `step_type = parse_step_type(step)` (add executor selection after this block)
- `webqa_agent/executor/gen/agents/execute_agent.py:723-734` — `instruction_templates` list (replace with `STEP_MESSAGE_TEMPLATES` lookup)
- `webqa_agent/executor/gen/agents/execute_agent.py:841` — main step `agent_executor.ainvoke` (change to `current_executor`)

`parse_step_type()` returns `'Action'` for action steps, `'Assertion'` for verify steps, `'UX_Verify'` for ux_verify steps. Use these exact strings as `STEP_MESSAGE_TEMPLATES` keys.

______________________________________________________________________

### Task 1: Planning Prompt — Inject Actual File Names

**Files:**

- Modify: `webqa_agent/prompts/test_planning_prompts.py:739-753` (signature + docstring)

- Modify: `webqa_agent/prompts/test_planning_prompts.py:1005-1014` (upload section)

- Modify: `webqa_agent/prompts/test_planning_prompts.py:1204-1238` (outer wrapper)

- Modify: `webqa_agent/executor/gen/graph.py:382`

- Create: `tests/test_planning_prompts.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_planning_prompts.py`:

```python
"""Tests for planning prompt file catalog injection."""

import pytest

from webqa_agent.prompts.test_planning_prompts import (
    get_planning_prompt,
    get_test_case_planning_system_prompt,
)

SAMPLE_CATALOG = (
    '- /test/bench.pdf (application/pdf, 1024 bytes, document)\n'
    '- /test/bench.docx (application/vnd.openxmlformats-officedocument, 512 bytes, document)\n'
    '\nIMPORTANT: Use the FULL path as shown above.'
)


def test_planning_system_prompt_injects_catalog_filenames():
    """System prompt must contain actual filenames when catalog is provided."""
    sys_prompt, _ = get_planning_prompt(
        business_objectives='test upload',
        state_url='http://example.com',
        file_catalog=SAMPLE_CATALOG,
    )
    assert 'bench.pdf' in sys_prompt
    assert '/test/bench.pdf' in sys_prompt


def test_planning_system_prompt_empty_catalog_omits_upload_section():
    """No catalog means no upload instructions in system prompt."""
    sys_prompt, _ = get_planning_prompt(
        business_objectives='test',
        state_url='http://example.com',
        file_catalog='',
    )
    assert 'Do NOT invent filenames' not in sys_prompt


def test_planning_system_prompt_with_catalog_forbids_invented_names():
    """Upload section must explicitly instruct LLM not to invent filenames."""
    sys_prompt, _ = get_planning_prompt(
        business_objectives='test upload',
        state_url='http://example.com',
        file_catalog=SAMPLE_CATALOG,
    )
    assert 'Do NOT invent filenames' in sys_prompt


def test_get_test_case_planning_system_prompt_with_catalog():
    """Inner function receives and injects file_catalog."""
    prompt = get_test_case_planning_system_prompt(
        business_objectives='test',
        file_catalog=SAMPLE_CATALOG,
    )
    assert 'bench.pdf' in prompt
    assert 'Do NOT invent filenames' in prompt


def test_get_test_case_planning_system_prompt_without_catalog():
    """No catalog → no File Upload Testing section."""
    prompt = get_test_case_planning_system_prompt(
        business_objectives='test',
        file_catalog='',
    )
    assert 'File Upload Testing' not in prompt
```

- [ ] **Step 2: Run failing tests**

```bash
uv run pytest tests/test_planning_prompts.py -v
```

Expected: FAIL — `TypeError: get_planning_prompt() got an unexpected keyword argument 'file_catalog'`

- [ ] **Step 3: Rename `has_test_files` to `file_catalog: str` in `get_test_case_planning_system_prompt`**

In `webqa_agent/prompts/test_planning_prompts.py`, change the function at line 739:

```python
# Before (lines 739-753)
def get_test_case_planning_system_prompt(
    business_objectives: str,
    language: str = 'zh-CN',
    enabled_custom_tools: list[str] | None = None,
    has_test_files: bool = False,
) -> str:
    """Generate system prompt for test case planning.

    Args:
        business_objectives: Business objectives
        language: Language for test case naming (zh-CN or en-US)
        enabled_custom_tools: List of enabled custom tool step_types to include.
                            If None, includes all custom tools.
        has_test_files: Whether test files are configured for upload testing.
    ...
    """

# After (lines 739-753)
def get_test_case_planning_system_prompt(
    business_objectives: str,
    language: str = 'zh-CN',
    enabled_custom_tools: list[str] | None = None,
    file_catalog: str = '',
) -> str:
    """Generate system prompt for test case planning.

    Args:
        business_objectives: Business objectives
        language: Language for test case naming (zh-CN or en-US)
        enabled_custom_tools: List of enabled custom tool step_types to include.
                            If None, includes all custom tools.
        file_catalog: Formatted file catalog string from TestFileLibrary.get_catalog_for_llm().
                     Empty string means no test files configured.
    ...
    """
```

- [ ] **Step 4: Replace the `if has_test_files:` upload block**

In the same file, replace lines 1005–1014:

```python
# Before
    if has_test_files:
        system_prompt += """

## File Upload Testing
When you identify file upload controls (input[type="file"]) on the page:
- Include upload actions in your test steps with natural language descriptions
- Example step: "Upload a PDF resume to the file upload area"
- The agent will automatically select appropriate files during execution
- Consider testing: successful file upload, verify uploaded filename appears on page
"""

# After
    if file_catalog:
        system_prompt += f"""

## File Upload Testing
When you identify file upload controls (input[type="file"]) on the page:
- Include upload test steps using only filenames from the available test files below
- Do NOT invent filenames; use only files from the list below
- Example step format: "Upload bench.pdf to the file upload area"
- Consider testing: successful upload, verify the filename appears on page

Available test files:
{file_catalog}
"""
```

- [ ] **Step 5: Update `get_planning_prompt` wrapper function**

Replace lines 1204–1238:

```python
# Before
def get_planning_prompt(
    business_objectives: str,
    state_url: str,
    language: str = 'zh-CN',
    page_text_summary: dict = None,
    priority_elements: dict = None,
    all_page_links: list = None,
    navigation_map: dict = None,
    enabled_custom_tools: list[str] | None = None,
    has_test_files: bool = False,
) -> tuple[str, str]:
    """Generate prompts for planning (returns system and user prompt).

    Args:
        ...
        has_test_files: Whether test files are configured for upload testing.
    ...
    """
    system_prompt = get_test_case_planning_system_prompt(
        business_objectives, language, enabled_custom_tools, has_test_files
    )

# After
def get_planning_prompt(
    business_objectives: str,
    state_url: str,
    language: str = 'zh-CN',
    page_text_summary: dict = None,
    priority_elements: dict = None,
    all_page_links: list = None,
    navigation_map: dict = None,
    enabled_custom_tools: list[str] | None = None,
    file_catalog: str = '',
) -> tuple[str, str]:
    """Generate prompts for planning (returns system and user prompt).

    Args:
        ...
        file_catalog: Formatted file catalog string from TestFileLibrary.get_catalog_for_llm().
                     Empty string means no test files configured.
    ...
    """
    system_prompt = get_test_case_planning_system_prompt(
        business_objectives, language, enabled_custom_tools, file_catalog
    )
```

- [ ] **Step 6: Update the call site in `graph.py`**

In `webqa_agent/executor/gen/graph.py`, replace line 382:

```python
# Before (lines 373–383)
        system_prompt, user_prompt = get_planning_prompt(
            business_objectives=enhanced_business_objectives,
            state_url=state['url'],
            language=language,
            page_text_summary=page_text_summary,
            all_page_links=all_page_links,
            navigation_map=navigation_map,
            enabled_custom_tools=enabled_custom_tools,
            has_test_files=state.get('test_file_library') is not None,
        )

# After
        _lib = state.get('test_file_library')
        system_prompt, user_prompt = get_planning_prompt(
            business_objectives=enhanced_business_objectives,
            state_url=state['url'],
            language=language,
            page_text_summary=page_text_summary,
            all_page_links=all_page_links,
            navigation_map=navigation_map,
            enabled_custom_tools=enabled_custom_tools,
            file_catalog=_lib.get_catalog_for_llm() if _lib else '',
        )
```

- [ ] **Step 7: Run tests — expect pass**

```bash
uv run pytest tests/test_planning_prompts.py -v
```

Expected: 5 PASSED

- [ ] **Step 8: Run full test suite**

```bash
uv run pytest tests/ -v --ignore=tests/test_crawler.py
```

Expected: all existing tests still pass

- [ ] **Step 9: Commit**

```bash
git add webqa_agent/prompts/test_planning_prompts.py \
        webqa_agent/executor/gen/graph.py \
        tests/test_planning_prompts.py
git commit -m "fix(planning): inject actual file catalog into planning prompt

Replace has_test_files boolean with file_catalog string so the planning
LLM sees actual filenames (e.g. bench.pdf) instead of inventing them.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

______________________________________________________________________

### Task 2: Preamble System Prompt

**Files:**

- Modify: `webqa_agent/prompts/agent_execution_prompts.py` (add function after line 648)

- Create: `tests/test_agent_execution_prompts.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_agent_execution_prompts.py`:

```python
"""Tests for agent execution prompt functions."""

import pytest

from webqa_agent.prompts.agent_execution_prompts import (
    get_execute_system_prompt,
    get_preamble_system_prompt,
)

MINIMAL_CASE = {
    'objective': 'Test upload functionality',
    'success_criteria': ['File uploaded successfully'],
}


def test_preamble_prompt_excludes_test_objective():
    """Preamble prompt must not expose the test objective to prevent over-execution."""
    prompt = get_preamble_system_prompt(language='zh-CN')
    # The word 'objective' itself should not appear (it drives over-execution)
    assert 'objective' not in prompt.lower()
    assert 'success_criteria' not in prompt


def test_preamble_prompt_excludes_success_criteria():
    """Preamble prompt must not contain success criteria."""
    prompt = get_preamble_system_prompt(language='zh-CN')
    assert 'success criteria' not in prompt.lower()
    assert 'success_criteria' not in prompt


def test_preamble_prompt_excludes_file_upload_instructions():
    """Preamble prompt must not mention available test files."""
    prompt = get_preamble_system_prompt(language='zh-CN')
    assert 'Available test files' not in prompt
    assert 'file_catalog' not in prompt


def test_preamble_prompt_contains_scope_constraint_zh():
    """zh-CN preamble must contain explicit scope constraint language."""
    prompt = get_preamble_system_prompt(language='zh-CN')
    # Must contain scoping language in Chinese
    assert '仅限' in prompt or '不要追求' in prompt


def test_preamble_prompt_contains_scope_constraint_en():
    """en-US preamble must contain explicit scope constraint language."""
    prompt = get_preamble_system_prompt(language='en-US')
    assert 'ONLY' in prompt or 'only' in prompt


def test_preamble_prompt_is_shorter_than_execute_prompt():
    """Preamble prompt must be significantly leaner than full execute prompt."""
    preamble = get_preamble_system_prompt()
    execute = get_execute_system_prompt(MINIMAL_CASE)
    assert len(preamble) < len(execute) * 0.5


def test_preamble_prompt_returns_string():
    """Function must return a non-empty string for both languages."""
    assert isinstance(get_preamble_system_prompt('zh-CN'), str)
    assert len(get_preamble_system_prompt('zh-CN')) > 100
    assert isinstance(get_preamble_system_prompt('en-US'), str)
    assert len(get_preamble_system_prompt('en-US')) > 100
```

- [ ] **Step 2: Run failing tests**

```bash
uv run pytest tests/test_agent_execution_prompts.py -v
```

Expected: FAIL — `ImportError: cannot import name 'get_preamble_system_prompt'`

- [ ] **Step 3: Add `get_preamble_system_prompt` to `agent_execution_prompts.py`**

Add after the `get_execute_system_prompt` function (after line 648, before `get_file_upload_context`):

```python
def get_preamble_system_prompt(language: str = 'zh-CN') -> str:
    """Lean system prompt for preamble execution.

    Intentionally excludes: objective, success_criteria, file_catalog, business_context.
    Includes: role definition, browser environment, scope constraint, language directive.

    Args:
        language: Language for output instructions ('zh-CN' or 'en-US').

    Returns:
        Formatted system prompt string.
    """
    output_lang_instruction = (
        '**请你注意，所有输出内容均使用中文。**'
        if language == 'zh-CN'
        else '**All output must be in English.**'
    )

    return f"""You are a UI operator responsible for executing pre-test preparation actions (preamble actions).

## Browser Environment

**Browser Mode**: Single-tab only. All navigation occurs in the current tab. Use the `GoBack` action to return to previous pages in browser history.

**Automatic Viewport Management**: The system automatically scrolls elements into view before interactions. You do NOT need to manually scroll to elements — simply reference them by their identifiers.

**Screenshot Context**: Screenshots show only the current viewport. The viewport management system ensures elements are scrolled into view before any action executes.

## Scope Constraint

Your ONLY responsibility is to execute the preparation action(s) specified in the current message.

- Execute ONLY the specified preparation action (e.g., close a dialog, navigate to a URL)
- 你的任务仅限于当前指派的准备动作
- Do NOT pursue any test objectives or success criteria
- 不要追求任何测试目标，不要尝试验证功能
- Do NOT upload files or verify test outcomes
- Do NOT continue to main test steps after completing the preparation
- Report the result after completing the preparation action and stop immediately

## Quality Standards

{output_lang_instruction}
- Execute exactly what is specified, nothing more
- Stop immediately after completing the preparation action
"""
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/test_agent_execution_prompts.py -v
```

Expected: 7 PASSED

- [ ] **Step 5: Run full suite**

```bash
uv run pytest tests/ -v --ignore=tests/test_crawler.py
```

Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add webqa_agent/prompts/agent_execution_prompts.py \
        tests/test_agent_execution_prompts.py
git commit -m "feat(prompts): add get_preamble_system_prompt for isolated preamble execution

Lean prompt excludes objective, success_criteria, file_catalog to prevent
preamble agent from pursuing test goals beyond its preparation scope.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

______________________________________________________________________

### Task 3: Executor Factory + Three Profiles

**Files:**

- Modify: `webqa_agent/executor/gen/agents/execute_agent.py`

  - Line 14: add `Any` to typing imports
  - Line 63-64: add `get_preamble_system_prompt` to import
  - Before line 75: add `_create_agent_executor` function
  - Lines 251-267: replace single executor with three profiles
  - Line 456: change `agent_executor` → `preamble_executor`
  - After line 693: add executor selection (`current_executor`)
  - Line 841: change `agent_executor` → `current_executor`

- Create: `tests/test_execute_agent_boundary.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_execute_agent_boundary.py`:

```python
"""Tests for agent executor factory and step boundary enforcement."""

from unittest.mock import MagicMock, call, patch

import pytest


def test_create_agent_executor_sets_max_iterations():
    """Factory must create AgentExecutor with the specified max_iterations."""
    with patch(
        'webqa_agent.executor.gen.agents.execute_agent.create_tool_calling_agent'
    ) as mock_create, patch(
        'webqa_agent.executor.gen.agents.execute_agent.AgentExecutor'
    ) as mock_executor_cls:
        mock_create.return_value = MagicMock()
        mock_executor_cls.return_value = MagicMock()

        from webqa_agent.executor.gen.agents.execute_agent import _create_agent_executor

        _create_agent_executor(MagicMock(), [], 'test prompt', max_iterations=3)

        mock_executor_cls.assert_called_once_with(
            agent=mock_create.return_value,
            tools=[],
            verbose=False,
            max_iterations=3,
            return_intermediate_steps=True,
        )


def test_create_agent_executor_default_max_iterations_is_five():
    """Default max_iterations must be 5."""
    with patch(
        'webqa_agent.executor.gen.agents.execute_agent.create_tool_calling_agent'
    ) as mock_create, patch(
        'webqa_agent.executor.gen.agents.execute_agent.AgentExecutor'
    ) as mock_executor_cls:
        mock_create.return_value = MagicMock()
        mock_executor_cls.return_value = MagicMock()

        from webqa_agent.executor.gen.agents.execute_agent import _create_agent_executor

        _create_agent_executor(MagicMock(), [], 'test prompt')

        mock_executor_cls.assert_called_once_with(
            agent=mock_create.return_value,
            tools=[],
            verbose=False,
            max_iterations=5,
            return_intermediate_steps=True,
        )
```

- [ ] **Step 2: Run failing tests**

```bash
uv run pytest tests/test_execute_agent_boundary.py::test_create_agent_executor_sets_max_iterations -v
```

Expected: FAIL — `ImportError: cannot import name '_create_agent_executor'`

- [ ] **Step 3: Add `Any` to typing imports (line 14)**

```python
# Before
from typing import Dict, List, Optional, Set

# After
from typing import Any, Dict, List, Optional, Set
```

- [ ] **Step 4: Add `get_preamble_system_prompt` to the agent_execution_prompts import (lines 63-64)**

```python
# Before
from webqa_agent.prompts.agent_execution_prompts import (
    get_execute_system_prompt, get_file_upload_context)

# After
from webqa_agent.prompts.agent_execution_prompts import (
    get_execute_system_prompt, get_file_upload_context, get_preamble_system_prompt)
```

- [ ] **Step 5: Add `_create_agent_executor` factory before `agent_worker_node` (at line 74)**

Insert after the blank line at line 73, before `agent_worker_node`:

```python
def _create_agent_executor(
    llm: Any,
    tools: list,
    system_prompt: str,
    max_iterations: int = 5,
) -> AgentExecutor:
    """Create a configured AgentExecutor bound to the given system prompt.

    Args:
        llm: LangChain chat model instance.
        tools: List of LangChain tools to bind.
        system_prompt: System prompt string for this executor profile.
        max_iterations: Maximum ReAct loop iterations (default 5).

    Returns:
        Configured AgentExecutor instance.
    """
    prompt = ChatPromptTemplate.from_messages([
        ('system', system_prompt),
        MessagesPlaceholder(variable_name='messages'),
        MessagesPlaceholder(variable_name='agent_scratchpad'),
    ])
    agent = create_tool_calling_agent(llm, tools, prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=False,
        max_iterations=max_iterations,
        return_intermediate_steps=True,
    )

```

- [ ] **Step 6: Run factory tests — expect pass**

```bash
uv run pytest tests/test_execute_agent_boundary.py -v
```

Expected: 2 PASSED

- [ ] **Step 7: Replace single executor with three profiles (lines 251-267)**

```python
# Before (lines 251-267)
    prompt = ChatPromptTemplate.from_messages(
        [
            ('system', system_prompt_string),
            MessagesPlaceholder(variable_name='messages'),
            MessagesPlaceholder(variable_name='agent_scratchpad'),
        ]
    )

    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=False,
        max_iterations=5,
        return_intermediate_steps=True,
    )
    logging.debug('AgentExecutor created successfully')

# After
    preamble_system_prompt_str = get_preamble_system_prompt(language=language)
    preamble_executor = _create_agent_executor(
        llm, tools, preamble_system_prompt_str, max_iterations=3
    )
    action_executor = _create_agent_executor(
        llm, tools, system_prompt_string, max_iterations=5
    )
    verify_executor = _create_agent_executor(
        llm, tools, system_prompt_string, max_iterations=3
    )
    logging.debug('AgentExecutor profiles created (preamble=3, action=5, verify=3)')
```

- [ ] **Step 8: Update preamble `ainvoke` call (line 456)**

```python
# Before
                result = await agent_executor.ainvoke(
                    {'messages': preamble_messages}
                )

# After
                result = await preamble_executor.ainvoke(
                    {'messages': preamble_messages}
                )
```

- [ ] **Step 9: Add executor selection in main step loop**

After the `step_type` is finalised (after the custom tool branch around line 693), add:

```python
        # Select executor by step type: verify/ux_verify → max_iterations=3; action → 5
        current_executor = (
            verify_executor if step_type in ('Assertion', 'UX_Verify') else action_executor
        )
```

- [ ] **Step 10: Update main step `ainvoke` call (line 841)**

```python
# Before
                result = await asyncio.wait_for(
                    agent_executor.ainvoke(
                        {'messages': pruned_messages},
                    ),
                    timeout=step_timeout,
                )

# After
                result = await asyncio.wait_for(
                    current_executor.ainvoke(
                        {'messages': pruned_messages},
                    ),
                    timeout=step_timeout,
                )
```

- [ ] **Step 11: Run full test suite**

```bash
uv run pytest tests/ -v --ignore=tests/test_crawler.py
```

Expected: all tests pass (including the 2 new factory tests)

- [ ] **Step 12: Commit**

```bash
git add webqa_agent/executor/gen/agents/execute_agent.py \
        tests/test_execute_agent_boundary.py
git commit -m "refactor(executor): factory function + three executor profiles for step boundary

- _create_agent_executor() factory eliminates executor creation duplication
- preamble_executor: lean system prompt, max_iterations=3
- action_executor: full system prompt, max_iterations=5
- verify_executor: full system prompt, max_iterations=3
- Executor selection per step_type in main loop (Assertion/UX_Verify → verify_executor)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

______________________________________________________________________

### Task 4: Step-Aware Message Templates

**Files:**

- Modify: `webqa_agent/executor/gen/agents/execute_agent.py`

  - Before `_create_agent_executor` (line 74 area): add `STEP_MESSAGE_TEMPLATES` constant
  - Lines 723-734: replace `instruction_templates` list with `STEP_MESSAGE_TEMPLATES` lookup

- Modify: `tests/test_execute_agent_boundary.py` (add template tests)

- [ ] **Step 1: Write failing tests for templates**

Add to `tests/test_execute_agent_boundary.py`:

```python
def test_step_message_templates_has_required_keys():
    """Templates dict must cover all core step types."""
    from webqa_agent.executor.gen.agents.execute_agent import STEP_MESSAGE_TEMPLATES

    assert 'Action' in STEP_MESSAGE_TEMPLATES
    assert 'Assertion' in STEP_MESSAGE_TEMPLATES
    assert 'UX_Verify' in STEP_MESSAGE_TEMPLATES


def test_action_template_anchors_step_and_stops():
    """Action template must include step anchor and stop directive."""
    from webqa_agent.executor.gen.agents.execute_agent import STEP_MESSAGE_TEMPLATES

    formatted = STEP_MESSAGE_TEMPLATES['Action'].format(
        n=1, total=3, instruction='Click submit button'
    )
    assert '[步骤 1/3' in formatted
    assert 'Click submit button' in formatted
    # Stop directive present
    assert '不要主动继续' in formatted or '仅执行' in formatted


def test_assertion_template_prohibits_ui_actions():
    """Assertion (verify) template must explicitly forbid UI actions."""
    from webqa_agent.executor.gen.agents.execute_agent import STEP_MESSAGE_TEMPLATES

    formatted = STEP_MESSAGE_TEMPLATES['Assertion'].format(
        n=2, total=5, instruction='Verify file name visible'
    )
    assert '[步骤 2/5' in formatted
    assert '不要执行任何界面操作' in formatted


def test_ux_verify_template_prohibits_ui_actions():
    """UX_Verify template must explicitly forbid UI actions."""
    from webqa_agent.executor.gen.agents.execute_agent import STEP_MESSAGE_TEMPLATES

    formatted = STEP_MESSAGE_TEMPLATES['UX_Verify'].format(
        n=3, total=5, instruction='Check layout alignment'
    )
    assert '[步骤 3/5' in formatted
    assert '不要执行任何界面操作' in formatted


def test_unknown_step_type_falls_back_to_action_template():
    """Unknown step type (custom tools) must fall back to Action template."""
    from webqa_agent.executor.gen.agents.execute_agent import STEP_MESSAGE_TEMPLATES

    fallback = STEP_MESSAGE_TEMPLATES.get('SomeCustomTool', STEP_MESSAGE_TEMPLATES['Action'])
    assert fallback is STEP_MESSAGE_TEMPLATES['Action']
```

- [ ] **Step 2: Run failing tests**

```bash
uv run pytest tests/test_execute_agent_boundary.py -k "template" -v
```

Expected: FAIL — `ImportError: cannot import name 'STEP_MESSAGE_TEMPLATES'`

- [ ] **Step 3: Add `STEP_MESSAGE_TEMPLATES` constant before `_create_agent_executor`**

Insert before `_create_agent_executor` (at line 74, after imports):

```python
STEP_MESSAGE_TEMPLATES: dict[str, str] = {
    'Action': (
        '[步骤 {n}/{total} · 操作]\n'
        '{instruction}\n\n'
        '执行且仅执行上述操作。完成后立即报告结果，不要主动继续其他步骤。'
    ),
    'Assertion': (
        '[步骤 {n}/{total} · 验证]\n'
        '{instruction}\n\n'
        '仅验证上述条件，不要执行任何界面操作。报告验证结果后停止。'
    ),
    'UX_Verify': (
        '[步骤 {n}/{total} · UX验证]\n'
        '{instruction}\n\n'
        '仅评估上述视觉/体验条件，不要执行任何界面操作。报告评估结果后停止。'
    ),
}
```

- [ ] **Step 4: Run template tests — expect pass**

```bash
uv run pytest tests/test_execute_agent_boundary.py -k "template" -v
```

Expected: 5 PASSED

- [ ] **Step 5: Replace `instruction_templates` list with `STEP_MESSAGE_TEMPLATES` lookup (lines 723-734)**

```python
# Before (lines 723-734)
        # Define instruction templates for variation
        instruction_templates = [
            'Now, execute this instruction: {instruction}',
            'Please proceed with the following step: {instruction}',
            'The next task is to perform this action: {instruction}',
            'Execute the instruction as follows: {instruction}',
        ]
        # Vary the instruction prompt to avoid repetitive context
        prompt_template = instruction_templates[i % len(instruction_templates)]
        formatted_instruction = prompt_template.format(
            instruction=instruction_to_execute
        )

# After
        # Step-type-aware message: anchors position (N/M), scopes action, adds stop directive
        _step_template = STEP_MESSAGE_TEMPLATES.get(step_type, STEP_MESSAGE_TEMPLATES['Action'])
        formatted_instruction = _step_template.format(
            n=i + 1, total=total_steps, instruction=instruction_to_execute
        )
```

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest tests/ -v --ignore=tests/test_crawler.py
```

Expected: all tests pass

- [ ] **Step 7: Run pre-commit**

```bash
pre-commit run --files \
  webqa_agent/executor/gen/agents/execute_agent.py \
  tests/test_execute_agent_boundary.py
```

Expected: Passed

- [ ] **Step 8: Commit**

```bash
git add webqa_agent/executor/gen/agents/execute_agent.py \
        tests/test_execute_agent_boundary.py
git commit -m "feat(executor): step-aware message templates with step anchor and stop directive

Replace rotating unanchored instruction_templates with STEP_MESSAGE_TEMPLATES:
- Action: [步骤 N/M · 操作] anchor + stop directive
- Assertion: [步骤 N/M · 验证] + explicit 不要执行任何界面操作
- UX_Verify: [步骤 N/M · UX验证] + explicit 不要执行任何界面操作
- Unknown step types fall back to Action template

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

______________________________________________________________________

## Self-Review Notes

- **Spec Section 1 (planning):** Task 1 covers both inner and outer function + graph.py call site. ✓
- **Spec Section 2a (factory):** Task 3, Steps 3–6. ✓
- **Spec Section 2b (preamble prompt):** Task 2 covers function creation + tests. ✓
- **Spec Section 2c (three profiles):** Task 3, Steps 7–11. ✓
- **Spec Section 3 (step templates):** Task 4 covers `STEP_MESSAGE_TEMPLATES` + lookup replacement. ✓
- **Spec Section 4 (max_iterations):** Built into the three profiles in Task 3 (preamble=3, action=5, verify=3). ✓
- **Type consistency:** `_create_agent_executor` signature defined in Task 3 Step 5, used in Task 3 Step 7. `STEP_MESSAGE_TEMPLATES` dict defined in Task 4 Step 3, referenced in Task 4 Step 5. ✓
- **`parse_step_type` returns:** `'Action'`, `'Assertion'`, `'UX_Verify'` — template keys match exactly. ✓
- **No placeholders:** All code blocks are complete and runnable. ✓
