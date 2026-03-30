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
    """Kubernetes Job status monitor.

    Periodically checks executions in 'running' state. If the corresponding K8s
    Job has failed or no longer exists, updates the database status.
    """

    def __init__(self, interval_seconds: int = 30):
        self.interval_seconds = interval_seconds
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

        # Lazy initialization of K8s client
        self._batch_v1 = None
        self._core_v1 = None
        self._k8s_initialized = False

    def start(self):
        """Start the monitoring task."""
        if self._task:
            return

        # Only run in kubernetes mode
        if settings.EXECUTION_MODE.lower() != 'kubernetes':
            logger.info('[Monitor] 非 Kubernetes 模式，跳过 Job 监控')
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f'[Monitor] Job 监控已启动 (间隔: {self.interval_seconds}s)')

    async def stop(self):
        """Stop the monitoring task."""
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
        """Main monitoring loop."""
        while not self._stop_event.is_set():
            try:
                await self._check_running_jobs()
            except Exception as e:
                logger.exception(f'[Monitor] 检查 Job 状态失败: {e}')

            # Wait until next check; supports responding to stop event
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    def _init_k8s_client(self):
        """Initialize the K8s client."""
        if self._k8s_initialized:
            return True

        try:
            from kubernetes import client
            from kubernetes import config as k8s_config

            # Load K8s configuration
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
        """Check all tasks in running state."""
        if not self._init_k8s_client():
            return

        k8s_namespace = os.getenv('K8S_NAMESPACE', 'cloud-staging')

        async with AsyncSessionLocal() as db:
            # Query all running executions
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
        """Check the status of a single Job."""
        # Gen mode and Run mode use different Job name prefixes
        if execution.trigger_type == 'gen':
            job_name = f'webqa-gen-{str(execution.id)[:8]}'
        else:
            job_name = f'webqa-exec-{str(execution.id)[:8]}'

        try:
            # 1. Fetch Job status
            # Note: kubernetes python client's sync API blocks in asyncio;
            # ideally use run_in_executor; direct call kept for simplicity (low concurrency assumed)
            job = await asyncio.to_thread(
                self._batch_v1.read_namespaced_job, job_name, namespace
            )

            # 2. Inspect Job status
            status = job.status

            if status.failed and status.failed > 0:
                logger.warning(f'[Monitor] Job 已失败: {job_name}')

                reason = 'K8s Job 执行失败'
                if status.conditions:
                    reason = f'K8s Job 失败: {status.conditions[0].message}'

                await self._fail_execution(db, execution, reason)
                return

            # 3. Check Pod status (handles ImagePullBackOff, etc.)
            # Job may not be marked failed while Pods never come up
            pods = await asyncio.to_thread(
                self._core_v1.list_namespaced_pod,
                namespace,
                label_selector=f'job-name={job_name}'
            )

            if not pods.items:
                # No Pod yet: Job may have just been created, or something is wrong
                # Ignore for now; wait for next check (or could timeout by creation time)
                return

            pod = pods.items[0]
            pod_status = pod.status

            # Inspect container state
            if pod_status.container_statuses:
                for container_status in pod_status.container_statuses:
                    state = container_status.state
                    if state.waiting:
                        reason = state.waiting.reason
                        message = state.waiting.message

                        # Common fatal conditions
                        fatal_errors = ['ImagePullBackOff', 'ErrImagePull', 'CreateContainerConfigError', 'InvalidImageName']
                        if reason in fatal_errors:
                            logger.warning(f'[Monitor] Pod 处于致命错误状态: {job_name}, reason={reason}')
                            error_msg = f'启动失败: {reason} - {message}'
                            await self._fail_execution(db, execution, error_msg)

                            # Try to delete the bad Job to free resources
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
            # NotFound (404)
            if hasattr(e, 'status') and e.status == 404:
                # Job missing: manually deleted, or not created yet
                # If started long ago (e.g. 5+ minutes) and still no Job, mark as failed
                start_time = execution.started_at
                if start_time and (now_with_tz() - start_time) > timedelta(minutes=5):
                    logger.warning(f'[Monitor] Job 不存在且已超时: {job_name}')
                    await self._fail_execution(db, execution, 'K8s Job 不存在或已丢失')
            else:
                logger.error(f'[Monitor] 检查 Job {job_name} 出错: {e}')

    async def _fail_execution(self, db, execution: Execution, error_message: str):
        """Mark the execution as failed."""
        execution.status = 'failed'
        execution.error_message = error_message
        execution.completed_at = now_with_tz()
        await db.commit()
        logger.info(f'[Monitor] 已更新任务 {execution.id} 为 failed: {error_message}')


# Global singleton
job_monitor = JobMonitor()
