import asyncio
import logging
import re
import os
import sys
import time
import threading
from dataclasses import dataclass
from io import StringIO
from typing import Optional, List
from collections import deque

from webqa_agent.utils.get_log import COLORS


@dataclass
class TaskInfo:
    name: str
    start: float
    end: Optional[float] = None
    error: Optional[str] = None


class _Tracker:
    def __init__(self, display_util: "_Display", name):
        self.display_util = display_util
        self.name = name
        self.start_time = None

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
                TaskInfo(name=self.name, start=self.start_time, end=end_time, error=error))
        return False

def remove_ansi_escape_sequences(text):
    ansi_escape = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', text)


class Display:
    display = None

    @classmethod
    def init(cls):
        cls.display = _Display()


class _Display:
    SPINNER = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

    def __init__(self, refresh_interval: float = 0.1):
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
        self.num_log = 5  # TODO: Make it configurable

        for hdr in self.logger.handlers:
            if isinstance(hdr, logging.StreamHandler) and hdr.name == "stream":
                hdr.setStream(self.captured_output)
                self.logger_handlers.append(hdr)

        self.log_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+)(\s+)(\w+)(\s+\[.*?]\s+\[.*?]\s+-\s+)(.*)")

    def __call__(self, name: str):
        return _Tracker(self, name)

    def start(self):
        self._stop_event.clear()
        self._render_task = asyncio.create_task(self._render_loop())
        sys.stdout.write("\x1b[?25l")

    async def stop(self):
        self._stop_event.set()
        if self._render_task:
            await self._render_task
        sys.stdout.write("\x1b[?25h")

    async def _render_loop(self):
        while not self._stop_event.is_set():
            self._render_frame()
            await asyncio.sleep(self._interval)
        self._render_frame()

    def _render_frame(self):
        try:
            col, lin = os.get_terminal_size()
        except OSError:
            col = 180  # TODO: Make it configurable
        _log = self.captured_output.getvalue()
        lines = []
        if _log:
            lines = _log.splitlines()
        self._spinner_index = (self._spinner_index + 1) % len(self.SPINNER)
        spinner = self.SPINNER[self._spinner_index]
        out = sys.stdout
        out.write("\x1b[H\x1b[J")
        with self._lock:
            out.write("🎉 已完成任务\n")
            for t in self.completed:
                if t.end is None:
                    continue
                duration = t.end - t.start
                status = "✅" if t.error is None else "❌"
                err = f" ⚠️ {t.error}" if t.error else ""
                out.write(f"  {status} {t.name} ⏱️ {duration:.2f}s{err}\n")

            out.write("════════════════════════════════════════\n")

            out.write("🚀 正在执行任务\n")
            now = time.monotonic()
            for t in self.running:
                elapsed = now - t.start
                out.write(f"  ⏳ {spinner} {t.name} [{elapsed:.2f}s]\n")
            out.write("-" * col + "\n")
            length = min(self.num_log, len(lines))
            for ln in range(length):
                line = lines[-length + ln]
                _line = remove_ansi_escape_sequences(str(line))
                if len(_line) >= col:
                    match = self.log_pattern.search(_line[:col - 3])
                    if match:
                        timestamp, space1, loglevel, middle, message = match.groups()
                        color = COLORS[loglevel]
                        end = COLORS['ENDC']
                        colored_loglevel = f"{color}{loglevel}{end}"
                        colored_message = f"{color}{message}{end}"
                        _line = f"{timestamp}{space1}{colored_loglevel}{middle}{colored_message}"
                        out.write(f"{_line}" + "...\n")
                    else:
                        out.write(f"{_line[:col-3]}"+"...\n")
                else:
                    out.write(line + "\n")
        out.flush()

    def render_summary(self):
        out = sys.stdout
        out.write("\x1b[H\x1b[J")
        # captured = self.captured_output.getvalue()
        # if captured:
        #     out.write(captured)
        out.write("📊 任务执行统计面板\n")
        out.write("════════════════════════════════════════\n")

        total = len(self.completed)
        success = sum(1 for t in self.completed if t.error is None)
        failed = total - success
        total_time = sum(t.end - t.start for t in self.completed if t.end)

        # out.write(f"🔢 总任务数：{total}\n")
        # out.write(f"✅ 成功任务：{success}\n")
        # out.write(f"❌ 失败任务：{failed}\n")
        out.write(f"⏱️ 总共耗时：{total_time:.2f}s\n")

        if failed > 0:
            out.write("⚠️ 错误任务列表：\n")
            for t in self.completed:
                if t.error:
                    out.write(f"  ❌ {t.name} 错误信息：{t.error}\n")

        # out.write("════════════════════════════════════════\n")
        # out.write("🎯 Done！\n")
        out.flush()

        for hdr in self.logger_handlers:
            hdr.setStream(sys.stdout)

    @property
    def lock(self):
        return self._lock
