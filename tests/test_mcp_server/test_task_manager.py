"""Tests for TaskManager."""
import time
from datetime import datetime, timedelta, timezone

import pytest

from webqa_agent.mcp_server.task_manager import TaskManager


@pytest.fixture
def manager():
    return TaskManager()


def test_create_task(manager):
    task_id = manager.create_task('exec-123')
    state = manager.get_task(task_id)
    assert state is not None
    assert state.execution_id == 'exec-123'
    assert state.status == 'working'


def test_get_nonexistent_task_returns_none(manager):
    assert manager.get_task('nonexistent') is None


def test_map_backend_status_pending(manager):
    assert manager.map_backend_status('pending') == 'working'
    assert manager.map_backend_status('running') == 'working'


def test_map_backend_status_completed(manager):
    assert manager.map_backend_status('completed') == 'completed'
    assert manager.map_backend_status('passed') == 'completed'


def test_map_backend_status_failed(manager):
    assert manager.map_backend_status('failed') == 'failed'
    assert manager.map_backend_status('timeout') == 'failed'


def test_map_backend_status_cancelled(manager):
    assert manager.map_backend_status('cancelled') == 'cancelled'
    assert manager.map_backend_status('stopped') == 'cancelled'


def test_adaptive_poll_interval_early(manager):
    task_id = manager.create_task('exec-1')
    interval = manager.get_poll_interval(task_id)
    assert interval == 3000


def test_adaptive_poll_interval_steady(manager):
    task_id = manager.create_task('exec-1')
    state = manager.get_task(task_id)
    state.created_at = datetime.now(timezone.utc) - timedelta(seconds=60)
    interval = manager.get_poll_interval(task_id)
    assert interval == 5000


def test_cleanup_expired(manager):
    task_id = manager.create_task('exec-1', ttl_ms=1)
    time.sleep(0.01)
    manager.cleanup_expired()
    assert manager.get_task(task_id) is None
