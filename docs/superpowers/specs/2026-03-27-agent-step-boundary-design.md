# Agent Step Boundary Enforcement Design

## Overview

**Goal:** Eliminate agent step over-execution in Gen mode by fixing planning hallucination, isolating preamble execution context, and reinforcing main step boundaries.

**Architecture:** Three coordinated changes across prompts, executor factory, and agent loop — using layered soft guidance (L1 Prompt + L2 Iteration limits) with interfaces reserved for harder enforcement (L3 Tool filtering, L4 Hook-based monitoring).

**Tech Stack:** LangChain AgentExecutor, ChatPromptTemplate, LangGraph, Python

______________________________________________________________________

## Background

### Observed Problems

Running a test case with `test_assets/` containing `bench.pdf` exposed two defects:

1. **Planning hallucination**: The planning LLM generated step instructions referencing `test_document.pdf` — a filename it invented — because the planning prompt only received `has_test_files=True` (a boolean), not the actual filenames.

2. **Preamble over-execution**: A preamble step intended only to close a modal dialog (click "我知道了") ran for 93 seconds and executed the entire test case: uploaded `bench.pdf`, clicked confirm, and verified the result. Root cause: preamble and main steps share the same `get_execute_system_prompt(case)` output, which includes `objective`, `success_criteria`, and `file_catalog` — giving the agent both the goal and the tools to achieve it.

3. **Main step over-execution**: Action or verify steps occasionally continue into subsequent steps. Root cause: step messages provide no positional anchor ("you are on step N of M") and no explicit stop directive.

### Root Cause Summary

```
System prompt (shared)
├── objective: "验证上传功能"          ← preamble also sees this
├── success_criteria: ["文件上传成功"]  ← preamble also sees this
├── file_catalog: bench.pdf available   ← preamble also sees this
└── execution guidance: "ensure test objectives are met"  ← core driver of over-execution

AgentExecutor (max_iterations=5, shared)
├── Preamble: should only close modal
│   ├── Tool call 1: Tap "我知道了" ✓
│   ├── Sees upload area appear
│   ├── Reasons: "objective says upload, catalog has bench.pdf"
│   ├── Tool call 2: Upload bench.pdf  ← boundary violation
│   ├── Tool call 3: Tap "上传"        ← continues
│   └── Tool call 4: Verify state      ← max_iterations reached
└── Main steps: instructions reference hallucinated "test_document.pdf"
```

### Research Basis

| Finding                                                                                  | Source                         |
| ---------------------------------------------------------------------------------------- | ------------------------------ |
| Prompt constraints work for Claude Sonnet/Opus, but unreliable for weaker models         | arXiv:2405.13966               |
| Step position anchoring (N/M framing) is more reliable than pure prohibition language    | Plan-Then-Execute architecture |
| OWASP LLM06:2025: prompt constraints are necessary but insufficient; use layered defense | OWASP GenAI                    |
| WebArena: "issue only one action at a time" + stop sequence = effective dual enforcement | arXiv:2307.13854               |
| Verify-type steps need explicit "do NOT perform actions" constraint                      | WebArena observations          |

______________________________________________________________________

## Design

### Section 1: Planning Prompt — Inject Actual File Names

**Problem:** `get_planning_prompt()` receives `has_test_files: bool = False`. When `True`, the LLM knows files exist but invents names.

**Solution:** Pass `file_catalog: str = ''` instead. The catalog string (produced by `TestFileLibrary.get_catalog_for_llm()`) contains actual filenames, paths, and MIME types.

**Change in `test_planning_prompts.py`:**

```python
# Before
def get_planning_prompt(
    ...,
    has_test_files: bool = False,
) -> str:

# After
def get_planning_prompt(
    ...,
    file_catalog: str = '',
) -> str:
```

Internal logic change: replace `if has_test_files:` with `if file_catalog:`, and inject the catalog content into the prompt instead of a generic "files are available" message.

**Change in `graph.py`:**

```python
# Before
get_planning_prompt(has_test_files=state.get('test_file_library') is not None)

# After
lib = state.get('test_file_library')
file_catalog = lib.get_catalog_for_llm() if lib else ''
get_planning_prompt(file_catalog=file_catalog)
```

**Backward compatibility:** `file_catalog=''` is semantically equivalent to the old `has_test_files=False`. No behavior change when no file library is configured.

