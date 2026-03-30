"""Internal API endpoints for Agent callback."""
import asyncio
import logging
import os
import shutil
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Execution
from app.models.business import Business
from app.models.environment import Environment
from app.models.scheduled_task import ScheduledTask
from app.providers import get_provider
from app.services.executor import _time_id_prefix, upload_report_to_oss
from app.services.progress_cache import refresh_progress_ttl, set_progress
from app.utils.datetime_utils import now_with_tz
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()


# =============================================================================
# Progress API - Agent progress push
# =============================================================================

class TaskProgressItem(BaseModel):
    """Progress information for a single task."""
    name: str
    duration: Optional[float] = None
    elapsed: Optional[float] = None
    status: Optional[str] = None  # Execution status: 'success' | 'failed'
    error: Optional[str] = None
    result: Optional[str] = None  # Test result: 'passed' | 'failed' | 'warning'


class ProgressUpdateRequest(BaseModel):
    """Request body for Agent progress push."""
    completed: List[TaskProgressItem] = []
    running: List[TaskProgressItem] = []
    logs: List[str] = []


@router.post('/executions/{execution_id}/progress')
async def update_execution_progress(
    execution_id: str,
    request: ProgressUpdateRequest,
):
    """Receive progress updates pushed by the Agent.

    The Agent pushes progress to this endpoint every 1-2 seconds during
    execution. Data is stored in Redis cache (with TTL auto-expiration) for
    frontend polling. Progress is retained after execution completes to view
    historical execution logs.
    """
    progress_data = {
        'completed': [t.model_dump() for t in request.completed],
        'running': [t.model_dump() for t in request.running],
        'logs': request.logs,
    }

    # Store in Redis cache (with TTL)
    await set_progress(execution_id, progress_data)

    return {'success': True}


class ExecutionCompleteRequest(BaseModel):
    """Request body for execution complete callback.

    Execution level status (status):
    - completed: Agent finished execution normally (report available)
    - failed: Agent exited abnormally/crashed
    - timeout: Execution timed out (set by Backend timeout detection)

    Case results are shown via result_count:
    - { total: 10, passed: 8, failed: 1, warning: 1 }
    """
    status: str  # completed, failed, timeout
    result_count: Optional[Dict[str, Any]] = None
    report_path: Optional[str] = None  # Report path in shared storage
    log_path: Optional[str] = None     # Log path in shared storage
    error_message: Optional[str] = None


class ExecutionCompleteResponse(BaseModel):
    """Response for execution complete callback."""
    success: bool
    oss_report_url: Optional[str] = None
    message: Optional[str] = None


def cleanup_local_report(report_path: str) -> bool:
    """Remove the local report directory (call after OSS upload succeeds).

    Args:
        report_path: Path to the report directory

    Returns:
        True if cleanup succeeded
    """
    try:
        if report_path and os.path.exists(report_path):
            shutil.rmtree(report_path)
            logger.info(f'[Cleanup] 已删除本地报告目录: {report_path}')
            return True
        return False
    except Exception as e:
        logger.warning(f'[Cleanup] 删除本地报告目录失败: {report_path}, error: {e}')
        return False


