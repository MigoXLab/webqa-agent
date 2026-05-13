# Intelligent File Upload for Gen Mode

**Date**: 2026-03-26
**Status**: Approved (reviewed by architect-review + code-reviewer)
**Scope**: Gen mode only (Run mode unaffected)

## Overview

In Gen mode (AI-driven exploration), the Agent autonomously detects file upload controls on web pages and selects appropriate files from a user-configured test file directory. The LLM makes file selection decisions based on the accept attribute, page context, and business objectives.

## Requirements

1. **File Source**: User-configured directory via `test_files_dir` in config.yaml
2. **Selection Logic**: LLM comprehensive judgment (accept attribute + page context + business objectives)
3. **Planning Level**: LLM auto-identifies upload points; step descriptions contain intent only (e.g., "upload a PDF resume")
4. **Execution Level**: LLM sees file catalog, selects specific file, calls Upload action with full path
5. **Batch Strategy**: LLM makes separate Upload calls, one per file
6. **No Files Configured**: Skip upload steps with `[WARNING]` log
7. **File Types**: Extensible architecture, core types first (PDF, images, documents)
8. **Verification**: Basic verification via existing verify_tool

## Architecture: File-Aware LLM (Approach A)

### Data Flow

```
Startup:
  config.yaml (test_files_dir: ./uploads/)
    -> CLI resolves relative path to absolute path
    -> GenConfig validates directory exists
    -> GenExecutor._run_langgraph_workflow() creates TestFileLibrary
    -> TestFileLibrary scans directory, builds index, caches catalog
    -> TestFileLibrary added to initial_state

Planning:
  DeepCrawler extracts page elements (including input[type=file])
    -> Stage 1: LLM filters priority elements (upload controls retained)
    -> Stage 2: LLM plans test cases (has_test_files=True passed to prompt)
       Step description: "Upload a PDF resume" (no file path needed)

Execution:
  agent_worker_node() reads state['test_file_library']
    -> file catalog injected into agent system prompt
    -> LLM sees upload element + file catalog
    -> LLM calls: Upload(target='42', value='/abs/path/resume.pdf')
    -> action_tool._arun(): validates path within test_files_dir (security)
    -> action_tool._arun(): forwards file_path=value to ui_tester.action()
    -> ui_driver.action(file_path=value): forwards to _execute_plan()
    -> action_executor._execute_upload(action, file_path)
    -> action_handler.upload_file() (existing two-tier strategy)
    -> verify_tool: verify upload result
```

## Design Details

### 1. Configuration Layer

Add `test_files_dir` to `GenConfig`:

```python
# gen_config.py
class GenConfig(BaseModel):
    # ... existing fields ...
    test_files_dir: Optional[str] = Field(
        default=None,
        description='Directory containing test files for upload testing. '
                    'Agent will scan this directory and auto-select files '
                    'based on page context when encountering upload controls.'
    )

    @field_validator('test_files_dir')
    @classmethod
    def validate_test_files_dir(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        resolved = os.path.abspath(v)
        if not os.path.isdir(resolved):
            logging.warning(f"test_files_dir does not exist: {resolved}")
            return None  # Treat as unconfigured
        return resolved
```

**Path resolution**: CLI layer resolves relative paths (relative to config.yaml directory) to absolute paths before passing to GenConfig. GenConfig validator uses `os.path.abspath()` as a secondary resolution (relative to CWD).

User config example:

```yaml
test_config:
  test_files_dir: ./test_assets/uploads/
  business_objectives: "Test resume upload and file management"
```

### 2. TestFileLibrary

New file: `webqa_agent/utils/test_file_library.py`

```python
MAX_CATALOG_FILES = 30
MAX_FILE_SIZE_MB = 50

@dataclass
class FileEntry:
    name: str           # resume.pdf
    path: str           # /absolute/path/to/resume.pdf
    relative_path: str  # resume.pdf (relative to test_files_dir)
    extension: str      # .pdf
    mime_type: str       # application/pdf
    size_bytes: int      # 128000
    category: str        # document / image / video / audio / other

class TestFileLibrary:
    """Scans user-specified directory, builds file index,
    provides LLM-readable file catalog summary."""

    def __init__(self, directory: str): ...

    def _scan(self) -> None:
        """Recursive scan with safety guards:
        - followlinks=False (prevent symlink cycles)
        - os.path.isfile() check (skip special files)
        - PermissionError catch per file
        - Skip files > MAX_FILE_SIZE_MB
        """

    def get_catalog_for_llm(self) -> str:
        """Generate compact file catalog for LLM context.
        - Truncates at MAX_CATALOG_FILES entries
        - Uses category-diverse selection when truncating
        - Includes FULL absolute paths for LLM to use directly
        - Logs warning if truncated
        """

    def validate_file_path(self, file_path: str) -> bool:
        """Security: validate that file_path is within test_files_dir.
        Uses os.path.realpath() to resolve symlinks before checking."""
```

