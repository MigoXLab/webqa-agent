# Intelligent File Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable the Gen mode agent to autonomously detect file upload controls and select appropriate test files from a user-configured directory.

**Architecture:** A `TestFileLibrary` scans the user's test file directory at startup, builds a catalog, and injects it into the LLM execution prompt. The LLM selects files based on accept attributes, page context, and business objectives. Path confinement ensures the LLM cannot reference files outside the configured directory.

**Tech Stack:** Python 3.11+, Pydantic V2, LangGraph, Playwright, mimetypes (stdlib)

**Spec:** `docs/superpowers/specs/2026-03-26-intelligent-file-upload-design.md`

______________________________________________________________________

## File Structure

| File                                               | Responsibility                                                             |
| -------------------------------------------------- | -------------------------------------------------------------------------- |
| `webqa_agent/utils/test_file_library.py`           | **New.** Scan directory, build index, generate LLM catalog, validate paths |
| `webqa_agent/config_models/gen_config.py`          | Add `test_files_dir` field with path validator                             |
| `webqa_agent/cli.py`                               | Extract `test_files_dir` from YAML, pass to GenConfig                      |
| `webqa_agent/executor/gen_executor.py`             | Create TestFileLibrary, inject into LangGraph initial_state                |
| `webqa_agent/executor/gen/state/schemas.py`        | Add `test_file_library` field to MainGraphState                            |
| `webqa_agent/executor/gen/agents/execute_agent.py` | Read library from state, inject catalog into system prompt                 |
| `webqa_agent/prompts/agent_execution_prompts.py`   | New `get_file_upload_context()` function                                   |
| `webqa_agent/prompts/test_planning_prompts.py`     | Add `has_test_files` param, conditional upload guidance                    |
| `webqa_agent/executor/gen/graph.py`                | Pass `has_test_files` flag to planning prompt                              |
| `webqa_agent/tools/action_tool.py`                 | Upload skip + path security + file_path forwarding                         |
| `webqa_agent/actions/action_executor.py`           | Make `_execute_upload` file_path optional                                  |
| `tests/test_file_library.py`                       | **New.** Unit tests for TestFileLibrary                                    |

______________________________________________________________________

### Task 1: TestFileLibrary Core

**Files:**

- Create: `webqa_agent/utils/test_file_library.py`

- Test: `tests/test_file_library.py`

- [ ] **Step 1: Create test fixture directory**

Create a temporary test fixtures structure for unit tests:

```python
# tests/test_file_library.py
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def test_files_dir(tmp_path):
    """Create a temporary directory with sample test files."""
    # Documents
    pdf_file = tmp_path / 'resume.pdf'
    pdf_file.write_bytes(b'%PDF-1.4 fake pdf content')

    csv_file = tmp_path / 'data.csv'
    csv_file.write_text('name,age\nAlice,30\n')

    txt_file = tmp_path / 'notes.txt'
    txt_file.write_text('test notes content')

    # Images
    img_dir = tmp_path / 'images'
    img_dir.mkdir()

    jpg_file = img_dir / 'photo.jpg'
    jpg_file.write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 100)  # JPEG magic bytes

    png_file = img_dir / 'logo.png'
    png_file.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)  # PNG magic bytes

    # Large file (should be excluded by size limit)
    large_file = tmp_path / 'huge_video.mp4'
    large_file.write_bytes(b'\x00' * (51 * 1024 * 1024))  # 51MB

    # Unreadable file (permission test - skip on Windows)
    if os.name != 'nt':
        locked_file = tmp_path / 'locked.pdf'
        locked_file.write_bytes(b'%PDF locked')
        locked_file.chmod(0o000)

    return tmp_path
```

- [ ] **Step 2: Write failing tests for TestFileLibrary**

