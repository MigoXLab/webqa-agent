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
from app.services.executor import run_execution, stop_execution
from app.services.progress_cache import get_progress
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# =============================================================================
# Progress Response Schema
# =============================================================================


class TaskProgress(BaseModel):
    """Progress information for a single task."""
    name: str
    duration: Optional[float] = None
    elapsed: Optional[float] = None
    status: Optional[str] = None
    error: Optional[str] = None
    result: Optional[str] = None  # Test result: 'passed' | 'failed' | 'warning'


class ExecutionProgress(BaseModel):
    """Execution progress response."""
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


def get_execution_urls(execution: Execution, request: Request) -> tuple[Optional[str], Optional[str]]:
    """Generate report URLs for an execution."""
    # 1. If OSS report URL exists, use it and derive data flow URL
    if execution.oss_report_url:
        report_url = execution.oss_report_url
        data_flow_url = report_url.replace('test_report.html', 'data_flow_report.html')
        return report_url, data_flow_url

    # 2. If no OSS report URL, but execution is completed/failed/warning, generate local static URLs
    if execution.status in ('completed', 'passed', 'failed', 'timeout', 'warning'):
        report_url = f'/reports/exec_{execution.id}/test_report.html'
        data_flow_url = f'/reports/exec_{execution.id}/data_flow_report.html'
        return report_url, data_flow_url

    return None, None


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
    request: Request,
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
    if data.business_id:
        business_result = await db.execute(
            select(Business).where(Business.id == data.business_id)
        )
        business = business_result.scalar_one_or_none()
        if not business:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={'code': 2001, 'message': 'Business not found'}
            )
    else:
        business = None

    # Verify environment exists
    if data.environment_id:
        env_result = await db.execute(
            select(Environment).where(Environment.id == data.environment_id)
        )
        environment = env_result.scalar_one_or_none()
        if not environment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={'code': 2002, 'message': '环境不存在'}
            )
    else:
        environment = None

    # Verify all test cases exist (skip for cases with data provided inline)
    inline_ids = set(data.case_data.keys()) if data.case_data else set()

    if data.trigger_type != 'gen':
        for case_id in data.test_case_ids:
            if str(case_id) in inline_ids:
                continue  # Data provided inline, no DB record needed
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
        test_case_ids=[str(cid) for cid in data.test_case_ids] if data.test_case_ids else [],
        status='pending',
        config=data.gen_config if data.gen_config else None,
    )
    db.add(execution)
    await db.commit()
    await db.refresh(execution)

    # Start execution in background using asyncio.create_task for true concurrency
    execution_id_str = str(execution.id)
    task = asyncio.create_task(run_execution(execution_id_str, case_data=data.case_data, gen_config_dict=data.gen_config))
    _running_tasks[execution_id_str] = task

    # Clean up task reference when done
    def cleanup_task(t):
        _running_tasks.pop(execution_id_str, None)
    task.add_done_callback(cleanup_task)

    logger.info(f'[API] Started execution: id={execution_id_str}, business={data.business_id}, env={data.environment_id}, cases={len(data.test_case_ids) if data.test_case_ids else 0}, model={data.model}, workers={data.workers}')

    # Build response with names
    report_url, data_flow_report_url = get_execution_urls(execution, request)
    response = ExecutionResponse(
        id=execution.id,
        business_id=execution.business_id,
        business_name=business.name if business else None,
        environment_id=execution.environment_id,
        environment_name=environment.name if environment else None,
        trigger_type=execution.trigger_type,
        model=execution.model,
        workers=execution.workers,
        test_case_ids=execution.test_case_ids,
        status=execution.status,
        oss_report_url=execution.oss_report_url,
        report_url=report_url,
        data_flow_report_url=data_flow_report_url,
        created_at=execution.created_at,
        config=execution.config,
    )

    return APIResponse(data=response)


@router.get('', response_model=APIResponse[ExecutionListResponse])
async def list_executions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    business_id: Optional[UUID] = None,
    trigger_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    url_search: Optional[str] = None,
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
    if url_search:
        url_filter = Execution.config['target_url'].astext.ilike(f'%{url_search}%')
        query = query.where(url_filter)
        count_query = count_query.where(url_filter)

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
        report_url, data_flow_report_url = get_execution_urls(exc, request)
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
            report_url=report_url,
            data_flow_report_url=data_flow_report_url,
            local_report_path=exc.local_report_path,
            started_at=exc.started_at,
            completed_at=exc.completed_at,
            created_at=exc.created_at,
            error_message=exc.error_message,
            result_count=exc.result_count,
            config=exc.config,
        ))

    return APIResponse(
        data=ExecutionListResponse(items=items, total=total)
    )


@router.get('/{execution_id}', response_model=APIResponse[ExecutionResponse])
async def get_execution(
    request: Request,
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

    report_url, data_flow_report_url = get_execution_urls(execution, request)
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
        report_url=report_url,
        data_flow_report_url=data_flow_report_url,
        local_report_path=execution.local_report_path,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        created_at=execution.created_at,
        error_message=execution.error_message,
        result_count=execution.result_count,
        config=execution.config,
    )

    return APIResponse(data=response)


@router.post('/{execution_id}/stop', status_code=status.HTTP_200_OK)
async def stop_execution_endpoint(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Stop a running execution."""
    # Check if execution exists
    result = await db.execute(
        select(Execution).where(Execution.id == execution_id)
    )
    execution = result.scalar_one_or_none()

    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2004, 'message': '执行记录不存在'}
        )

    if execution.status not in ['pending', 'running']:
        return APIResponse(data={'message': 'Execution is not running'})

    # Try to stop via executor service
    execution_id_str = str(execution_id)
    stopped = await stop_execution(execution_id_str)

    if not stopped:
        # If not found in active processes (e.g. server restarted), just update DB status
        logger.warning(f'[API] Could not find active process for {execution_id_str}, forcing status update')

    # Update status in DB
    execution.status = 'cancelled'
    execution.error_message = 'User cancelled execution'
    await db.commit()

    return APIResponse(data={'message': 'Execution stopped'})


@router.get('/{execution_id}/status', response_model=APIResponse[ExecutionStatusResponse])
async def get_execution_status(
    request: Request,
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

    report_url, data_flow_report_url = get_execution_urls(execution, request)
    return APIResponse(
        data=ExecutionStatusResponse(
            id=execution.id,
            status=execution.status,
            oss_report_url=execution.oss_report_url,
            report_url=report_url,
            data_flow_report_url=data_flow_report_url,
            result_count=execution.result_count,
            error_message=execution.error_message,
        )
    )


@router.get('/{execution_id}/progress', response_model=APIResponse[ExecutionProgress])
async def get_execution_progress(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get real-time progress for an execution.

    The frontend polls this endpoint for live progress. Suggested poll intervals:
    - running: 2 seconds
    - pending: 5 seconds
    - completed/failed/timeout: stop polling
    """
    # Query execution record
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

    # Get progress from Redis cache (always try for historical logs regardless of execution status)
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

    # No data in cache (agent may not have started pushing yet, or cache expired)
    return APIResponse(data=ExecutionProgress(
        execution_id=execution_id_str,
        status=execution.status,
    ))
