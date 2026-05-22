"""Tests for screenshot filename-collision bug in
webqa_agent/executor/flash/runner.py."""
from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

from webqa_agent.executor.flash.runner import _persist_step_screenshots

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# 1-pixel JPEG (valid base64) so base64.b64decode succeeds.
_FAKE_JPEG_B64 = base64.b64encode(b'\xff\xd8\xff\xe0' + b'\x00' * 10 + b'\xff\xd9').decode()
_FAKE_PNG_B64 = base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'\x00' * 8).decode()


def _image_block(b64_data: str = _FAKE_JPEG_B64, mime: str = 'image/jpeg') -> dict:
    return {'type': 'image', 'data': b64_data, 'mimeType': mime}


def _tool_result(*blocks: dict) -> SimpleNamespace:
    """Build a fake tool_result whose content_blocks holds the given blocks."""
    return SimpleNamespace(content_blocks=list(blocks))


# ---------------------------------------------------------------------------
# Test 1 — PRIMARY (RED test): multiple calls for the same step must produce
# distinct filenames, not overwrite each other.
# ---------------------------------------------------------------------------

def test_multiple_calls_same_step_produce_distinct_filenames(tmp_path: Path) -> None:
    """Simulates a step that receives 3 screenshots via 3 separate tool_result
    events.

    Without the fix every call resets image_idx to 0 → all land on
    step_001_01.jpg.  With the fix they are numbered 01, 02, 03.
    """
    screenshot_dir = tmp_path / 'screenshots'
    screenshot_dir.mkdir()

    step_index = 1
    accumulated: list[dict] = []

    for i in range(3):
        result = _tool_result(_image_block())
        new_screenshots = _persist_step_screenshots(
            tool_result=result,
            step_index=step_index,
            screenshot_root=screenshot_dir,
            image_index_start=len(accumulated),
        )
        accumulated.extend(new_screenshots)

    # 3 distinct path entries returned
    data_paths = [s['data'] for s in accumulated]
    assert len(data_paths) == 3, f'Expected 3 screenshot dicts, got {len(data_paths)}'
    assert len(set(data_paths)) == 3, f'Paths are not all distinct: {data_paths}'

    # All 3 files exist on disk simultaneously
    expected_names = ['step_001_01.jpg', 'step_001_02.jpg', 'step_001_03.jpg']
    for name in expected_names:
        assert (screenshot_dir / name).exists(), f'{name} does not exist on disk'

    # The first file is NOT overwritten by the second or third
    assert len(list(screenshot_dir.glob('step_001_*.jpg'))) == 3


# ---------------------------------------------------------------------------
# Test 2 — Backward compatibility: single call without image_index_start
# still numbers from 01.
# ---------------------------------------------------------------------------

def test_single_call_default_args_numbers_from_01(tmp_path: Path) -> None:
    """A single call with no image_index_start should behave exactly as
    before."""
    screenshot_dir = tmp_path / 'screenshots'
    screenshot_dir.mkdir()

    result = _tool_result(_image_block())
    screenshots = _persist_step_screenshots(
        tool_result=result,
        step_index=2,
        screenshot_root=screenshot_dir,
    )

    assert len(screenshots) == 1
    assert screenshots[0]['data'].endswith('step_002_01.jpg')
    assert (screenshot_dir / 'step_002_01.jpg').exists()


# ---------------------------------------------------------------------------
# Test 3 — Multiple image blocks in one call: numbered sequentially starting
# from image_index_start + 1.
# ---------------------------------------------------------------------------

def test_multiple_blocks_in_one_call_numbered_sequentially(tmp_path: Path) -> None:
    """A single tool_result with 2 image blocks and image_index_start=2 should
    produce step_NNN_03 and step_NNN_04 (the next two slots)."""
    screenshot_dir = tmp_path / 'screenshots'
    screenshot_dir.mkdir()

    result = _tool_result(_image_block(), _image_block(b64_data=_FAKE_PNG_B64, mime='image/png'))
    screenshots = _persist_step_screenshots(
        tool_result=result,
        step_index=5,
        screenshot_root=screenshot_dir,
        image_index_start=2,
    )

    assert len(screenshots) == 2
    data_paths = [s['data'] for s in screenshots]
    assert data_paths[0].endswith('step_005_03.jpg'), f'Unexpected first path: {data_paths[0]}'
    assert data_paths[1].endswith('step_005_04.png'), f'Unexpected second path: {data_paths[1]}'
    assert (screenshot_dir / 'step_005_03.jpg').exists()
    assert (screenshot_dir / 'step_005_04.png').exists()
