"""Download verification tool — checks whether a file was downloaded.

Usage flow for the agent:
    1. check_download(action="snapshot")   — before clicking download
    2. click the download button
    3. check_download(action="verify")     — confirms new file appeared

The tool manages baseline state internally so the agent doesn't need
to remember file lists or construct shell commands.
"""
from __future__ import annotations

import time
from pathlib import Path

from ..core.tool import Tool, ToolResult

_DEFAULT_TIMEOUT = 15  # seconds to wait for download to complete
_POLL_INTERVAL = 1.0   # seconds between checks


def _human_size(size_bytes: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size_bytes < 1024:
            return f'{size_bytes:.1f}{unit}' if unit != 'B' else f'{size_bytes}{unit}'
        size_bytes /= 1024  # type: ignore[assignment]
    return f'{size_bytes:.1f}TB'


class DownloadCheckTool(Tool):
    """Verify that a browser download produced a real file on disk."""

    # Stateful: _snapshot writes self._baseline, _verify reads it.  Two
    # concurrent invocations would race on the baseline.  Forced sequential.
    concurrent_safe = False

    def __init__(self, download_dir: str | Path) -> None:
        self._dir = Path(download_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._baseline: set[str] | None = None

    @property
    def name(self) -> str:
        return 'check_download'

    @property
    def description(self) -> str:
        return (
            'Verify browser downloads. Two-step usage:\n'
            '1. Call with action="snapshot" BEFORE clicking a download '
            'button — records current files as baseline.\n'
            '2. Call with action="verify" AFTER clicking download — '
            'waits up to timeout seconds for a new file to appear, '
            'confirms it is complete (not .crdownload), and reports '
            'file name + size.\n'
            'Optional: action="list" to see all files in the download dir.'
        )

    @property
    def input_schema(self) -> dict:
        return {
            'type': 'object',
            'properties': {
                'action': {
                    'type': 'string',
                    'enum': ['snapshot', 'verify', 'list'],
                    'description': (
                        '"snapshot" = record baseline before download. '
                        '"verify" = check for new file after download. '
                        '"list" = list all files in download directory.'
                    ),
                },
                'timeout': {
                    'type': 'integer',
                    'description': (
                        f'Seconds to wait for download (default {_DEFAULT_TIMEOUT}). '
                        'Only used with action="verify".'
                    ),
                },
            },
            'required': ['action'],
        }

    def get_activity_description(self, **kwargs) -> str | None:
        action = kwargs.get('action', '')
        if action == 'snapshot':
            return 'Recording download baseline'
        if action == 'verify':
            return 'Verifying download'
        return 'Checking downloads'

    def is_read_only(self) -> bool:
        return True

    def execute(self, **kwargs) -> ToolResult:
        action = (kwargs.get('action') or '').strip()

        if action == 'snapshot':
            return self._snapshot()
        elif action == 'verify':
            timeout = float(kwargs.get('timeout') or _DEFAULT_TIMEOUT)
            return self._verify(timeout)
        elif action == 'list':
            return self._list_files()
        else:
            return ToolResult(
                content='[FAILURE: action must be "snapshot", "verify", or "list"]',
                is_error=True,
            )

    def _current_files(self) -> dict[str, int]:
        """Return {filename: size} for all non-temp files in download dir."""
        result: dict[str, int] = {}
        if not self._dir.exists():
            return result
        for f in self._dir.iterdir():
            if f.is_file() and not f.name.endswith('.crdownload'):
                result[f.name] = f.stat().st_size
        return result

    def _snapshot(self) -> ToolResult:
        files = self._current_files()
        self._baseline = set(files.keys())
        count = len(self._baseline)
        return ToolResult(
            content=(
                f'[SUCCESS] Baseline recorded: {count} existing file(s). '
                'Now click the download button, then call '
                'check_download(action="verify").'
            )
        )

    def _verify(self, timeout: float) -> ToolResult:
        if self._baseline is None:
            return ToolResult(
                content=(
                    '[FAILURE: no baseline] Call check_download(action="snapshot") '
                    'before clicking the download button, then call verify.'
                ),
                is_error=True,
            )

        deadline = time.monotonic() + timeout
        new_files: dict[str, int] = {}

        while time.monotonic() < deadline:
            current = self._current_files()
            new_files = {
                name: size
                for name, size in current.items()
                if name not in self._baseline and size > 0
            }
            if new_files:
                # Check no .crdownload siblings (still downloading)
                downloading = [
                    f.name for f in self._dir.iterdir()
                    if f.name.endswith('.crdownload')
                ]
                if not downloading:
                    break
            time.sleep(_POLL_INTERVAL)

        if not new_files:
            # Check if there's a stuck .crdownload
            downloading = [
                f.name for f in self._dir.iterdir()
                if f.name.endswith('.crdownload')
            ]
            if downloading:
                return ToolResult(
                    content=(
                        f'[FAILURE: download incomplete after {timeout:.0f}s] '
                        f'Still downloading: {", ".join(downloading)}'
                    ),
                    is_error=True,
                )
            return ToolResult(
                content=(
                    f'[FAILURE: no new file after {timeout:.0f}s] '
                    'No new file appeared in the download directory.'
                ),
                is_error=True,
            )

        # Report success
        parts: list[str] = []
        for name, size in sorted(new_files.items()):
            parts.append(f'{name} ({_human_size(size)})')

        # Update baseline so subsequent verifies don't re-report
        self._baseline = set(self._current_files().keys())

        return ToolResult(
            content=(
                f'[SUCCESS] Downloaded {len(new_files)} file(s): '
                + ', '.join(parts)
            )
        )

    def _list_files(self) -> ToolResult:
        files = self._current_files()
        if not files:
            return ToolResult(content='Download directory is empty.')
        lines = [f'  {name} ({_human_size(size)})' for name, size in sorted(files.items())]
        return ToolResult(
            content=f'Files in download directory ({len(files)}):\n' + '\n'.join(lines)
        )