______________________________________________________________________

### Section 2: Preamble — Independent Agent Executor via Factory Function

**Problem:** Preamble uses the same `AgentExecutor` instance as main steps, bound to `get_execute_system_prompt(case)` which contains the full test objective and file catalog.

#### 2a: Factory Function

Extract executor creation into a reusable factory to avoid duplication and enable per-profile configuration:

```python
def _create_agent_executor(
    llm: BaseChatModel,
    tools: list,
    system_prompt: str,
    max_iterations: int = 5,
) -> AgentExecutor:
    """Create a configured AgentExecutor with the given system prompt and iteration limit."""
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

#### 2b: Preamble System Prompt

Add `get_preamble_system_prompt(language)` to `agent_execution_prompts.py`. The function returns a prompt with the following structure:

**zh-CN version (key sections):**

```
你是一个 UI 操作员，负责在测试正式开始前执行前置准备动作（preamble actions）。

## 你的职责范围
- 执行当前消息中指定的准备动作
- 准备动作通常包括：关闭弹窗、切换标签、导航到指定页面等

## 明确的边界
- 你的任务仅限于当前指派的准备动作
- 不要追求任何测试目标，不要尝试验证功能，不要上传文件
- 完成准备动作后立即报告结果并停止

## 可用工具
[复用 get_execute_system_prompt 中的工具使用说明部分]
```

**Intentionally omitted from preamble prompt** (compared to `get_execute_system_prompt`):

- `objective` / `business_context`
- `success_criteria`
- `file_catalog` (files available for upload)
- Any mention of what the test is trying to prove

**Implementation note:** Re-use the tool description section from `get_execute_system_prompt` verbatim to avoid divergence. Only the role definition and scope constraint sections differ.

#### 2c: Three Executor Profiles

Create all executors once before the step loops:

```python
preamble_system_prompt = get_preamble_system_prompt(language=language)
full_system_prompt = get_execute_system_prompt(case, language=language)

preamble_executor = _create_agent_executor(llm, tools, preamble_system_prompt, max_iterations=3)
action_executor   = _create_agent_executor(llm, tools, full_system_prompt,     max_iterations=5)
verify_executor   = _create_agent_executor(llm, tools, full_system_prompt,     max_iterations=3)
```

Preamble execution uses `preamble_executor`. Main step loop selects based on `step_type`:

```python
if step_type in ('verify', 'ux_verify'):
    current_executor = verify_executor
else:
    current_executor = action_executor  # 'action' + custom tool steps
```

______________________________________________________________________

### Section 3: Main Steps — Step-Aware Message Templates

**Problem:** Current instruction templates are positionally unanchored and provide no stop directive:

```python
instruction_templates = [
    'Now, execute this instruction: {instruction}',
    'Please proceed with the following step: {instruction}',
    ...
]
```

**Solution:** Replace with step-type-aware structured templates.

#### Template Design

```python
STEP_MESSAGE_TEMPLATES = {
    'action': (
        '[步骤 {n}/{total} · 操作]\n'
        '{instruction}\n\n'
        '执行且仅执行上述操作。完成后立即报告结果，不要主动继续其他步骤。'
    ),
    'verify': (
        '[步骤 {n}/{total} · 验证]\n'
        '{instruction}\n\n'
        '仅验证上述条件，不要执行任何界面操作。报告验证结果后停止。'
    ),
    'ux_verify': (
        '[步骤 {n}/{total} · UX验证]\n'
        '{instruction}\n\n'
        '仅评估上述视觉/体验条件，不要执行任何界面操作。报告评估结果后停止。'
    ),
}

