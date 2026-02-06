import asyncio
import logging
import os
from datetime import timedelta
from typing import Optional

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Execution
from app.utils.datetime_utils import now_with_tz
from sqlalchemy import select

logger = logging.getLogger(__name__)
settings = get_settings()


class JobMonitor:
    """K8s Job 状态监控器。

    定期检查处于 'running' 状态的 Kubernetes 任务。 如果发现对应的 K8s Job 已经失败或不存在，则更新数据库状态。
    """

    def __init__(self, interval_seconds: int = 30):
        self.interval_seconds = interval_seconds
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

        # K8s client 延迟初始化
        self._batch_v1 = None
        self._core_v1 = None
        self._k8s_initialized = False

    def start(self):
        """启动监控任务。"""
        if self._task:
            return

        # 仅在 kubernetes 模式下运行
        if settings.EXECUTION_MODE.lower() != 'kubernetes':
            logger.info('[Monitor] 非 Kubernetes 模式，跳过 Job 监控')
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f'[Monitor] Job 监控已启动 (间隔: {self.interval_seconds}s)')

    async def stop(self):
        """停止监控任务。"""
        if not self._task:
            return

        self._stop_event.set()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info('[Monitor] Job 监控已停止')

    async def _monitor_loop(self):
        """监控循环。"""
        while not self._stop_event.is_set():
            try:
                await self._check_running_jobs()
            except Exception as e:
                logger.exception(f'[Monitor] 检查 Job 状态失败: {e}')

            # 等待下一次检查，支持响应停止事件
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    def _init_k8s_client(self):
        """初始化 K8s 客户端。"""
        if self._k8s_initialized:
            return True

        try:
            from kubernetes import client
            from kubernetes import config as k8s_config

            # 加载 K8s 配置
            k8s_config_path = os.getenv('K8S_CONFIG_PATH')
            if k8s_config_path:
                k8s_config.load_kube_config(config_file=k8s_config_path)
            else:
                k8s_config.load_incluster_config()

            self._batch_v1 = client.BatchV1Api()
            self._core_v1 = client.CoreV1Api()
            self._k8s_initialized = True
            return True
        except Exception as e:
            logger.error(f'[Monitor] K8s 客户端初始化失败: {e}')
            return False

    async def _check_running_jobs(self):
        """检查所有 running 状态的任务。"""
        if not self._init_k8s_client():
            return

        k8s_namespace = os.getenv('K8S_NAMESPACE', 'cloud-staging')

        async with AsyncSessionLocal() as db:
            # 查询所有 running 的任务
            result = await db.execute(
                select(Execution).where(Execution.status == 'running')
            )
            executions = result.scalars().all()

            if not executions:
                return

            logger.debug(f'[Monitor] 检查 {len(executions)} 个运行中的任务')

            for execution in executions:
                await self._check_single_job(db, execution, k8s_namespace)

    async def _check_single_job(self, db, execution: Execution, namespace: str):
        """检查单个 Job 的状态。"""
        job_name = f'webqa-exec-{str(execution.id)[:8]}'

        try:
            # 1. 获取 Job 状态
            # 注意：kubernetes python client 的同步 API 在 asyncio 中会阻塞
            # 理想情况下应使用 run_in_executor，为了简单起见这里直接调用（假设并发低）
            job = await asyncio.to_thread(
                self._batch_v1.read_namespaced_job, job_name, namespace
            )

            # 2. 检查 Job 状态
            status = job.status

            if status.failed and status.failed > 0:
                # Job 已失败
                logger.warning(f'[Monitor] Job 已失败: {job_name}')

                # 尝试获取 Pod 日志或事件以确定原因
                reason = 'K8s Job 执行失败'
                if status.conditions:
                    reason = f'K8s Job 失败: {status.conditions[0].message}'

                await self._fail_execution(db, execution, reason)
                return

            # 3. 检查 Pod 状态 (处理 ImagePullBackOff 等情况)
            # Job 可能没 failed，但 Pod 一直起不来
            pods = await asyncio.to_thread(
                self._core_v1.list_namespaced_pod,
                namespace,
                label_selector=f'job-name={job_name}'
            )

            if not pods.items:
                # 找不到 Pod，可能 Job 刚创建还没调度，或者是异常
                # 暂时忽略，等待下次检查（或者可以检查创建时间是否超时）
                return

            pod = pods.items[0]
            pod_status = pod.status

            # 检查容器状态
            if pod_status.container_statuses:
                for container_status in pod_status.container_statuses:
                    state = container_status.state
                    if state.waiting:
                        reason = state.waiting.reason
                        message = state.waiting.message

                        # 常见致命错误
                        fatal_errors = ['ImagePullBackOff', 'ErrImagePull', 'CreateContainerConfigError', 'InvalidImageName']
                        if reason in fatal_errors:
                            logger.warning(f'[Monitor] Pod 处于致命错误状态: {job_name}, reason={reason}')
                            error_msg = f'启动失败: {reason} - {message}'
                            await self._fail_execution(db, execution, error_msg)

                            # 尝试删除错误的 Job 以清理资源
                            try:
                                await asyncio.to_thread(
                                    self._batch_v1.delete_namespaced_job,
                                    job_name,
                                    namespace,
                                    propagation_policy='Background'
                                )
                            except:
                                pass
                            return

        except Exception as e:
            # 如果是 NotFound 错误 (404)
            if hasattr(e, 'status') and e.status == 404:
                # Job 不存在，可能是被手动删除了，或者还没创建成功
                # 检查任务开始时间，如果已经过去很久（例如 5 分钟）还找不到 Job，则判定失败
                start_time = execution.started_at
                if start_time and (now_with_tz() - start_time) > timedelta(minutes=5):
                    logger.warning(f'[Monitor] Job 不存在且已超时: {job_name}')
                    await self._fail_execution(db, execution, 'K8s Job 不存在或已丢失')
            else:
                logger.error(f'[Monitor] 检查 Job {job_name} 出错: {e}')

    async def _fail_execution(self, db, execution: Execution, error_message: str):
        """将任务标记为失败。"""
        execution.status = 'failed'
        execution.error_message = error_message
        execution.completed_at = now_with_tz()
        await db.commit()
        logger.info(f'[Monitor] 已更新任务 {execution.id} 为 failed: {error_message}')


# 全局单例
job_monitor = JobMonitor()