@router.post('/executions/{execution_id}/complete', response_model=ExecutionCompleteResponse)
async def execution_complete(execution_id: str, request: ExecutionCompleteRequest):
    """Callback after Agent execution completes.

    - Update execution status
    - Read report from shared storage and upload to OSS
    - Remove local report directory after successful upload
    - Return OSS URL
    """
    logger.info(f'[Internal] 收到执行完成回调: execution_id={execution_id}, status={request.status}, result_count={request.result_count}, report_path={request.report_path}, error={request.error_message}')

    async with AsyncSessionLocal() as db:
        try:
            # Look up execution record
            result = await db.execute(
                select(Execution).where(Execution.id == UUID(execution_id))
            )
            execution = result.scalar_one_or_none()

            if not execution:
                raise HTTPException(status_code=404, detail=f'Execution {execution_id} not found')

            # Update execution status
            execution.status = request.status
            execution.result_count = request.result_count
            execution.completed_at = now_with_tz()

            if request.error_message:
                execution.error_message = request.error_message

            if request.report_path:
                execution.local_report_path = request.report_path

            # Upload report to OSS (path uses time_id prefix: YYYYMMDD_HHMMSS + first 8 chars of exec id)
            oss_url = None
            if request.report_path and os.path.exists(request.report_path):
                oss_key_dir = _time_id_prefix(execution_id, execution.started_at)
                logger.info(f'[Internal] 开始上传报告到 OSS: {request.report_path} -> reports/{oss_key_dir}')
                # 使用 run_in_executor 异步执行同步的 OSS 上传操作，避免阻塞异步事件循环
                loop = asyncio.get_event_loop()
                oss_url = await loop.run_in_executor(
                    None,
                    upload_report_to_oss,
                    request.report_path,
                    oss_key_dir,
                )
                if oss_url:
                    execution.oss_report_url = oss_url
                    logger.info(f'[Internal] OSS 上传成功: {oss_url}')

                    # After OSS upload, remove local report directory
                    cleanup_local_report(request.report_path)
                else:
                    logger.warning('[Internal] OSS 上传失败，保留本地报告目录')
            else:
                logger.warning(f'[Internal] 报告路径不存在或未提供: {request.report_path}')

            await db.commit()

            # Refresh progress cache TTL (keeps history until TTL expires)
            await refresh_progress_ttl(execution_id)

            # Notification: if triggered by a scheduled task (including manual), send result notification
            if execution.scheduled_task_id:
                try:
                    notifier = get_provider('notification')

                    # Load scheduled task for webhook_url
                    task_result = await db.execute(
                        select(ScheduledTask).where(ScheduledTask.id == execution.scheduled_task_id)
                    )
                    scheduled_task = task_result.scalar_one_or_none()

                    task_webhook = scheduled_task.webhook_url if scheduled_task else None
                    feishu_user_ids = scheduled_task.feishu_notify_user_id if scheduled_task else None

                    # Resolve business name
                    biz_result = await db.execute(
                        select(Business).where(Business.id == execution.business_id)
                    )
                    business = biz_result.scalar_one_or_none()
                    business_name = business.name if business else 'Unknown business'

                    # Resolve environment name
                    environment_name = None
                    if execution.environment_id:
                        env_result = await db.execute(
                            select(Environment).where(Environment.id == execution.environment_id)
                        )
                        env = env_result.scalar_one_or_none()
                        environment_name = env.name if env else None

                    task_name = scheduled_task.name if scheduled_task else None

                    notification_kwargs = dict(
                        execution_id=execution_id,
                        business_name=business_name,
                        completed_at=execution.completed_at,
                        result_count=request.result_count,
                        report_url=oss_url,
                        feishu_notify_user_id=feishu_user_ids,
                        environment_name=environment_name,
                        task_name=task_name,
                    )

                    # Default notification
                    asyncio.create_task(notifier.send(**notification_kwargs))

                    # Custom webhook: also send on failure or manual trigger
                    if task_webhook:
                        failed_count = (request.result_count or {}).get('failed', 0)
                        is_manual = execution.trigger_type != 'scheduled'
                        if failed_count > 0 or is_manual:
                            asyncio.create_task(
                                notifier.send(webhook_url=task_webhook, **notification_kwargs)
                            )
                except Exception as notify_err:
                    logger.warning(f'[Internal] 通知发送失败（不影响主流程）: {notify_err}')

            return ExecutionCompleteResponse(
                success=True,
                oss_report_url=oss_url,
                message='Execution status updated successfully'
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f'[Internal] 处理回调失败: execution_id={execution_id}, status={request.status}')
            await db.rollback()
            raise HTTPException(status_code=500, detail=str(e))


@router.get('/health')
async def internal_health():
    """Internal health check endpoint."""
    return {'status': 'healthy', 'service': 'internal-api'}