```python
# tests/test_file_library.py (append after fixture)

from webqa_agent.utils.test_file_library import TestFileLibrary


class TestFileLibraryScan:
    """Tests for directory scanning and indexing."""

    def test_scan_finds_all_valid_files(self, test_files_dir):
        library = TestFileLibrary(str(test_files_dir))
        # 5 valid files: resume.pdf, data.csv, notes.txt, photo.jpg, logo.png
        # huge_video.mp4 excluded (>50MB), locked.pdf excluded (no permission)
        assert len(library.files) == 5

    def test_scan_extracts_correct_mime_types(self, test_files_dir):
        library = TestFileLibrary(str(test_files_dir))
        mime_map = {f.name: f.mime_type for f in library.files}
        assert mime_map['resume.pdf'] == 'application/pdf'
        assert mime_map['photo.jpg'] == 'image/jpeg'
        assert mime_map['data.csv'] == 'text/csv'

    def test_scan_extracts_categories(self, test_files_dir):
        library = TestFileLibrary(str(test_files_dir))
        categories = {f.name: f.category for f in library.files}
        assert categories['resume.pdf'] == 'document'
        assert categories['photo.jpg'] == 'image'

    def test_scan_nonexistent_directory(self):
        library = TestFileLibrary('/nonexistent/path')
        assert len(library.files) == 0

    def test_scan_empty_directory(self, tmp_path):
        library = TestFileLibrary(str(tmp_path))
        assert len(library.files) == 0

    def test_scan_skips_large_files(self, test_files_dir):
        library = TestFileLibrary(str(test_files_dir))
        names = [f.name for f in library.files]
        assert 'huge_video.mp4' not in names

    @pytest.mark.skipif(os.name == 'nt', reason='Permission test not supported on Windows')
    def test_scan_skips_unreadable_files(self, test_files_dir):
        library = TestFileLibrary(str(test_files_dir))
        names = [f.name for f in library.files]
        assert 'locked.pdf' not in names


class TestFileLibraryCatalog:
    """Tests for LLM catalog generation."""

    def test_catalog_contains_file_info(self, test_files_dir):
        library = TestFileLibrary(str(test_files_dir))
        catalog = library.get_catalog_for_llm()
        assert 'resume.pdf' in catalog
        assert 'application/pdf' in catalog
        assert str(test_files_dir) in catalog  # absolute paths

    def test_catalog_empty_library(self, tmp_path):
        library = TestFileLibrary(str(tmp_path))
        catalog = library.get_catalog_for_llm()
        assert catalog == ''

    def test_catalog_truncation(self, tmp_path):
        """Create more than MAX_CATALOG_FILES files to test truncation."""
        for i in range(35):
            (tmp_path / f'file_{i}.txt').write_text(f'content {i}')
        library = TestFileLibrary(str(tmp_path))
        catalog = library.get_catalog_for_llm()
        # Should mention truncation
        assert '30' in catalog or 'showing' in catalog.lower()


class TestFileLibraryPathValidation:
    """Tests for path confinement security."""

    def test_valid_path_inside_dir(self, test_files_dir):
        library = TestFileLibrary(str(test_files_dir))
        valid_path = str(test_files_dir / 'resume.pdf')
        assert library.validate_file_path(valid_path) is True

    def test_invalid_path_outside_dir(self, test_files_dir):
        library = TestFileLibrary(str(test_files_dir))
        assert library.validate_file_path('/etc/passwd') is False

    def test_path_traversal_attack(self, test_files_dir):
        library = TestFileLibrary(str(test_files_dir))
        evil_path = str(test_files_dir / '..' / '..' / 'etc' / 'passwd')
        assert library.validate_file_path(evil_path) is False

    def test_symlink_escape(self, test_files_dir):
        """Symlink pointing outside the directory should be rejected."""
        symlink = test_files_dir / 'evil_link.pdf'
        try:
            symlink.symlink_to('/etc/hosts')
            library = TestFileLibrary(str(test_files_dir))
            assert library.validate_file_path(str(symlink)) is False
        except OSError:
            pytest.skip('Cannot create symlinks on this OS')
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_file_library.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'webqa_agent.utils.test_file_library'`

- [ ] **Step 4: Implement TestFileLibrary**

