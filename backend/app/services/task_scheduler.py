"""Task scheduler service using APScheduler.

This service manages scheduled tasks execution:
- Loads enabled scheduled tasks on startup
- Triggers executions based on cron expressions
- Implements job queue when MAX_CONCURRENT_JOBS is reached
- Supports dynamic task management (add/update/remove)
"""
import asyncio
import logging
from typing import Optional
from uuid import UUID

import pytz
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Execution, ScheduledTask
from app.services.executor import run_execution
from app.utils.cron_utils import get_next_run_time
from app.utils.datetime_utils import now_with_tz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

logger = logging.getLogger(__name__)
settings = get_settings()


class TaskScheduler:
    """Scheduled task manager using APScheduler."""

    def __init__(self):
        # Use Asia/Shanghai timezone for scheduler
        self.timezone = pytz.timezone('Asia/Shanghai')
        self.scheduler = AsyncIOScheduler(timezone=self.timezone)
        self._job_queue = asyncio.Queue()
        self._queue_processor_task: Optional[asyncio.Task] = None
        self._started = False

    async def start(self):
        """Start the scheduler and load all enabled tasks."""
        if self._started:
            logger.warning('[TaskScheduler] Already started')
            return

        logger.info('[TaskScheduler] Starting scheduler...')

        # Start APScheduler
        self.scheduler.start()

        # Start job queue processor
        self._queue_processor_task = asyncio.create_task(self._process_job_queue())

        # Load all enabled tasks
        await self._load_all_tasks()

        self._started = True
        logger.info('[TaskScheduler] Scheduler started successfully')

    async def stop(self):
        """Stop the scheduler."""
        if not self._started:
            return

        logger.info('[TaskScheduler] Stopping scheduler...')

        # Stop APScheduler
        self.scheduler.shutdown(wait=False)

        # Stop queue processor
        if self._queue_processor_task:
            self._queue_processor_task.cancel()
            try:
                await self._queue_processor_task
            except asyncio.CancelledError:
                pass

        self._started = False
        logger.info('[TaskScheduler] Scheduler stopped')

    async def _load_all_tasks(self):
        """Load all enabled scheduled tasks from database."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ScheduledTask).where(ScheduledTask.enabled == True)
            )
            tasks = result.scalars().all()

            logger.info(f'[TaskScheduler] Loading {len(tasks)} enabled tasks')

            for task in tasks:
                try:
                    await self._add_task_to_scheduler(task)
                except Exception as e:
                    logger.exception(f'[TaskScheduler] Failed to load task {task.id}: {e}')

    async def _add_task_to_scheduler(self, task: ScheduledTask):
        """Add a task to APScheduler."""
        job_id = str(task.id)

        # Remove existing job if any
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        # Create cron trigger
        try:
            trigger = CronTrigger.from_crontab(task.cron_expression, timezone=self.timezone)
        except Exception as e:
            logger.error(f'[TaskScheduler] Invalid cron expression for task {task.id}: {e}')
            return

        # Add job to scheduler
        self.scheduler.add_job(
            self._trigger_scheduled_execution,
            trigger=trigger,
            id=job_id,
            args=[str(task.id)],
            replace_existing=True,
            max_instances=1,  # Prevent concurrent executions of same task
        )

        # Update next_run_at in database
        next_run = get_next_run_time(task.cron_expression)
        if next_run:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(ScheduledTask).where(ScheduledTask.id == task.id)
                )
                db_task = result.scalar_one_or_none()
                if db_task:
                    db_task.next_run_at = next_run
                    await db.commit()

        logger.info(f'[TaskScheduler] Task {task.name} ({task.id}) scheduled with cron: {task.cron_expression}')

    async def _trigger_scheduled_execution(self, task_id: str):
        """Trigger execution for a scheduled task.

        This is called by APScheduler when cron triggers. Implements queue
        mechanism when MAX_CONCURRENT_JOBS is reached.
        """
        logger.info(f'[TaskScheduler] Cron triggered for task {task_id}')

        try:
            async with AsyncSessionLocal() as db:
                # Load task
                result = await db.execute(
                    select(ScheduledTask).where(ScheduledTask.id == UUID(task_id))
                )
                task = result.scalar_one_or_none()

                if not task:
                    logger.error(f'[TaskScheduler] Task {task_id} not found')
                    return

                if not task.enabled:
                    logger.info(f'[TaskScheduler] Task {task_id} is disabled, skipping')
                    return

                # Update last_run_at and next_run_at
                task.last_run_at = now_with_tz()
                next_run = get_next_run_time(task.cron_expression)
                if next_run:
                    task.next_run_at = next_run
                await db.commit()

                # Check current running jobs count
                running_count = await self._get_running_jobs_count(db)

                if running_count >= settings.MAX_CONCURRENT_JOBS:
                    # Queue the job
                    logger.info(f'[TaskScheduler] Max concurrent jobs ({settings.MAX_CONCURRENT_JOBS}) reached, queueing task {task_id}')
                    await self._job_queue.put(task_id)
                    return

                # Execute immediately
                await self._execute_scheduled_task(task)

        except Exception as e:
            logger.exception(f'[TaskScheduler] Error triggering task {task_id}: {e}')

    async def _execute_scheduled_task(self, task: ScheduledTask):
        """Execute a scheduled task by creating an execution."""
        try:
            async with AsyncSessionLocal() as db:
                # Create execution record
                execution = Execution(
                    business_id=task.business_id,
                    environment_id=task.environment_id,
                    trigger_type='scheduled',
                    scheduled_task_id=task.id,
                    model=task.model,
                    workers=task.workers,
                    test_case_ids=[str(case_id) for case_id in task.test_case_ids],
                    status='pending',
                )

                db.add(execution)
                await db.commit()
                await db.refresh(execution)

                execution_id = str(execution.id)

                logger.info(f'[TaskScheduler] Created execution {execution_id} for task {task.name} ({task.id})')

                # Trigger execution (don't wait)
                asyncio.create_task(run_execution(execution_id))

        except Exception as e:
            logger.exception(f'[TaskScheduler] Failed to execute task {task.id}: {e}')

    async def _process_job_queue(self):
        """Process queued jobs when slots become available.

        This background task continuously checks if there are jobs in the queue
        and executes them when running jobs count drops below
        MAX_CONCURRENT_JOBS.
        """
        logger.info('[TaskScheduler] Job queue processor started')

        while True:
            try:
                # Wait for a queued job (non-blocking check)
                try:
                    task_id = await asyncio.wait_for(self._job_queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    # No queued jobs, continue loop
                    continue

                logger.info(f'[TaskScheduler] Processing queued task {task_id}')

                # Wait until there's a free slot
                while True:
                    async with AsyncSessionLocal() as db:
                        running_count = await self._get_running_jobs_count(db)

                        if running_count < settings.MAX_CONCURRENT_JOBS:
                            # Free slot available, execute
                            result = await db.execute(
                                select(ScheduledTask).where(ScheduledTask.id == UUID(task_id))
                            )
                            task = result.scalar_one_or_none()

                            if task and task.enabled:
                                await self._execute_scheduled_task(task)
                            break

                    # Wait before checking again
                    await asyncio.sleep(5)

            except asyncio.CancelledError:
                logger.info('[TaskScheduler] Queue processor cancelled')
                break
            except Exception as e:
                logger.exception(f'[TaskScheduler] Error in queue processor: {e}')
                await asyncio.sleep(5)

    async def _get_running_jobs_count(self, db) -> int:
        """Get count of currently running or pending jobs across all
        businesses."""
        result = await db.execute(
            select(Execution).where(
                Execution.status.in_(['pending', 'running'])
            )
        )
        executions = result.scalars().all()
        return len(executions)

    # Public methods for task management

    async def add_task(self, task: ScheduledTask):
        """Add a new task to scheduler."""
        if not self._started:
            logger.warning('[TaskScheduler] Scheduler not started, task will be loaded on next start')
            return

        await self._add_task_to_scheduler(task)

    async def update_task(self, task: ScheduledTask):
        """Update an existing task in scheduler."""
        if not self._started:
            return

        job_id = str(task.id)

        if task.enabled:
            # Re-add task (will replace existing)
            await self._add_task_to_scheduler(task)
        else:
            # Remove task if disabled
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logger.info(f'[TaskScheduler] Task {task.name} ({task.id}) removed (disabled)')

    async def remove_task(self, task_id: str):
        """Remove a task from scheduler."""
        if not self._started:
            return

        job_id = str(task_id)
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            logger.info(f'[TaskScheduler] Task {task_id} removed from scheduler')


# Global singleton
task_scheduler = TaskScheduler()
