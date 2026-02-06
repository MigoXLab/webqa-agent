"""Scheduled tasks API endpoints."""
import logging
from typing import Optional
from uuid import UUID

from app.database import get_db
from app.models import Business, Environment, ScheduledTask, TestCase
from app.schemas.common import APIResponse
from app.schemas.scheduled_task import (CronValidationRequest,
                                        CronValidationResponse,
                                        ScheduledTaskCreate,
                                        ScheduledTaskListResponse,
                                        ScheduledTaskResponse,
                                        ScheduledTaskToggleRequest,
                                        ScheduledTaskUpdate)
from app.services.task_scheduler import task_scheduler
from app.utils.cron_utils import (get_next_run_time, get_next_run_times,
                                  validate_cron_expression)
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post('/schedules', response_model=APIResponse[ScheduledTaskResponse])
async def create_scheduled_task(
    task_data: ScheduledTaskCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new scheduled task."""
    # Verify business exists
    result = await db.execute(
        select(Business).where(Business.id == task_data.business_id)
    )
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail='Business not found')

    # Verify environment exists and belongs to business
    result = await db.execute(
        select(Environment).where(
            Environment.id == task_data.environment_id,
            Environment.business_id == task_data.business_id
        )
    )
    environment = result.scalar_one_or_none()
    if not environment:
        raise HTTPException(status_code=404, detail='Environment not found or does not belong to business')

    # Verify test cases exist and belong to business
    for case_id in task_data.test_case_ids:
        result = await db.execute(
            select(TestCase).where(
                TestCase.id == case_id,
                TestCase.business_id == task_data.business_id
            )
        )
        case = result.scalar_one_or_none()
        if not case:
            raise HTTPException(status_code=404, detail=f'Test case {case_id} not found or does not belong to business')

    # Calculate next run time
    next_run = get_next_run_time(task_data.cron_expression)

    # Create scheduled task
    task = ScheduledTask(
        business_id=task_data.business_id,
        name=task_data.name,
        description=task_data.description,
        environment_id=task_data.environment_id,
        test_case_ids=[str(case_id) for case_id in task_data.test_case_ids],
        model=task_data.model,
        workers=task_data.workers,
        cron_expression=task_data.cron_expression,
        enabled=task_data.enabled,
        webhook_url=task_data.webhook_url,
        feishu_notify_user_id=task_data.feishu_notify_user_id,
        next_run_at=next_run,
    )

    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Add to scheduler if enabled
    if task.enabled:
        await task_scheduler.add_task(task)

    # Build response with related names
    response = ScheduledTaskResponse(
        id=task.id,
        business_id=task.business_id,
        business_name=business.name,
        name=task.name,
        description=task.description,
        environment_id=task.environment_id,
        environment_name=environment.name,
        test_case_ids=task.test_case_ids,
        model=task.model,
        workers=task.workers,
        cron_expression=task.cron_expression,
        enabled=task.enabled,
        webhook_url=task.webhook_url,
        feishu_notify_user_id=task.feishu_notify_user_id,
        last_run_at=task.last_run_at,
        next_run_at=task.next_run_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )

    logger.info(f'[API] Created scheduled task: {task.name} ({task.id})')
    return APIResponse(data=response)


@router.get('/schedules', response_model=APIResponse[ScheduledTaskListResponse])
async def list_scheduled_tasks(
    business_id: Optional[UUID] = Query(None),
    enabled: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """List scheduled tasks with optional filters."""
    # Build query
    query = select(ScheduledTask)

    if business_id:
        query = query.where(ScheduledTask.business_id == business_id)

    if enabled is not None:
        query = query.where(ScheduledTask.enabled == enabled)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Get paginated results
    query = query.order_by(ScheduledTask.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    tasks = result.scalars().all()

    # Build response with related names
    items = []
    for task in tasks:
        # Get business name
        business_result = await db.execute(
            select(Business).where(Business.id == task.business_id)
        )
        business = business_result.scalar_one_or_none()

        # Get environment name
        env_result = await db.execute(
            select(Environment).where(Environment.id == task.environment_id)
        )
        environment = env_result.scalar_one_or_none()

        items.append(ScheduledTaskResponse(
            id=task.id,
            business_id=task.business_id,
            business_name=business.name if business else None,
            name=task.name,
            description=task.description,
            environment_id=task.environment_id,
            environment_name=environment.name if environment else None,
            test_case_ids=task.test_case_ids,
            model=task.model,
            workers=task.workers,
            cron_expression=task.cron_expression,
            enabled=task.enabled,
            webhook_url=task.webhook_url,
            feishu_notify_user_id=task.feishu_notify_user_id,
            last_run_at=task.last_run_at,
            next_run_at=task.next_run_at,
            created_at=task.created_at,
            updated_at=task.updated_at,
        ))

    return APIResponse(data=ScheduledTaskListResponse(items=items, total=total))


@router.get('/schedules/{task_id}', response_model=APIResponse[ScheduledTaskResponse])
async def get_scheduled_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get a scheduled task by ID."""
    result = await db.execute(
        select(ScheduledTask).where(ScheduledTask.id == task_id)
    )
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail='Scheduled task not found')

    # Get business name
    business_result = await db.execute(
        select(Business).where(Business.id == task.business_id)
    )
    business = business_result.scalar_one_or_none()

    # Get environment name
    env_result = await db.execute(
        select(Environment).where(Environment.id == task.environment_id)
    )
    environment = env_result.scalar_one_or_none()

    response = ScheduledTaskResponse(
        id=task.id,
        business_id=task.business_id,
        business_name=business.name if business else None,
        name=task.name,
        description=task.description,
        environment_id=task.environment_id,
        environment_name=environment.name if environment else None,
        test_case_ids=task.test_case_ids,
        model=task.model,
        workers=task.workers,
        cron_expression=task.cron_expression,
        enabled=task.enabled,
        webhook_url=task.webhook_url,
        feishu_notify_user_id=task.feishu_notify_user_id,
        last_run_at=task.last_run_at,
        next_run_at=task.next_run_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )

    return APIResponse(data=response)