```python
# webqa_agent/utils/test_file_library.py
"""Test file library for intelligent file upload in Gen mode.

Scans a user-configured directory, builds a file index by MIME type,
and provides an LLM-readable catalog for autonomous file selection.
"""

import logging
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

MAX_CATALOG_FILES = 30
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB

# Supplement mimetypes with common types that may be missing
_EXTRA_MIME_TYPES = {
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.webp': 'image/webp',
    '.avif': 'image/avif',
    '.md': 'text/markdown',
    '.yaml': 'text/yaml',
    '.yml': 'text/yaml',
}

_CATEGORY_MAP = {
    'image': ['image/'],
    'video': ['video/'],
    'audio': ['audio/'],
    'document': [
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats',
        'text/',
    ],
}


def _get_mime_type(file_path: str) -> str:
    """Get MIME type for a file, with fallback to custom mappings."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in _EXTRA_MIME_TYPES:
        return _EXTRA_MIME_TYPES[ext]
    mime, _ = mimetypes.guess_type(file_path)
    return mime or 'application/octet-stream'


def _get_category(mime_type: str) -> str:
    """Categorize a MIME type into a human-readable category."""
    for category, prefixes in _CATEGORY_MAP.items():
        for prefix in prefixes:
            if mime_type.startswith(prefix):
                return category
    return 'other'


def _format_size(size_bytes: int) -> str:
    """Format file size in human-readable form."""
    if size_bytes < 1024:
        return f'{size_bytes}B'
    elif size_bytes < 1024 * 1024:
        return f'{size_bytes // 1024}KB'
    else:
        return f'{size_bytes // (1024 * 1024)}MB'


@dataclass
class FileEntry:
    """Represents a single test file in the library."""

    name: str
    path: str
    extension: str
    mime_type: str
    size_bytes: int
    category: str


class TestFileLibrary:
    """Scans a directory for test files and provides LLM-readable catalogs.

    Used by Gen mode to enable intelligent file selection during
    autonomous web testing when file upload controls are encountered.
    """

    def __init__(self, directory: str) -> None:
        self._directory = os.path.realpath(directory)
        self.files: List[FileEntry] = []
        self._scan()

    def _scan(self) -> None:
        """Recursively scan directory for test files.

        Safety guards:
        - followlinks=False to prevent symlink cycles
        - Skips non-regular files (devices, pipes, sockets)
        - Catches PermissionError per file
        - Skips files larger than MAX_FILE_SIZE_BYTES
        """
        if not os.path.isdir(self._directory):
            logger.warning(f'TestFileLibrary: directory does not exist: {self._directory}')
            return

        for root, _dirs, filenames in os.walk(self._directory, followlinks=False):
            for filename in filenames:
                filepath = os.path.join(root, filename)

                if not os.path.isfile(filepath):
                    continue

                try:
                    size = os.path.getsize(filepath)
                except (PermissionError, OSError) as e:
                    logger.warning(f'TestFileLibrary: skipping inaccessible file: {filepath}: {e}')
                    continue

                if size > MAX_FILE_SIZE_BYTES:
                    logger.debug(
                        f'TestFileLibrary: skipping large file ({_format_size(size)}): {filepath}'
                    )
                    continue

                ext = os.path.splitext(filename)[1].lower()
                mime_type = _get_mime_type(filepath)
                category = _get_category(mime_type)

                self.files.append(FileEntry(
                    name=filename,
                    path=filepath,
                    extension=ext,
                    mime_type=mime_type,
                    size_bytes=size,
                    category=category,
                ))

        # Sort by category then name for consistent output
        self.files.sort(key=lambda f: (f.category, f.name))
        logger.info(f'TestFileLibrary: found {len(self.files)} files in {self._directory}')

    def get_catalog_for_llm(self) -> str:
        """Generate a compact file catalog string for LLM context injection.

        Returns empty string if no files are available.
        Truncates to MAX_CATALOG_FILES with category-diverse selection.
        """
        if not self.files:
            return ''

        entries = self.files
        truncated = False

        if len(entries) > MAX_CATALOG_FILES:
            truncated = True
            # Category-diverse selection: pick files across categories
            by_category: dict[str, list[FileEntry]] = {}
            for f in entries:
                by_category.setdefault(f.category, []).append(f)

            selected: list[FileEntry] = []
            while len(selected) < MAX_CATALOG_FILES and by_category:
                empty_cats = []
                for cat, cat_files in by_category.items():
                    if len(selected) >= MAX_CATALOG_FILES:
                        break
                    if cat_files:
                        selected.append(cat_files.pop(0))
                    else:
                        empty_cats.append(cat)
                for cat in empty_cats:
                    del by_category[cat]

            entries = sorted(selected, key=lambda f: (f.category, f.name))

        lines = ['Available test files for upload (use FULL path in Upload action value):']
        for f in entries:
            lines.append(f'- {f.path} ({f.mime_type}, {_format_size(f.size_bytes)})')

        if truncated:
            lines.append(
                f'\n[Showing {MAX_CATALOG_FILES} of {len(self.files)} files. '
                f'Prefer files listed above.]'
            )

        lines.append(
            '\nIMPORTANT: Use the exact full path shown above as the '
            "Upload action's value parameter."
        )

        return '\n'.join(lines)

    def validate_file_path(self, file_path: str) -> bool:
        """Validate that a file path is within the configured test directory.

        Resolves symlinks and relative paths before checking containment.
        Returns False for paths outside test_files_dir (security).
        """
        try:
            resolved = os.path.realpath(file_path)
            return resolved.startswith(self._directory + os.sep) or resolved == self._directory
        except (OSError, ValueError):
            return False
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_file_library.py -v`
Expected: All tests PASS (adjust test_scan_finds_all_valid_files count if locked file fixture is skipped on your OS)

