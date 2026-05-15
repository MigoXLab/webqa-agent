"""MCP task ID <-> backend execution_id mapping."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

_STATUS_MAP = {
    'pending': 'working',
    'running': 'working',
    'completed': 'completed',
    'passed': 'completed',
    'failed': 'failed',
    'timeout': 'failed',
    'cancelled': 'cancelled',
    'stopped': 'cancelled',
}

DEFAULT_TTL_MS = 3_600_000


@dataclass
class TaskState:
    """State for a single MCP task."""

    execution_id: str
    status: str = 'working'
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_ms: int = DEFAULT_TTL_MS
    status_message: str = ''


class TaskManager:
    """In-memory mapping from MCP task IDs to backend execution IDs."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskState] = {}

    def create_task(
        self, execution_id: str, ttl_ms: int = DEFAULT_TTL_MS,
    ) -> str:
        task_id = str(uuid.uuid4())
        self._tasks[task_id] = TaskState(
            execution_id=execution_id,
            ttl_ms=ttl_ms,
        )
        return task_id

    def get_task(self, task_id: str) -> Optional[TaskState]:
        return self._tasks.get(task_id)

    def update_status(
        self, task_id: str, backend_status: str, status_message: str = '',
    ) -> None:
        state = self._tasks.get(task_id)
        if state:
            state.status = self.map_backend_status(backend_status)
            state.status_message = status_message

    @staticmethod
    def map_backend_status(backend_status: str) -> str:
        return _STATUS_MAP.get(backend_status, 'working')

    def get_poll_interval(self, task_id: str) -> int:
        state = self._tasks.get(task_id)
        if not state:
            return 5000
        elapsed = (datetime.now(timezone.utc) - state.created_at).total_seconds()
        if elapsed < 30:
            return 3000
        return 5000

    def cleanup_expired(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [
            tid for tid, state in self._tasks.items()
            if now > state.created_at + timedelta(milliseconds=state.ttl_ms)
        ]
        for tid in expired:
            del self._tasks[tid]