**Key behaviors**:

- Recursive directory scan at GenExecutor initialization (one-time)
- Uses Python `mimetypes` module + custom supplement mappings
- `get_catalog_for_llm()` output is compact (~300 tokens for 10 files)
- Truncates at MAX_CATALOG_FILES (30) with category-diverse selection
- Skips files > MAX_FILE_SIZE_MB (50MB)
- `followlinks=False` to prevent symlink cycles
- Per-file `PermissionError` handling (skip with warning)
- `validate_file_path()` for path confinement security

**Catalog output format**:

```
Available test files for upload (use FULL path in Upload action value):
- /home/user/uploads/resume.pdf (application/pdf, 125KB)
- /home/user/uploads/photo.jpg (image/jpeg, 45KB)
- /home/user/uploads/data.csv (text/csv, 12KB)

IMPORTANT: Use the exact full path shown above as the Upload action's value parameter.
```

### 3. Planning Phase Changes

In `test_planning_prompts.py`, add `has_test_files: bool = False` parameter to `get_planning_prompt()`.

When `has_test_files=True`, append upload testing guidance:

```
## File Upload Testing
When you identify file upload controls on the page:
- Include upload actions in your test steps with natural language descriptions
- Example step: "Upload a PDF resume to the file upload area"
- The agent will automatically select appropriate files during execution
- Consider testing: valid file upload, upload verification
```

In `graph.py` `plan_test_cases()`, pass `has_test_files=state.get('test_file_library') is not None`.

When `has_test_files=False`, no upload guidance is added. LLM will not proactively generate upload test cases.

### 4. Execution Phase Changes

#### 4.1 State Plumbing (Full Chain)

1. **`gen_executor.py`** (`_run_langgraph_workflow()`): Create TestFileLibrary from `self.config.test_files_dir`, add to `initial_state['test_file_library']`
2. **`schemas.py`**: Add `test_file_library: Optional[Any] = None` to `MainGraphState`
3. **`graph.py`**: No change needed — `**state` spread propagates `test_file_library` to all nodes
4. **`execute_agent.py`** (`agent_worker_node()`): Read `state.get('test_file_library')`, inject catalog into system prompt

#### 4.2 File Catalog Injection

In `execute_agent.py` `agent_worker_node()`, inject file catalog into agent system prompt:

```python
test_file_library = state.get('test_file_library')
if test_file_library:
    file_upload_context = get_file_upload_context(
        test_file_library.get_catalog_for_llm()
    )
    system_prompt += f"\n\n{file_upload_context}"
```

#### 4.3 Upload Action Value Semantics

LLM fills `value` field with the full file path from the catalog:

```json
{
  "action": "Upload",
  "target": "42",
  "value": "/home/user/uploads/resume.pdf",
  "description": "Upload a PDF resume to the file input"
}
```

No new schema fields needed. The existing `value` parameter is reused.

#### 4.4 action_tool.py Changes

Three changes needed:

**a) Upload instruction building** (existing line 170-171):

```python
elif action == 'Upload':
    if value:
        action_phrase = f'Upload file {value} to {target}'
    else:
        return '[WARNING] Upload skipped: no test files configured (test_files_dir not set)'
```

**b) Path confinement security** (before forwarding):

```python
# Validate file path is within test_files_dir
if action == 'Upload' and value:
    test_file_library = self.ui_tester_instance.test_file_library  # or passed via state
    if test_file_library and not test_file_library.validate_file_path(value):
        return f'[FAILURE] Security: file path {value} is outside configured test_files_dir'
```

**c) Pass file_path to ui_tester.action()** (critical fix for Gen mode):

```python
# In _arun(), when calling ui_tester:
if action == 'Upload' and value:
    execution_steps, result = await self.ui_tester_instance.action(
        instruction, file_path=value
    )
else:
    execution_steps, result = await self.ui_tester_instance.action(instruction)
```

Data flow: LLM `value` -> action_tool (validate + forward) -> ui_driver.action(file_path=...) -> \_execute_upload(action, file_path) -> action_handler.upload_file()

**Batch upload**: For multiple files, LLM makes SEPARATE Upload calls, one per file.

#### 4.5 action_executor.py Defensive Fix

Make `file_path` optional to prevent TypeError from generic dispatch:

```python
async def _execute_upload(self, action, file_path=None):
    if not file_path:
        return {
            'success': False,
            'message': 'No file path provided for upload action. '
                       'Configure test_files_dir in config.yaml.'
        }
    # ... rest unchanged
```

#### 4.6 Execution Prompt

New function in `agent_execution_prompts.py`:

```python
def get_file_upload_context(file_catalog: str) -> str:
    return f"""
## File Upload Testing
When you encounter a file upload element on the page:
1. Check the element's accept attribute and surrounding labels/text
2. Select the most appropriate file from the available test files below
3. Use the Upload action with the FULL file path as the value parameter

{file_catalog}

**Selection Rules:**
- Match file type to the accept attribute (e.g., accept=".pdf" -> choose a .pdf file)
- If accept allows multiple types, prefer the most common type
- For batch upload (multiple attribute), make SEPARATE Upload calls, one per file
- If no matching file exists, skip the upload step

**CRITICAL**: The value parameter MUST be the FULL absolute path exactly as shown
in the file list above. Do NOT use just the filename.
"""
```

### 5. Error Handling

| Scenario                                   | Behavior                                                                      |
| ------------------------------------------ | ----------------------------------------------------------------------------- |
| `test_files_dir` not configured            | Planning: no upload guidance. Execution: `[WARNING]` skip                     |
| Directory doesn't exist / empty            | GenConfig validator warns, returns None (treated as unconfigured)             |
| LLM picks non-existent file                | ui_driver validates existence, returns `[FAILURE]`, LLM can retry             |
| LLM picks file outside dir                 | action_tool `validate_file_path()` blocks with `[FAILURE]` (path confinement) |
| accept attribute mismatch                  | action_handler has existing fallback (uses first available input)             |
| Upload fails                               | Existing error chain unchanged (ActionContext -> error_details)               |
| File too large (>50MB)                     | Excluded from catalog during scan, LLM never sees it                          |
| Permission denied on file                  | Excluded from catalog during scan with warning log                            |
| Symlink cycle                              | `followlinks=False` prevents infinite recursion                               |
| `_execute_upload` called without file_path | Returns failure with guidance message (defensive fix)                         |

### 6. Backward Compatibility

- `test_files_dir` is Optional with default None, no impact on existing behavior
- Run mode completely unaffected (still uses YAML `args.file_path`)
- Upload action `value` semantics extended (was already file_path), no breaking change
- `_execute_upload` signature change (file_path default=None) is backward compatible
- All existing tests continue to pass

## Files Changed

| File                                               | Change Type | Description                                             |
| -------------------------------------------------- | ----------- | ------------------------------------------------------- |
| `webqa_agent/config_models/gen_config.py`          | Modify      | Add `test_files_dir` field with path validator          |
| `webqa_agent/utils/test_file_library.py`           | **New**     | TestFileLibrary: scan, index, catalog, path validation  |
| `webqa_agent/executor/gen_executor.py`             | Modify      | Create TestFileLibrary, add to initial_state            |
| `webqa_agent/executor/gen/state/schemas.py`        | Modify      | Add `test_file_library` to MainGraphState               |
| `webqa_agent/executor/gen/agents/execute_agent.py` | Modify      | Inject file catalog into agent system prompt            |
| `webqa_agent/prompts/test_planning_prompts.py`     | Modify      | Add `has_test_files` param, conditional upload guidance |
| `webqa_agent/prompts/agent_execution_prompts.py`   | Modify      | Add `get_file_upload_context()` function                |
| `webqa_agent/tools/action_tool.py`                 | Modify      | Upload skip + path security + file_path forwarding      |
| `webqa_agent/actions/action_executor.py`           | Modify      | Make `_execute_upload` file_path optional (defensive)   |
| `tests/test_file_library.py`                       | **New**     | TestFileLibrary unit tests                              |

**Unchanged files**: action_handler.py, ui_driver.py, run_structures.py, case_runner.py, graph.py

## Test Strategy

| Test                                    | Type     | Coverage                                           |
| --------------------------------------- | -------- | -------------------------------------------------- |
| TestFileLibrary scan/catalog/edge cases | Unit     | Directory scan, MIME mapping, truncation, symlinks |
| TestFileLibrary path confinement        | Security | Path traversal prevention, symlink resolution      |
| GenConfig test_files_dir validation     | Unit     | Path resolution, non-existent dir, permissions     |
| action_tool Upload branch               | Unit     | file_path forwarding, value=None skip, security    |
| Planning prompt with/without files      | Unit     | Conditional upload guidance insertion              |
| \_execute_upload defensive guard        | Unit     | file_path=None returns failure                     |
| Agent system prompt with file catalog   | Unit     | Catalog injection in agent_worker_node             |
