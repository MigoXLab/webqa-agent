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
from app.services.executor import upload_report_to_oss
from app.services.feishu_notify import send_feishu_notification
from app.services.progress_cache import refresh_progress_ttl, set_progress
from app.utils.datetime_utils import now_with_tz
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()


# =============================================================================
# Progress API - Agent 推送进度
# =============================================================================

class TaskProgressItem(BaseModel):
    """单个任务的进度信息."""
    name: str
    duration: Optional[float] = None
    elapsed: Optional[float] = None
    status: Optional[str] = None
    error: Optional[str] = None


class ProgressUpdateRequest(BaseModel):
    """Agent 推送进度的请求体."""
    completed: List[TaskProgressItem] = []
    running: List[TaskProgressItem] = []
    logs: List[str] = []


@router.post('/executions/{execution_id}/progress')
async def update_execution_progress(
    execution_id: str,
    request: ProgressUpdateRequest,
):
    """接收 Agent 推送的进度更新。

    Agent 执行过程中每 1-2 秒推送一次进度到此接口。 数据存入 Redis 缓存（TTL 自动过期），供前端轮询查询。
    执行完成后进度仍保留，可查看历史执行日志。
    """
    progress_data = {
        'completed': [t.model_dump() for t in request.completed],
        'running': [t.model_dump() for t in request.running],
        'logs': request.logs,
    }

    # 存入 Redis 缓存（带 TTL）
    await set_progress(execution_id, progress_data)

    return {'success': True}


class ExecutionCompleteRequest(BaseModel):
    """Request body for execution complete callback.

    执行层面状态（status）:
    - completed: Agent 正常完成执行（可查看报告）
    - failed: Agent 异常退出/崩溃
    - timeout: 执行超时（由 Backend 超时检测设置）

    Case 结果通过 result_count 展示:
    - { total: 10, passed: 8, failed: 1, warning: 1 }
    """
    status: str  # completed, failed, timeout
    result_count: Optional[Dict[str, Any]] = None
    report_path: Optional[str] = None  # 共享存储中的报告路径
    log_path: Optional[str] = None     # 共享存储中的日志路径
    error_message: Optional[str] = None


class ExecutionCompleteResponse(BaseModel):
    """Response for execution complete callback."""
    success: bool
    oss_report_url: Optional[str] = None
    message: Optional[str] = None


def cleanup_local_report(report_path: str) -> bool:
    """清理本地报告目录（OSS 上传成功后调用）。

    Args:
        report_path: 报告目录路径

    Returns:
        是否清理成功
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
    """Agent 执行完成后的回调接口。

    - 更新执行状态
    - 从共享存储读取报告并上传到 OSS
    - 上传成功后清理本地报告目录
    - 返回 OSS URL
    """
    logger.info(f'[Internal] 收到执行完成回调: execution_id={execution_id}, status={request.status}, result_count={request.result_count}, report_path={request.report_path}, error={request.error_message}')

    async with AsyncSessionLocal() as db:
        try:
            # 查找执行记录
            result = await db.execute(
                select(Execution).where(Execution.id == UUID(execution_id))
            )
            execution = result.scalar_one_or_none()

            if not execution:
                raise HTTPException(status_code=404, detail=f'Execution {execution_id} not found')

            # 更新执行状态
            execution.status = request.status
            execution.result_count = request.result_count
            execution.completed_at = now_with_tz()

            if request.error_message:
                execution.error_message = request.error_message

            if request.report_path:
                execution.local_report_path = request.report_path

            # 上传报告到 OSS
            oss_url = None
            if request.report_path and os.path.exists(request.report_path):
                logger.info(f'[Internal] 开始上传报告到 OSS: {request.report_path}')
                # 使用 run_in_executor 异步执行同步的 OSS 上传操作，避免阻塞异步事件循环
                loop = asyncio.get_event_loop()
                oss_url = await loop.run_in_executor(
                    None,
                    upload_report_to_oss,
                    request.report_path,
                    execution_id
                )
                if oss_url:
                    execution.oss_report_url = oss_url
                    logger.info(f'[Internal] OSS 上传成功: {oss_url}')

                    # OSS 上传成功后，清理本地报告目录
                    cleanup_local_report(request.report_path)
                else:
                    logger.warning('[Internal] OSS 上传失败，保留本地报告目录')
            else:
                logger.warning(f'[Internal] 报告路径不存在或未提供: {request.report_path}')

            await db.commit()

            # 刷新进度缓存 TTL（保留历史日志，TTL 过期后自动清理）
            await refresh_progress_ttl(execution_id)

            # 飞书通知：如果是定时任务触发，发送结果通知
            if execution.trigger_type == 'scheduled' and execution.scheduled_task_id:
                try:
                    # 查找关联的定时任务，获取 webhook_url
                    task_result = await db.execute(
                        select(ScheduledTask).where(ScheduledTask.id == execution.scheduled_task_id)
                    )
                    scheduled_task = task_result.scalar_one_or_none()

                    # 优先使用任务级别的 webhook_url，没有则使用全局默认
                    webhook_url = (
                        (scheduled_task.webhook_url if scheduled_task else None)
                        or settings.DEFAULT_FEISHU_WEBHOOK_URL
                    )

                    if webhook_url:
                        # 获取业务名称
                        biz_result = await db.execute(
                            select(Business).where(Business.id == execution.business_id)
                        )
                        business = biz_result.scalar_one_or_none()
                        business_name = business.name if business else '未知业务'

                        # 获取执行环境名称
                        environment_name = None
                        if execution.environment_id:
                            env_result = await db.execute(
                                select(Environment).where(Environment.id == execution.environment_id)
                            )
                            env = env_result.scalar_one_or_none()
                            environment_name = env.name if env else None

                        # 获取任务名称（如有）
                        task_name = scheduled_task.name if scheduled_task else None

                        # 异步发送通知（不阻塞回调响应）
                        asyncio.create_task(
                            send_feishu_notification(
                                webhook_url=webhook_url,
                                execution_id=execution_id,
                                business_name=business_name,
                                completed_at=execution.completed_at,
                                result_count=request.result_count,
                                oss_report_url=oss_url,
                                feishu_notify_user_id=scheduled_task.feishu_notify_user_id if scheduled_task else None,
                                environment_name=environment_name,
                                task_name=task_name,
                            )
                        )
                except Exception as notify_err:
                    logger.warning(f'[Internal] 飞书通知发送失败（不影响主流程）: {notify_err}')

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
