"""Execution API routes."""
import asyncio
import logging
from typing import List, Optional
from uuid import UUID

from app.config import get_settings
from app.database import get_db
from app.models import Business, Environment, Execution, TestCase
from app.schemas.common import APIResponse
from app.schemas.execution import (ExecutionCreate, ExecutionListResponse,
                                   ExecutionResponse, ExecutionStatusResponse)
from app.services.executor import run_execution
from app.services.progress_cache import get_progress
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# =============================================================================
# Progress Response Schema
# =============================================================================

class TaskProgress(BaseModel):
    """单个任务的进度信息."""
    name: str
    duration: Optional[float] = None
    elapsed: Optional[float] = None
    status: Optional[str] = None
    error: Optional[str] = None


class ExecutionProgress(BaseModel):
    """执行进度响应."""
    execution_id: str
    status: str
    updated_at: Optional[str] = None
    completed: List[TaskProgress] = []
    running: List[TaskProgress] = []
    logs: List[str] = []

router = APIRouter()
settings = get_settings()
logger = logging.getLogger(__name__)

# Store running tasks for potential cancellation/monitoring
_running_tasks: dict[str, asyncio.Task] = {}


async def can_start_execution(db: AsyncSession) -> tuple[bool, str]:
    """Check if a new execution can be started."""
    result = await db.execute(
        select(func.count(Execution.id)).where(
            Execution.status.in_(['pending', 'running'])
        )
    )
    running_count = result.scalar() or 0

    if running_count >= settings.MAX_CONCURRENT_JOBS:
        return False, f'系统繁忙，当前有 {running_count} 个任务在执行，最大并发数为 {settings.MAX_CONCURRENT_JOBS}'

    return True, ''


@router.post('', response_model=APIResponse[ExecutionResponse], status_code=status.HTTP_201_CREATED)
async def create_execution(
    data: ExecutionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create and start a new execution (manual or debug trigger)."""
    # Check concurrency limit
    can_run, msg = await can_start_execution(db)
    if not can_run:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={'code': 5001, 'message': msg}
        )

    # Verify business exists
    business_result = await db.execute(
        select(Business).where(Business.id == data.business_id)
    )
    business = business_result.scalar_one_or_none()
    if not business:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2001, 'message': '业务不存在'}
        )

    # Verify environment exists
    env_result = await db.execute(
        select(Environment).where(Environment.id == data.environment_id)
    )
    environment = env_result.scalar_one_or_none()
    if not environment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2002, 'message': '环境不存在'}
        )

    # Verify all test cases exist
    for case_id in data.test_case_ids:
        case_result = await db.execute(
            select(TestCase).where(TestCase.id == case_id)
        )
        if not case_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={'code': 2003, 'message': f'用例 {case_id} 不存在'}
            )

    # Debug mode: force workers=1
    workers = 1 if data.trigger_type == 'debug' else data.workers

    # Create execution record
    execution = Execution(
        business_id=data.business_id,
        environment_id=data.environment_id,
        trigger_type=data.trigger_type,
        model=data.model,
        workers=workers,
        test_case_ids=[str(cid) for cid in data.test_case_ids],
        status='pending',
    )
    db.add(execution)
    await db.commit()
    await db.refresh(execution)

    # Start execution in background using asyncio.create_task for true concurrency
    execution_id_str = str(execution.id)
    task = asyncio.create_task(run_execution(execution_id_str))
    _running_tasks[execution_id_str] = task

    # Clean up task reference when done
    def cleanup_task(t):
        _running_tasks.pop(execution_id_str, None)
    task.add_done_callback(cleanup_task)

    logger.info(f'[API] Started execution: id={execution_id_str}, business={data.business_id}, env={data.environment_id}, cases={len(data.test_case_ids)}, model={data.model}, workers={data.workers}')

    # Build response with names
    response = ExecutionResponse(
        id=execution.id,
        business_id=execution.business_id,
        business_name=business.name,
        environment_id=execution.environment_id,
        environment_name=environment.name,
        trigger_type=execution.trigger_type,
        model=execution.model,
        workers=execution.workers,
        test_case_ids=execution.test_case_ids,
        status=execution.status,
        created_at=execution.created_at,
    )

    return APIResponse(data=response)


@router.get('', response_model=APIResponse[ExecutionListResponse])
async def list_executions(
    db: AsyncSession = Depends(get_db),
    business_id: Optional[UUID] = None,
    trigger_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    exclude_debug: bool = True,
    limit: int = 50,
    offset: int = 0,
):
    """Get all executions with optional filters.

    By default, debug executions are excluded (exclude_debug=true).
    """
    # Build query
    query = select(Execution)
    count_query = select(func.count(Execution.id))

    # Exclude debug executions by default
    if exclude_debug and not trigger_type:
        query = query.where(Execution.trigger_type != 'debug')
        count_query = count_query.where(Execution.trigger_type != 'debug')

    # Apply filters
    if business_id:
        query = query.where(Execution.business_id == business_id)
        count_query = count_query.where(Execution.business_id == business_id)
    if trigger_type:
        query = query.where(Execution.trigger_type == trigger_type)
        count_query = count_query.where(Execution.trigger_type == trigger_type)
    if status_filter:
        query = query.where(Execution.status == status_filter)
        count_query = count_query.where(Execution.status == status_filter)

    # Get total count
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Get executions with relationships
    query = (
        query
        .options(
            selectinload(Execution.business),
            selectinload(Execution.environment)
        )
        .order_by(Execution.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await db.execute(query)
    executions = result.scalars().all()

    # Build response
    items = []
    for exc in executions:
        items.append(ExecutionResponse(
            id=exc.id,
            business_id=exc.business_id,
            business_name=exc.business.name if exc.business else None,
            environment_id=exc.environment_id,
            environment_name=exc.environment.name if exc.environment else None,
            trigger_type=exc.trigger_type,
            scheduled_task_id=exc.scheduled_task_id,
            model=exc.model,
            workers=exc.workers,
            test_case_ids=exc.test_case_ids,
            status=exc.status,
            oss_report_url=exc.oss_report_url,
            local_report_path=exc.local_report_path,
            started_at=exc.started_at,
            completed_at=exc.completed_at,
            created_at=exc.created_at,
            error_message=exc.error_message,
            result_count=exc.result_count,
        ))

    return APIResponse(
        data=ExecutionListResponse(items=items, total=total)
    )


@router.get('/{execution_id}', response_model=APIResponse[ExecutionResponse])
async def get_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get execution details."""
    result = await db.execute(
        select(Execution)
        .options(
            selectinload(Execution.business),
            selectinload(Execution.environment)
        )
        .where(Execution.id == execution_id)
    )
    execution = result.scalar_one_or_none()

    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2004, 'message': '执行记录不存在'}
        )

    response = ExecutionResponse(
        id=execution.id,
        business_id=execution.business_id,
        business_name=execution.business.name if execution.business else None,
        environment_id=execution.environment_id,
        environment_name=execution.environment.name if execution.environment else None,
        trigger_type=execution.trigger_type,
        scheduled_task_id=execution.scheduled_task_id,
        model=execution.model,
        workers=execution.workers,
        test_case_ids=execution.test_case_ids,
        status=execution.status,
        oss_report_url=execution.oss_report_url,
        local_report_path=execution.local_report_path,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        created_at=execution.created_at,
        error_message=execution.error_message,
        result_count=execution.result_count,
    )

    return APIResponse(data=response)