- [ ] **Step 6: Run pre-commit and commit**

```bash
pre-commit run --files webqa_agent/utils/test_file_library.py tests/test_file_library.py
git add webqa_agent/utils/test_file_library.py tests/test_file_library.py
git commit -m "feat(upload): add TestFileLibrary for intelligent file selection"
```

______________________________________________________________________

### Task 2: GenConfig + CLI Integration

**Files:**

- Modify: `webqa_agent/config_models/gen_config.py:36-77`

- Modify: `webqa_agent/cli.py:237-342`

- [ ] **Step 1: Write failing test for GenConfig**

```python
# tests/test_file_library.py (append at end)

from webqa_agent.config_models.gen_config import GenConfig
from webqa_agent.config_models.base_config import LLMConfig


class TestGenConfigTestFilesDir:
    """Tests for test_files_dir field in GenConfig."""

    def test_default_is_none(self):
        config = GenConfig(
            target_url='https://example.com',
            llm_config=LLMConfig(model='gpt-4o', api_key='test-key'),
        )
        assert config.test_files_dir is None

    def test_valid_directory(self, tmp_path):
        config = GenConfig(
            target_url='https://example.com',
            llm_config=LLMConfig(model='gpt-4o', api_key='test-key'),
            test_files_dir=str(tmp_path),
        )
        assert config.test_files_dir == str(tmp_path)

    def test_nonexistent_directory_becomes_none(self):
        config = GenConfig(
            target_url='https://example.com',
            llm_config=LLMConfig(model='gpt-4o', api_key='test-key'),
            test_files_dir='/nonexistent/path/xyz',
        )
        assert config.test_files_dir is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_file_library.py::TestGenConfigTestFilesDir -v`
Expected: FAIL (test_files_dir field does not exist)

- [ ] **Step 3: Add test_files_dir to GenConfig**

Edit `webqa_agent/config_models/gen_config.py`. Add import and field:

```python
# At top of file, add to imports:
import logging
import os
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

# In GenConfig class, after skip_reflection field (line 76), add:

    test_files_dir: Optional[str] = Field(
        default=None,
        description='Directory containing test files for upload testing. '
                    'Agent scans this directory and auto-selects files '
                    'when encountering upload controls in Gen mode.',
    )

    @field_validator('test_files_dir')
    @classmethod
    def validate_test_files_dir(cls, v: Optional[str]) -> Optional[str]:
        """Resolve and validate test files directory path."""
        if v is None:
            return None
        resolved = os.path.abspath(v)
        if not os.path.isdir(resolved):
            logging.warning(f'test_files_dir does not exist: {resolved}')
            return None
        return resolved
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_file_library.py::TestGenConfigTestFilesDir -v`
Expected: PASS

- [ ] **Step 5: Add test_files_dir extraction in CLI**