# Non-standard step_type (custom tools) falls back to 'action'
_template = STEP_MESSAGE_TEMPLATES.get(step_type.lower(), STEP_MESSAGE_TEMPLATES['action'])
formatted_instruction = _template.format(
    n=i + 1, total=total_steps, instruction=instruction_to_execute
)
```

#### Improvement Summary

| Dimension            | Before                                                    | After                      |
| -------------------- | --------------------------------------------------------- | -------------------------- |
| Step position        | None                                                      | `[步骤 N/M · 类型]` anchor |
| Task description     | Wrapped in boilerplate ("Now, execute this instruction:") | Pure instruction, no noise |
| Completion directive | None                                                      | "完成后立即报告，不要继续" |
| Verify constraint    | No distinction                                            | Explicit "不要执行操作"    |

#### Research Justification

- **Step anchoring** follows Plan-Then-Execute architecture: executor sees "you are on step N of M" which anchors it to its position and prevents look-ahead
- **Step-type distinction** follows WebArena findings: verify-type steps require explicit action prohibition, not just generic scope limits
- **Claude Sonnet compatibility**: arXiv:2405.13966 confirms explicit constraint instructions improve performance for Claude Sonnet/Opus (unlike GPT-3.5 where they backfire)

______________________________________________________________________

### Section 4: max_iterations — Per-Profile Iteration Limits

**Analysis of required iterations per step type:**

| Scenario                          | Normal path                | Error recovery                             | Total | Recommended  |
| --------------------------------- | -------------------------- | ------------------------------------------ | ----- | ------------ |
| **preamble** (close modal)        | 1 (tap + confirm)          | +1 (position offset) +1 (wait + retry)     | 3     | **3**        |
| **action** (upload, fill, click)  | 1–2 (incl. scroll/wait)    | +2 (element not visible / form validation) | 4–5   | **5** (keep) |
| **verify** (assert state/text)    | 1 (screenshot + assert)    | +1 (wait for load) +1 (scroll to find)     | 3     | **3**        |
| **ux_verify** (visual assessment) | 1–2 (screenshot + analyze) | +1 (scroll + re-screenshot)                | 3     | **3**        |

**Implementation:** Built into the three executor profiles defined in Section 2c. Both `verify` and `ux_verify` step types use `verify_executor` (max_iterations=3); `action` and all custom tool steps use `action_executor` (max_iterations=5).

**Semantics:** `early_stopping_method='force'` (default) returns current best result on limit, does not raise. This is a soft ceiling, not a hard abort.

______________________________________________________________________

### Section 5: Reserved Interfaces (Not in Scope)

The following hardening layers are explicitly not implemented now, but the design preserves clean interfaces for future activation:

| Layer                       | Mechanism                                                     | Activation Path                                                                   |
| --------------------------- | ------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| L3 Tool filtering           | Remove `execute_ui_action` from verify-step tool list         | Pass filtered `tools` to `verify_executor` at creation time                       |
| L4 Callback monitoring      | Log actual iteration count per step; detect multi-tool excess | Add `callbacks=[StepBoundaryCallback()]` to executor creation                     |
| L5 Per-step agent isolation | Create fresh executor per step (clears scratchpad history)    | Replace pre-created executors with per-iteration `_create_agent_executor()` calls |

______________________________________________________________________

## Affected Files

| File                                               | Change Type       | Summary                                                                                                                               |
| -------------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `webqa_agent/prompts/test_planning_prompts.py`     | Modify            | `has_test_files: bool` → `file_catalog: str`; inject catalog into planning prompt                                                     |
| `webqa_agent/prompts/agent_execution_prompts.py`   | Add function      | `get_preamble_system_prompt(language)` — lean system prompt excluding test objectives                                                 |
| `webqa_agent/executor/gen/agents/execute_agent.py` | Refactor + Modify | Add `_create_agent_executor()` factory; pre-create 3 executor profiles; replace `instruction_templates` with `STEP_MESSAGE_TEMPLATES` |
| `webqa_agent/executor/gen/graph.py`                | Modify            | Pass `file_catalog` string instead of `has_test_files` boolean                                                                        |

______________________________________________________________________

## Risk Assessment

| Risk                                                         | Likelihood | Mitigation                                                                                                    |
| ------------------------------------------------------------ | ---------- | ------------------------------------------------------------------------------------------------------------- |
| `file_catalog=''` breaks planning prompt logic               | Low        | Semantically equivalent to old `has_test_files=False`; no behavior change                                     |
| Lean preamble prompt causes incorrect tool usage             | Low        | Prompt still includes full tool usage instructions; only test-objective context is removed                    |
| `max_iterations=3` too tight for verify steps needing scroll | Medium     | `force` stopping returns best result; `max_iterations=5` action executor is still available for complex steps |
| Template change breaks non-zh-CN language paths              | Low        | Templates are language-neutral markers; stop directives can be localized if needed                            |