@router.put('/schedules/{task_id}', response_model=APIResponse[ScheduledTaskResponse])
async def update_scheduled_task(
    task_id: UUID,
    task_update: ScheduledTaskUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a scheduled task."""
    result = await db.execute(
        select(ScheduledTask).where(ScheduledTask.id == task_id)
    )
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail='Scheduled task not found')

    # Update fields
    update_data = task_update.model_dump(exclude_unset=True)

    # Verify environment if provided
    if 'environment_id' in update_data:
        result = await db.execute(
            select(Environment).where(
                Environment.id == update_data['environment_id'],
                Environment.business_id == task.business_id
            )
        )
        environment = result.scalar_one_or_none()
        if not environment:
            raise HTTPException(status_code=404, detail='Environment not found or does not belong to business')

    # Verify test cases if provided
    if 'test_case_ids' in update_data:
        for case_id in update_data['test_case_ids']:
            result = await db.execute(
                select(TestCase).where(
                    TestCase.id == case_id,
                    TestCase.business_id == task.business_id
                )
            )
            case = result.scalar_one_or_none()
            if not case:
                raise HTTPException(status_code=404, detail=f'Test case {case_id} not found or does not belong to business')
        update_data['test_case_ids'] = [str(case_id) for case_id in update_data['test_case_ids']]

    # Update next_run_at if cron expression changed
    if 'cron_expression' in update_data:
        next_run = get_next_run_time(update_data['cron_expression'])
        update_data['next_run_at'] = next_run

    # Apply updates
    for field, value in update_data.items():
        setattr(task, field, value)

    await db.commit()
    await db.refresh(task)

    # Update scheduler
    await task_scheduler.update_task(task)

    # Get related names for response
    business_result = await db.execute(
        select(Business).where(Business.id == task.business_id)
    )
    business = business_result.scalar_one_or_none()

    env_result = await db.execute(
        select(Environment).where(Environment.id == task.environment_id)
    )
    environment = env_result.scalar_one_or_none()

    response = ScheduledTaskResponse(
        id=task.id,
        business_id=task.business_id,
        business_name=business.name if business else None,
        name=task.name,
        description=task.description,
        environment_id=task.environment_id,
        environment_name=environment.name if environment else None,
        test_case_ids=task.test_case_ids,
        model=task.model,
        workers=task.workers,
        cron_expression=task.cron_expression,
        enabled=task.enabled,
        webhook_url=task.webhook_url,
        feishu_notify_user_id=task.feishu_notify_user_id,
        last_run_at=task.last_run_at,
        next_run_at=task.next_run_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )

    logger.info(f'[API] Updated scheduled task: {task.name} ({task.id})')
    return APIResponse(data=response)


@router.delete('/schedules/{task_id}', response_model=APIResponse[dict])
async def delete_scheduled_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Delete a scheduled task."""
    result = await db.execute(
        select(ScheduledTask).where(ScheduledTask.id == task_id)
    )
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail='Scheduled task not found')

    # Remove from scheduler
    await task_scheduler.remove_task(str(task_id))

    # Delete from database
    await db.delete(task)
    await db.commit()

    logger.info(f'[API] Deleted scheduled task: {task.name} ({task.id})')
    return APIResponse(data={'message': 'Scheduled task deleted successfully'})