Edit `webqa_agent/cli.py`. After line 328 (`skip_reflection = not enable_reflection`), add:

```python
    # Test files directory for upload testing
    test_files_dir = tconf.get('test_files_dir')
```

Then in the `GenConfig(...)` constructor call (line 331-342), add the new parameter:

```python
    gen_config = GenConfig(
        target_url=target_url,
        llm_config=llm_config,
        browser_config=browser_config,
        report_config=report_config,
        log_config=log_config,
        business_objectives=business_objectives,
        dynamic_step_generation=dynamic_step_config,
        custom_tools=custom_tools_config,
        max_concurrent_tests=workers,
        skip_reflection=skip_reflection,
        test_files_dir=test_files_dir,
    )
```

- [ ] **Step 6: Run pre-commit and commit**

```bash
pre-commit run --files webqa_agent/config_models/gen_config.py webqa_agent/cli.py
git add webqa_agent/config_models/gen_config.py webqa_agent/cli.py tests/test_file_library.py
git commit -m "feat(upload): add test_files_dir config field and CLI extraction"
```

______________________________________________________________________

### Task 3: LangGraph State Plumbing

**Files:**

- Modify: `webqa_agent/executor/gen/state/schemas.py:7-36`

- Modify: `webqa_agent/executor/gen_executor.py:267-299`

- [ ] **Step 1: Add test_file_library to MainGraphState**

Edit `webqa_agent/executor/gen/state/schemas.py`. After line 31 (`browser_config: Optional[dict]`), add:

```python
    test_file_library: Any               # TestFileLibrary instance (optional)
```

The full Infrastructure section becomes:

```python
    # Infrastructure
    session_pool: Any                    # BrowserSessionPool instance
    llm_config: Optional[dict]           # LLM config for creating UITester
    report_config: Optional[dict]        # Report config
    browser_config: Optional[dict]       # Browser config
    test_file_library: Any               # TestFileLibrary instance (optional)
```

- [ ] **Step 2: Initialize TestFileLibrary in gen_executor.py**

Edit `webqa_agent/executor/gen_executor.py`. In `_run_langgraph_workflow()`, before the `initial_state` dict (line 270), add:

```python
        # Initialize test file library if configured
        test_file_library = None
        if self.config.test_files_dir:
            from webqa_agent.utils.test_file_library import TestFileLibrary
            test_file_library = TestFileLibrary(self.config.test_files_dir)
            if test_file_library.files:
                logger.info(
                    f'TestFileLibrary loaded: {len(test_file_library.files)} files '
                    f'from {self.config.test_files_dir}'
                )
            else:
                logger.warning(
                    f'TestFileLibrary: no valid files found in {self.config.test_files_dir}'
                )
                test_file_library = None
```

Then in the `initial_state` dict, after the `'report_config'` entry (line 298), add:

```python
            # File upload testing
            'test_file_library': test_file_library,
```

- [ ] **Step 3: Verify no regressions**

Run: `uv run pytest tests/ -v -k "not external" --timeout=60`
Expected: All existing tests PASS (new field defaults to None, no impact)

- [ ] **Step 4: Run pre-commit and commit**

```bash
pre-commit run --files webqa_agent/executor/gen/state/schemas.py webqa_agent/executor/gen_executor.py
git add webqa_agent/executor/gen/state/schemas.py webqa_agent/executor/gen_executor.py
git commit -m "feat(upload): add TestFileLibrary to LangGraph state pipeline"
```

______________________________________________________________________

### Task 4: Planning Prompt Enhancement

**Files:**

- Modify: `webqa_agent/prompts/test_planning_prompts.py:739-743, 1191-1223`

- Modify: `webqa_agent/executor/gen/graph.py:373-382`

- [ ] **Step 1: Add has_test_files parameter to planning prompt functions**

Edit `webqa_agent/prompts/test_planning_prompts.py`.

In `get_test_case_planning_system_prompt()` (line 739-743), add `has_test_files` parameter:

```python
def get_test_case_planning_system_prompt(
    business_objectives: str,
    language: str = 'zh-CN',
    enabled_custom_tools: list[str] | None = None,
    has_test_files: bool = False,
) -> str:
```

