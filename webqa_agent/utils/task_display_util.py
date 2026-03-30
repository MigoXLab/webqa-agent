"""Task display utilities for real-time progress visualization.

Provides a terminal UI for displaying test execution progress with:
- Running/completed task tracking
- Live log output
- Progress data export for API integration
"""

import asyncio
import logging
import os
import re
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from typing import List, Optional

from webqa_agent.utils import i18n
from webqa_agent.utils.get_log import COLORS


@dataclass
class TaskInfo:
    """Information about a tracked task."""
    name: str
    start: float
    end: Optional[float] = None
    error: Optional[str] = None
    result: Optional[str] = None  # Test result: 'passed', 'failed', 'warning'


class _Tracker:
    """Context manager for tracking task execution time and status."""

    def __init__(self, display_util: '_Display', name: str):
        self.display_util = display_util
        self.name = name
        self.start_time = None
        self.result: Optional[str] = None

    def __enter__(self):
        self.start_time = time.monotonic()
        with self.display_util.lock:
            self.display_util.running.append(TaskInfo(name=self.name, start=self.start_time))
        return self

    def __exit__(self, exc_type, exc, tb):
        end_time = time.monotonic()
        error = str(exc) if exc else None
        with self.display_util.lock:
            self.display_util.running = [t for t in self.display_util.running if t.name != self.name]
            self.display_util.completed.append(
                TaskInfo(name=self.name, start=self.start_time, end=end_time,
                         error=error, result=self.result))
        return False


def remove_ansi_escape_sequences(text: str) -> str:
    """Remove ANSI escape codes from text."""
    ansi_escape = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', text)


class _TeeStream:
    """Stream that writes to both a StringIO buffer and stderr.

    Used in no_terminal_ui mode so that:
    - Logs are captured in memory for progress API (get_progress())
    - Logs are also written to stderr for kubectl logs / container output
    """

    def __init__(self, buffer: StringIO, stream=None):
        self.buffer = buffer
        self.stream = stream or sys.stderr

    def write(self, data):
        self.buffer.write(data)
        self.stream.write(data)

    def flush(self):
        self.buffer.flush()
        self.stream.flush()


class Display:
    """Singleton facade for the display system.

    Usage:
        Display.init(language='en-US')
        Display.display.start()
        with Display.display('Task Name'):
            # ... task code ...
        await Display.display.stop()
    """

    display = None

    @classmethod
    def init(cls, language: str = 'zh-CN', no_terminal_ui: bool = False):
        """Initialize the Display singleton.

        Args:
            language: UI language ('zh-CN' or 'en-US')
            no_terminal_ui: Disable terminal rendering. When True, logs are
                           still captured for API access via get_progress().

        Note:
            If already initialized with no_terminal_ui=True, subsequent calls
            will only update the language setting. This prevents internal modules
            from overriding the API mode setting.
        """
        # Preserve no_terminal_ui mode once set
        if cls.display is not None and cls.display.no_terminal_ui:
            cls.display.language = language
            return

        cls.display = _Display(
            language=language,
            no_terminal_ui=no_terminal_ui,
        )