@router.post('/schedules/{task_id}/toggle', response_model=APIResponse[ScheduledTaskResponse])
async def toggle_scheduled_task(
    task_id: UUID,
    toggle_data: ScheduledTaskToggleRequest,
    db: AsyncSession = Depends(get_db)
):
    """Enable or disable a scheduled task."""
    result = await db.execute(
        select(ScheduledTask).where(ScheduledTask.id == task_id)
    )
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail='Scheduled task not found')

    task.enabled = toggle_data.enabled

    # Update next_run_at if enabling
    if task.enabled:
        next_run = get_next_run_time(task.cron_expression)
        task.next_run_at = next_run
    else:
        task.next_run_at = None

    await db.commit()
    await db.refresh(task)

    # Update scheduler
    await task_scheduler.update_task(task)

    # Get related names for response
    business_result = await db.execute(
        select(Business).where(Business.id == task.business_id)
    )
    business = business_result.scalar_one_or_none()

    env_result = await db.execute(
        select(Environment).where(Environment.id == task.environment_id)
    )
    environment = env_result.scalar_one_or_none()

    response = ScheduledTaskResponse(
        id=task.id,
        business_id=task.business_id,
        business_name=business.name if business else None,
        name=task.name,
        description=task.description,
        environment_id=task.environment_id,
        environment_name=environment.name if environment else None,
        test_case_ids=task.test_case_ids,
        model=task.model,
        workers=task.workers,
        cron_expression=task.cron_expression,
        enabled=task.enabled,
        webhook_url=task.webhook_url,
        feishu_notify_user_id=task.feishu_notify_user_id,
        last_run_at=task.last_run_at,
        next_run_at=task.next_run_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )

    logger.info(f'[API] Toggled scheduled task: {task.name} ({task.id}) enabled={task.enabled}')
    return APIResponse(data=response)


@router.post('/schedules/validate-cron', response_model=APIResponse[CronValidationResponse])
async def validate_cron(
    validation_data: CronValidationRequest
):
    """Validate a cron expression and return next run times."""
    is_valid, error = validate_cron_expression(validation_data.cron_expression)

    if not is_valid:
        return APIResponse(data=CronValidationResponse(
            is_valid=False,
            error=error,
            next_run_times=None
        ))

    # Get next 5 run times
    next_times = get_next_run_times(validation_data.cron_expression, count=5)

    return APIResponse(data=CronValidationResponse(
        is_valid=True,
        error=None,
        next_run_times=next_times
    ))