At the end of the function body (before the `return` statement), append the upload guidance conditionally:

```python
    if has_test_files:
        system_prompt += """

## File Upload Testing
When you identify file upload controls (input[type="file"]) on the page:
- Include upload actions in your test steps with natural language descriptions
- Example step: "Upload a PDF resume to the file upload area"
- The agent will automatically select appropriate files during execution
- Consider testing: successful file upload, verify uploaded filename appears on page
"""
```

In `get_planning_prompt()` (line 1191-1200), add `has_test_files` parameter and forward it:

```python
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
```

And in the function body (line 1217-1218), pass it through:

```python
    system_prompt = get_test_case_planning_system_prompt(
        business_objectives, language, enabled_custom_tools, has_test_files
    )
```

- [ ] **Step 2: Pass has_test_files from graph.py**

Edit `webqa_agent/executor/gen/graph.py`. At the call site (lines 373-382), add the flag:

```python
        system_prompt, user_prompt = get_planning_prompt(
            business_objectives=enhanced_business_objectives,
            state_url=state['url'],
            language=language,
            page_text_summary=page_text_info,
            priority_elements=priority_elements,
            all_page_links=all_page_links,
            navigation_map=navigation_map,
            enabled_custom_tools=enabled_custom_tools,
            has_test_files=state.get('test_file_library') is not None,
        )
```

- [ ] **Step 3: Verify no regressions**

Run: `uv run pytest tests/ -v -k "not external" --timeout=60`
Expected: All existing tests PASS (default `has_test_files=False` preserves behavior)

- [ ] **Step 4: Run pre-commit and commit**

```bash
pre-commit run --files webqa_agent/prompts/test_planning_prompts.py webqa_agent/executor/gen/graph.py
git add webqa_agent/prompts/test_planning_prompts.py webqa_agent/executor/gen/graph.py
git commit -m "feat(upload): add file upload guidance to planning prompts"
```

______________________________________________________________________

### Task 5: Execution Prompt + Agent Injection

**Files:**

- Modify: `webqa_agent/prompts/agent_execution_prompts.py:648`

- Modify: `webqa_agent/executor/gen/agents/execute_agent.py:1569-1575`

- [ ] **Step 1: Add get_file_upload_context function**

Edit `webqa_agent/prompts/agent_execution_prompts.py`. After line 648 (before the `get_category_guidelines` function at line 651), add:

```python
def get_file_upload_context(file_catalog: str) -> str:
    """Generate file upload context section for the agent execution prompt.

    Args:
        file_catalog: LLM-readable file catalog from TestFileLibrary.

    Returns:
        Formatted prompt section with file catalog and selection rules.
    """
    return f"""

## File Upload Testing
When you encounter a file upload element on the page:
1. Check the element's accept attribute and surrounding labels/text
2. Select the most appropriate file from the available test files below
3. Use the Upload action with the FULL file path as the value parameter

{file_catalog}

**Selection Rules:**
- Match file type to the accept attribute (e.g., accept=".pdf" -> choose a .pdf file)
- If accept allows multiple types, prefer the most common type for the page context
- For batch upload (multiple attribute), make SEPARATE Upload action calls, one per file
- If no matching file exists, skip the upload step

**CRITICAL**: The value parameter MUST be the FULL absolute path exactly as shown
in the file list above. Do NOT use just the filename.
"""
```

- [ ] **Step 2: Inject file catalog in agent_worker_node**

Edit `webqa_agent/executor/gen/agents/execute_agent.py`.

Add import at the top (near existing prompt imports around line 47-48):

```python
from webqa_agent.prompts.agent_execution_prompts import (
    get_execute_system_prompt, get_file_upload_context
)
```

After line 1571 (`system_prompt_string = get_execute_system_prompt(case, language=language)`), add:

```python
    # Inject file upload context if test file library is available
    test_file_library = state.get('test_file_library')
    if test_file_library:
        file_catalog = test_file_library.get_catalog_for_llm()
        if file_catalog:
            system_prompt_string += get_file_upload_context(file_catalog)
            logging.debug(
                f'Injected file upload context ({len(file_catalog)} chars) '
                f'into agent system prompt'
            )
```