@router.get('/{execution_id}/status', response_model=APIResponse[ExecutionStatusResponse])
async def get_execution_status(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get execution status for polling."""
    result = await db.execute(
        select(Execution).where(Execution.id == execution_id)
    )
    execution = result.scalar_one_or_none()

    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2004, 'message': '执行记录不存在'}
        )

    return APIResponse(
        data=ExecutionStatusResponse(
            id=execution.id,
            status=execution.status,
            oss_report_url=execution.oss_report_url,
            result_count=execution.result_count,
            error_message=execution.error_message,
        )
    )


@router.get('/{execution_id}/progress', response_model=APIResponse[ExecutionProgress])
async def get_execution_progress(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """获取执行任务的实时进度。

    前端轮询此接口获取实时进度，建议轮询间隔：
    - running 状态：2 秒
    - pending 状态：5 秒
    - completed/failed/timeout：停止轮询
    """
    # 查询执行记录
    result = await db.execute(
        select(Execution).where(Execution.id == execution_id)
    )
    execution = result.scalar_one_or_none()

    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 4001, 'message': '执行记录不存在'}
        )

    execution_id_str = str(execution_id)

    # 从 Redis 缓存获取进度（无论执行状态，都尝试获取历史日志）
    cached = await get_progress(execution_id_str)

    if cached:
        return APIResponse(data=ExecutionProgress(
            execution_id=execution_id_str,
            status=execution.status,
            updated_at=cached.get('updated_at'),
            completed=[TaskProgress(**t) for t in cached.get('completed', [])],
            running=[TaskProgress(**t) for t in cached.get('running', [])],
            logs=cached.get('logs', []),
        ))

    # 缓存中没有数据（Agent 可能还没开始推送，或缓存已过期）
    return APIResponse(data=ExecutionProgress(
        execution_id=execution_id_str,
        status=execution.status,
    ))