class _Display:
    """Internal display implementation with terminal UI and progress
    tracking."""

    SPINNER = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

    def __init__(self, refresh_interval: float = 0.1, language: str = 'zh-CN',
                 no_terminal_ui: bool = False):
        self.logger = logging.getLogger()
        self.logger_handlers = []
        self.running: List[TaskInfo] = []
        self.completed: deque[TaskInfo] = deque(maxlen=50)
        self._lock = threading.Lock()
        self._interval = refresh_interval
        self._stop_event = asyncio.Event()
        self._render_task: Optional[asyncio.Task] = None
        self._spinner_index = 0
        self.captured_output = StringIO()
        self._log_queue = deque(maxlen=1000)
        self.num_log = 5  # Number of log lines to display
        self.language = language
        self.localized_strings = {
            'zh-CN': i18n.get_lang_data('zh-CN').get('display', {}),
            'en-US': i18n.get_lang_data('en-US').get('display', {}),
        }

        self.no_terminal_ui = no_terminal_ui

        # Log pattern for parsing and colorizing truncated log lines
        self.log_pattern = re.compile(
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+)(\s+)(\w+)(\s+\[.*?]\s+\[.*?]\s+-\s+)(.*)'
        )

    def _get_text(self, key: str) -> str:
        """Get localized text for the given key."""
        return self.localized_strings.get(self.language, {}).get(key, key)

    def __call__(self, name: str):
        """Create a task tracker context manager."""
        return _Tracker(self, name)

    def start(self):
        """Start the display system.

        Binds the stream handler to capture logs and starts the render loop. In
        no_terminal_ui mode, logs are still captured for get_progress() access.
        """
        self._stop_event.clear()
        self._bind_stream_handler()
        self._render_task = asyncio.create_task(self._render_loop())

        if not self.no_terminal_ui:
            sys.stdout.write('\x1b[?25l')  # Hide cursor

    def _bind_stream_handler(self):
        """Redirect the logger's stream handler to capture output.

        This allows logs to be captured in memory for:
        - Terminal UI rendering (when no_terminal_ui=False)
        - API progress export via get_progress() (when no_terminal_ui=True)

        In no_terminal_ui mode, a TeeStream is used so logs are both captured
        in memory (for progress API) and written to stderr (for kubectl logs).
        """
        self.logger_handlers.clear()

        if self.no_terminal_ui:
            target_stream = _TeeStream(self.captured_output, sys.stderr)
        else:
            target_stream = self.captured_output

        for handler in self.logger.handlers:
            if isinstance(handler, logging.StreamHandler) and handler.name == 'stream':
                handler.setStream(target_stream)
                self.logger_handlers.append(handler)

    async def stop(self):
        """Stop the display system and restore terminal state."""
        self._stop_event.set()
        if self._render_task:
            await self._render_task

        if not self.no_terminal_ui:
            self._render_frame()  # Final render
            sys.stdout.write('\x1b[?25h')  # Show cursor

    async def _render_loop(self):
        """Main render loop running at configured interval."""
        while not self._stop_event.is_set():
            if not self.no_terminal_ui:
                self._render_frame()
            await asyncio.sleep(self._interval)

    def _get_recent_logs(self, count: int = None) -> List[str]:
        """Get recent log lines with ANSI codes removed.

        Args:
            count: Number of lines to return. None returns all lines.

        Returns:
            List of cleaned log lines
        """
        log_content = self.captured_output.getvalue()
        if not log_content:
            return []

        lines = log_content.splitlines()
        cleaned_lines = [remove_ansi_escape_sequences(line) for line in lines]

        if count is not None:
            return cleaned_lines[-count:]
        return cleaned_lines

    def get_progress(self) -> dict:
        """Get current progress data for external access (e.g., API export).

        Returns:
            Dictionary containing:
            - updated_at: ISO timestamp
            - completed: List of completed tasks with duration and status
            - running: List of running tasks with elapsed time
            - logs: All captured log lines
        """
        current_time = time.monotonic()
        with self._lock:
            return {
                'updated_at': datetime.now().isoformat(),
                'completed': [
                    {
                        'name': t.name,
                        'duration': round(t.end - t.start, 2) if t.end else 0,
                        'status': 'success' if t.error is None else 'failed',
                        'error': t.error,
                        'result': t.result
                    }
                    for t in self.completed if t.end
                ],
                'running': [
                    {
                        'name': t.name,
                        'elapsed': round(current_time - t.start, 2)
                    }
                    for t in self.running
                ],
                'logs': self._get_recent_logs()
            }

    def _render_frame(self):
        """Render a single frame of the terminal UI."""
        try:
            col, _ = os.get_terminal_size()
        except OSError:
            col = 180  # Default width when terminal size unavailable

        log_content = self.captured_output.getvalue()
        lines = log_content.splitlines() if log_content else []

        self._spinner_index = (self._spinner_index + 1) % len(self.SPINNER)
        spinner = self.SPINNER[self._spinner_index]

        out = sys.stdout
        out.write('\x1b[H\x1b[J')  # Clear screen

        with self._lock:
            # Completed tasks section
            out.write(self._get_text('completed_tasks') + '\n')
            for task in self.completed:
                if task.end is None:
                    continue
                duration = task.end - task.start
                status = '✅' if task.error is None else '❌'
                err = f' ⚠️ {task.error}' if task.error else ''
                out.write(f'  {status} {task.name} ⏱️ {duration:.2f}s{err}\n')

            out.write('════════════════════════════════════════\n')

            # Running tasks section
            out.write(self._get_text('running_tasks') + '\n')
            now = time.monotonic()
            for task in self.running:
                elapsed = now - task.start
                out.write(f'  ⏳ {spinner} {task.name} [{elapsed:.2f}s]\n')

            out.write('-' * col + '\n')

            # Recent logs section
            num_lines = min(self.num_log, len(lines))
            for i in range(num_lines):
                line = lines[-num_lines + i]
                clean_line = remove_ansi_escape_sequences(str(line))

                if len(clean_line) >= col:
                    # Truncate and re-colorize long lines
                    match = self.log_pattern.search(clean_line[:col - 3])
                    if match:
                        timestamp, space1, loglevel, middle, message = match.groups()
                        color = COLORS.get(loglevel, '')
                        end = COLORS['ENDC']
                        colored_loglevel = f'{color}{loglevel}{end}'
                        colored_message = f'{color}{message}{end}'
                        formatted = f'{timestamp}{space1}{colored_loglevel}{middle}{colored_message}'
                        out.write(f'{formatted}...\n')
                    else:
                        out.write(f'{clean_line[:col-3]}...\n')
                else:
                    out.write(line + '\n')

        out.flush()

    def render_summary(self):
        """Render final execution summary to terminal."""
        out = sys.stdout
        out.write('\x1b[H\x1b[J')  # Clear screen

        out.write(self._get_text('task_execution_summary') + '\n')
        out.write('════════════════════════════════════════\n')

        total = len(self.completed)
        success = sum(1 for t in self.completed if t.error is None)
        failed = total - success
        total_time = sum(t.end - t.start for t in self.completed if t.end)

        out.write(f"{self._get_text('total_time')}：{total_time:.2f}s\n")

        if failed > 0:
            out.write(self._get_text('error_tasks') + '\n')
            for task in self.completed:
                if task.error:
                    out.write(f"  ❌ {task.name} {self._get_text('error_message')} {task.error}\n")

        out.flush()

        # Restore stream handlers to stdout
        for handler in self.logger_handlers:
            handler.setStream(sys.stdout)

    @property
    def lock(self):
        """Thread lock for synchronizing access to task lists."""
        return self._lock

    def update_task_result(self, task_name: str, result: str):
        """Update the test result for a completed task.

        Args:
            task_name: Name of the task to update
            result: Test result - 'passed', 'failed', or 'warning'
        """
        with self._lock:
            for task in self.completed:
                if task.name == task_name:
                    task.result = result
                    break