- [ ] **Step 3: Verify no regressions**

Run: `uv run pytest tests/ -v -k "not external" --timeout=60`
Expected: All existing tests PASS

- [ ] **Step 4: Run pre-commit and commit**

```bash
pre-commit run --files webqa_agent/prompts/agent_execution_prompts.py webqa_agent/executor/gen/agents/execute_agent.py
git add webqa_agent/prompts/agent_execution_prompts.py webqa_agent/executor/gen/agents/execute_agent.py
git commit -m "feat(upload): inject file catalog into agent execution prompt"
```

______________________________________________________________________

### Task 6: action_tool.py Upload Flow + Security

**Files:**

- Modify: `webqa_agent/tools/action_tool.py:170-171, 212-216`

- [ ] **Step 1: Modify Upload instruction building**

Edit `webqa_agent/tools/action_tool.py`. Replace lines 170-171:

```python
        elif action == 'Upload':
            action_phrase = f'Upload file {value} to {target}'
```

With:

```python
        elif action == 'Upload':
            if value:
                action_phrase = f'Upload file {value} to {target}'
            else:
                return (
                    '[WARNING] Upload skipped: no test files available. '
                    'Configure test_files_dir in config.yaml to enable file upload testing.'
                )
```

- [ ] **Step 2: Add path security validation and file_path forwarding**

Edit `webqa_agent/tools/action_tool.py`. Replace the `ui_tester.action()` call at line 216:

```python
            execution_steps, result = await self.ui_tester_instance.action(instruction)
```

With:

```python
            # For Upload actions, validate path security and forward file_path
            if action == 'Upload' and value:
                # Security: validate file is within configured test_files_dir
                test_file_library = getattr(
                    self.ui_tester_instance, 'test_file_library', None
                )
                if test_file_library and not test_file_library.validate_file_path(value):
                    return (
                        f'[FAILURE:SECURITY] File path "{value}" is outside the '
                        f'configured test_files_dir. Only files within the test '
                        f'directory can be uploaded.'
                    )
                execution_steps, result = await self.ui_tester_instance.action(
                    instruction, file_path=value
                )
            else:
                execution_steps, result = await self.ui_tester_instance.action(
                    instruction
                )
```

- [ ] **Step 3: Verify no regressions**

Run: `uv run pytest tests/ -v -k "not external" --timeout=60`
Expected: All existing tests PASS

- [ ] **Step 4: Run pre-commit and commit**

```bash
pre-commit run --files webqa_agent/tools/action_tool.py
git add webqa_agent/tools/action_tool.py
git commit -m "feat(upload): add path security and file_path forwarding in action_tool"
```

______________________________________________________________________

### Task 7: Defensive Fix for \_execute_upload

**Files:**

- Modify: `webqa_agent/actions/action_executor.py:340`

- [ ] **Step 1: Make file_path optional**

Edit `webqa_agent/actions/action_executor.py`. Change line 340 from:

```python
    async def _execute_upload(self, action, file_path):
```

To:

```python
    async def _execute_upload(self, action, file_path=None):
        """Execute upload action.

        Args:
            action: Action dict with locate.id
            file_path: File path(s) to upload. If None, returns failure
                      with guidance to configure test_files_dir.
        """
        if not file_path:
            return {
                'success': False,
                'message': 'No file path provided for upload action. '
                           'Configure test_files_dir in config.yaml to enable '
                           'file upload testing in Gen mode.',
            }
```

Keep the rest of the method unchanged (the existing `if not self._validate_params(...)` block follows after this new guard).

- [ ] **Step 2: Verify no regressions**

Run: `uv run pytest tests/ -v -k "not external" --timeout=60`
Expected: All existing tests PASS

- [ ] **Step 3: Run pre-commit and commit**

```bash
pre-commit run --files webqa_agent/actions/action_executor.py
git add webqa_agent/actions/action_executor.py
git commit -m "fix(upload): make _execute_upload file_path optional for defensive safety"
```

______________________________________________________________________

### Task 8: Wire TestFileLibrary to UITester for Security Validation

**Files:**

- Modify: `webqa_agent/executor/gen/agents/execute_agent.py:1558-1566`

The path security check in Task 6 reads `self.ui_tester_instance.test_file_library`. We need to attach the library to the UITester instance so the action_tool can access it.

- [ ] **Step 1: Attach test_file_library to UITester in agent_worker_node**

Edit `webqa_agent/executor/gen/agents/execute_agent.py`. After line 1559 (`ui_tester_instance.report_dir = report_dir`), add:

```python
    # Attach test file library for path security validation in action_tool
    ui_tester_instance.test_file_library = state.get('test_file_library')
```

- [ ] **Step 2: Verify no regressions**

Run: `uv run pytest tests/ -v -k "not external" --timeout=60`
Expected: All existing tests PASS

- [ ] **Step 3: Run pre-commit and commit**

```bash
pre-commit run --files webqa_agent/executor/gen/agents/execute_agent.py
git add webqa_agent/executor/gen/agents/execute_agent.py
git commit -m "feat(upload): wire TestFileLibrary to UITester for path security"
```

______________________________________________________________________

### Task 9: Final Integration Test + Smoke Test

**Files:**

- Test: `tests/test_file_library.py`

- [ ] **Step 1: Add integration test for full config-to-library flow**

```python
# tests/test_file_library.py (append at end)

class TestIntegration:
    """Integration tests for config -> library -> catalog flow."""

    def test_genconfig_to_library_flow(self, test_files_dir):
        """Test that GenConfig.test_files_dir correctly feeds TestFileLibrary."""
        config = GenConfig(
            target_url='https://example.com',
            llm_config=LLMConfig(model='gpt-4o', api_key='test-key'),
            test_files_dir=str(test_files_dir),
        )
        assert config.test_files_dir is not None

        library = TestFileLibrary(config.test_files_dir)
        assert len(library.files) > 0

        catalog = library.get_catalog_for_llm()
        assert 'resume.pdf' in catalog
        assert config.test_files_dir in catalog

    def test_none_config_skips_library(self):
        """Test that None test_files_dir means no library created."""
        config = GenConfig(
            target_url='https://example.com',
            llm_config=LLMConfig(model='gpt-4o', api_key='test-key'),
        )
        assert config.test_files_dir is None
        # Simulating gen_executor behavior: no library when dir is None
        test_file_library = None
        if config.test_files_dir:
            test_file_library = TestFileLibrary(config.test_files_dir)
        assert test_file_library is None

    def test_path_validation_security(self, test_files_dir):
        """Test end-to-end path validation security."""
        library = TestFileLibrary(str(test_files_dir))

        # Valid file inside directory
        valid = str(test_files_dir / 'resume.pdf')
        assert library.validate_file_path(valid) is True

        # Traversal attack
        evil = str(test_files_dir / '..' / '..' / 'etc' / 'passwd')
        assert library.validate_file_path(evil) is False

        # Completely unrelated path
        assert library.validate_file_path('/tmp/random_file.pdf') is False
```

- [ ] **Step 2: Run all tests**

Run: `uv run pytest tests/test_file_library.py -v`
Expected: All tests PASS

- [ ] **Step 3: Run full test suite for regressions**

Run: `uv run pytest tests/ -v -k "not external" --timeout=60`
Expected: All tests PASS

- [ ] **Step 4: Run pre-commit on all changed files**

```bash
pre-commit run --files \
  webqa_agent/utils/test_file_library.py \
  webqa_agent/config_models/gen_config.py \
  webqa_agent/cli.py \
  webqa_agent/executor/gen_executor.py \
  webqa_agent/executor/gen/state/schemas.py \
  webqa_agent/executor/gen/agents/execute_agent.py \
  webqa_agent/prompts/test_planning_prompts.py \
  webqa_agent/prompts/agent_execution_prompts.py \
  webqa_agent/tools/action_tool.py \
  webqa_agent/actions/action_executor.py \
  tests/test_file_library.py
```

Expected: All hooks PASS

- [ ] **Step 5: Final commit**

```bash
git add tests/test_file_library.py
git commit -m "test(upload): add integration tests for file upload feature"
```
