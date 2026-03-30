"""
Execution service - Unified execution mode

All modes execute by starting an independent Agent process, which callbacks Backend API upon completion.
- local: Start subprocess to run run_webqa.py
- kubernetes: Create K8s Job to run
"""
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import yaml
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Environment, Execution, TestCase
from app.utils.datetime_utils import now_with_tz
from sqlalchemy import select

settings = get_settings()
logger = logging.getLogger(__name__)

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


def _compute_k8s_resources(workers: int, business_id: Optional[UUID] = None) -> tuple[int, int]:
    """Calculate resource quotas for K8s Job.

    Chromium uses --disable-dev-shm-usage, no longer needs /dev/shm emptyDir volume,
    memory scales linearly with the number of workers.

    High memory businesses (HEAVY_RESOURCE_BUSINESS_IDS) allocate more memory per worker,
    suitable for streaming rendering scenarios like AI chat (JS heap can reach 1.5Gi/instance).

    Returns:
        (cpu_limit, memory_gi)
    """
    heavy_ids_raw = os.getenv('HEAVY_RESOURCE_BUSINESS_IDS', '')
    heavy_ids = {s.strip() for s in heavy_ids_raw.split(',') if s.strip()}
    is_heavy = business_id is not None and str(business_id) in heavy_ids

    w = max(1, workers)
    if is_heavy:
        # High memory mode: 2Gi per worker (JS heap heavy) + 2Gi Python/base overhead
        # workers │ CPU │ Memory
        # 1       │ 2c  │ 4Gi
        # 2       │ 4c  │ 6Gi
        # 3       │ 6c  │ 8Gi
        cpu_limit = w * 2
        memory_gi = w * 2 + 2
    else:
        # Standard mode: 1Gi per worker + 1Gi Python/base overhead
        # workers │ CPU │ Memory
        # 1       │ 2c  │ 2Gi
        # 2       │ 3c  │ 3Gi
        # 3       │ 4c  │ 4Gi
        cpu_limit = min(w + 1, 4)
        memory_gi = w + 1

    return cpu_limit, memory_gi


# Store active processes/containers for cancellation
_active_processes: Dict[str, asyncio.subprocess.Process] = {}
_active_containers: Dict[str, str] = {}  # execution_id -> container_id (Docker mode)


async def stop_execution(execution_id: str) -> bool:
    """Stop a running execution."""
    # 1. Try to stop local subprocess
    if execution_id in _active_processes:
        process = _active_processes[execution_id]
        try:
            logger.info(f'[Executor] Stopping process {process.pid} for execution {execution_id}')
            process.terminate()
            # Give it a chance to terminate gracefully
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning(f'[Executor] Process {process.pid} did not terminate, killing...')
                process.kill()

            return True
        except Exception as e:
            logger.error(f'[Executor] Failed to stop process: {e}')
            return False

    # 2. Docker mode: stop the container
    if execution_id in _active_containers:
        return await _stop_docker_container(execution_id)

    # 3. K8s mode: delete the Job from cluster
    if settings.is_kubernetes_mode:
        return await _stop_k8s_job(execution_id)

    return False


async def _stop_k8s_job(execution_id: str) -> bool:
    """Delete K8s Job to stop a running execution."""
    try:
        from kubernetes import client
        from kubernetes import config as k8s_config
    except ImportError:
        logger.error('[Executor] kubernetes package not installed')
        return False

    try:
        k8s_config_path = os.getenv('K8S_CONFIG_PATH')
        if k8s_config_path:
            k8s_config.load_kube_config(config_file=k8s_config_path)
        else:
            k8s_config.load_incluster_config()

        batch_v1 = client.BatchV1Api()
        k8s_namespace = os.getenv('K8S_NAMESPACE', 'webqa')

        # Query execution trigger_type to determine Job name prefix
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Execution).where(Execution.id == UUID(execution_id))
            )
            execution = result.scalar_one_or_none()

        if not execution:
            logger.warning(f'[Executor] Execution not found for stop: {execution_id}')
            return False

        if execution.trigger_type == 'gen':
            job_name = f'webqa-gen-{execution_id[:8]}'
        else:
            job_name = f'webqa-exec-{execution_id[:8]}'

        # Delete Job and its Pods (propagationPolicy=Background will cascade delete Pods)
        await asyncio.to_thread(
            batch_v1.delete_namespaced_job,
            job_name,
            k8s_namespace,
            propagation_policy='Background',
        )
        logger.info(f'[Executor] K8s Job deleted: {job_name}')
        return True

    except Exception as e:
        if hasattr(e, 'status') and e.status == 404:
            logger.warning(f'[Executor] K8s Job not found (already deleted): {execution_id[:8]}')
            return True  # Job is no longer there, consider it successful
        logger.error(f'[Executor] Failed to delete K8s Job: {e}')
        return False


def generate_sso_cookies(username: str, password: str, env: str = 'prod') -> Tuple[Optional[str], Optional[List[Dict]]]:
    """Generate cookies using authentication provider.

    Provider is auto-discovered from backend/app/providers/:
    - Internal deployment: Auto-load custom SSO implementation
    - Open-source deployment: Fallback to CookiesAuthProvider (does not support generating from credentials)
    """
    try:
        from app.providers import get_provider

        auth = get_provider('auth')
        logger.info(f'[Auth] 生成 cookies: username={username}, env={env}, provider={auth.name}')
        cookies = auth.generate_cookies(username, password, env)
        logger.info('[Auth] Cookies 生成成功')
        return None, cookies
    except Exception:
        logger.exception(f'[Auth] Cookies 生成失败: username={username}, env={env}')
        raise


def _time_id_prefix(execution_id: str, started_at=None) -> str:
    """Generate the 'time_id first part' used for remote storage paths:

    {YYYYMMDD_HHMMSS}_{exec_id first 8 chars}.
    """
    from datetime import datetime

    id_part = (execution_id or '').replace('-', '')[:8]
    if started_at:
        if hasattr(started_at, 'strftime'):
            time_part = started_at.strftime('%Y%m%d_%H%M%S')
        else:
            time_part = datetime.fromisoformat(str(started_at).replace('Z', '+00:00')).strftime('%Y%m%d_%H%M%S')
    else:
        time_part = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f'{time_part}_{id_part}'


def upload_report_to_oss(report_dir: str, oss_key_dir: str) -> Optional[str]:
    """Upload report directory to remote storage.

    Provider is auto-discovered from backend/app/providers/:
    - Internal deployment: Auto-load custom storage implementation
    - Open-source deployment: Fallback to LocalStorageProvider (does not upload, returns None)
    """
    if not report_dir or not os.path.exists(report_dir):
        logger.warning(f'[Storage] 报告目录不存在: {report_dir}')
        return None

    try:
        from app.providers import get_provider

        storage = get_provider('storage')
        # Compatibility for callers passing only execution_id, uniformly converting to time-prefixed directory
        normalized_key = (
            oss_key_dir if oss_key_dir and '_' in oss_key_dir else _time_id_prefix(oss_key_dir)
        )

        logger.info(f'[Storage] 开始上传: {report_dir}, provider={storage.name}')
        report_url = storage.upload_report(report_dir, normalized_key)

        if report_url:
            logger.info(f'[Storage] 上传成功，报告 URL: {report_url}')
        else:
            logger.info('[Storage] Provider 未上传报告（本地存储模式）')

        return report_url

    except Exception:
        logger.exception(f'[Storage] 上传失败: report_dir={report_dir}, oss_key_dir={oss_key_dir}')
        return None


async def run_execution(execution_id: str, case_data: Optional[Dict[str, Any]] = None, gen_config_dict: Optional[Dict[str, Any]] = None):
    """Execute test task (entry function).

    Select startup method based on EXECUTION_MODE configuration:
    - local: Start subprocess
    - kubernetes: Create K8s Job

    All modes uniformly receive results via callback API.

    Args:
        execution_id: Execution record ID
        case_data: Case data passed directly from frontend in Debug mode, not saved to DB.
            Format: {case_id_str: {login_required: bool, name: str, steps: [...], ...}}
        gen_config_dict: Raw config dict for Gen mode (without api_key, injected by executor)
    """
    # Check execution trigger_type first
    trigger_type = None
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(Execution).where(Execution.id == UUID(execution_id))
            )
            execution = result.scalar_one_or_none()
            if execution:
                trigger_type = execution.trigger_type
        except Exception as e:
            logger.exception(f'[Run] Failed to check execution type: {e}')
            return

    mode = settings.EXECUTION_MODE.lower()

    if trigger_type == 'gen':
        if mode == 'kubernetes':
            await _start_gen_k8s(execution_id, gen_config_dict)
        elif mode == 'docker':
            await _start_gen_docker(execution_id, gen_config_dict)
        else:
            await _start_gen_executor(execution_id, gen_config_dict)
    elif mode == 'kubernetes':
        await _start_agent_k8s(execution_id, case_data=case_data)
    elif mode == 'docker':
        await _start_agent_docker(execution_id, case_data=case_data)
    else:
        # local mode (default)
        await _start_agent_subprocess(execution_id, case_data=case_data)


async def _start_gen_executor(execution_id: str, gen_config_dict: Optional[Dict[str, Any]] = None):
    """Gen Mode (local): Start subprocess running gen_webqa.py.

    Accepts a raw config dict (without api_key). Secrets are injected here from
    backend settings before writing the config file.
    """
    import json

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(Execution).where(Execution.id == UUID(execution_id))
            )
            execution = result.scalar_one_or_none()

            if not execution:
                logger.error(f'[Gen] Execution not found: {execution_id}')
                return

            # If config dict is not passed (e.g. restart), load from execution.config
            if not gen_config_dict and execution.config:
                gen_config_dict = execution.config

            if not gen_config_dict:
                execution.status = 'failed'
                execution.error_message = 'Gen configuration missing'
                execution.completed_at = now_with_tz()
                await db.commit()
                return

            # Inject API key and base URL from backend settings
            llm_cfg = gen_config_dict.setdefault('llm_config', {})
            model_name = llm_cfg.get('model', '')
            if not llm_cfg.get('api_key'):
                llm_cfg['api_key'] = settings.get_api_key_for_model(model_name)
            if not llm_cfg.get('base_url'):
                llm_cfg['base_url'] = settings.get_base_url_for_model(model_name)
            if not llm_cfg.get('max_tokens'):
                llm_cfg['max_tokens'] = 8192
            if not llm_cfg.get('max_tokens'):
                llm_cfg['max_tokens'] = 8192

            api_key = llm_cfg.get('api_key', '')
            base_url = llm_cfg.get('base_url', '')

            # Write config to file (JSON format, compatible with GenConfig loading)
            config_dir = Path(settings.shared_reports_path) / f'exec_{execution_id}'
            config_dir.mkdir(parents=True, exist_ok=True)
            config_file = config_dir / 'config.yaml'

            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(gen_config_dict, f, indent=2, ensure_ascii=False)

            config_path = str(config_file)

            # Update status
            execution.status = 'running'
            execution.started_at = now_with_tz()
            await db.commit()

            logger.info(f'[Gen] Starting subprocess: {execution_id}')

            env = os.environ.copy()
            env['EXECUTION_ID'] = execution_id
            env['SHARED_STORAGE_PATH'] = settings.effective_shared_storage_path
            env['BACKEND_CALLBACK_URL'] = settings.BACKEND_CALLBACK_URL
            if api_key:
                env['OPENAI_API_KEY'] = api_key
            if base_url:
                env['OPENAI_BASE_URL'] = base_url

            process = await asyncio.create_subprocess_exec(
                'python', '-m', 'backend.gen_webqa',
                '-c', config_path,
                '--execution-id', execution_id,
                '--report-dir', str(config_dir),
                '--stdout',
                cwd=str(PROJECT_ROOT),
                env=env,
            )

            logger.info(f'[Gen] Subprocess started: PID={process.pid}')
            _active_processes[execution_id] = process

            # Monitor process (same as local mode)
            async def monitor_process():
                timeout_seconds = settings.JOB_TIMEOUT_SECONDS
                try:
                    await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
                    logger.info(f'[Gen] Subprocess finished: PID={process.pid}, exit_code={process.returncode}')

                    # Remove from active processes
                    _active_processes.pop(execution_id, None)

                    if process.returncode != 0:
                        logger.warning(f'[Gen] Subprocess exited with error: {process.returncode}')
                        await asyncio.sleep(2)
                        async with AsyncSessionLocal() as db:
                            result = await db.execute(select(Execution).where(Execution.id == UUID(execution_id)))
                            exec_record = result.scalar_one_or_none()
                            if exec_record and exec_record.status == 'running':
                                exec_record.status = 'failed'
                                exec_record.error_message = f'Agent exited with code {process.returncode}'
                                exec_record.completed_at = now_with_tz()
                                await db.commit()

                except asyncio.TimeoutError:
                    logger.warning(f'[Gen] Subprocess timeout: PID={process.pid}')
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=10)
                    except:
                        process.kill()

                    async with AsyncSessionLocal() as db:
                        result = await db.execute(select(Execution).where(Execution.id == UUID(execution_id)))
                        exec_record = result.scalar_one_or_none()
                        if exec_record and exec_record.status == 'running':
                            exec_record.status = 'timeout'
                            exec_record.error_message = 'Execution timed out'
                            exec_record.completed_at = now_with_tz()
                            await db.commit()

                except Exception as e:
                    logger.exception(f'[Gen] Monitor exception: {e}')

            asyncio.create_task(monitor_process())

        except Exception as e:
            logger.exception(f'[Gen] Start failed: {e}')
            try:
                execution.status = 'failed'
                execution.error_message = f'Failed to start process: {e}'
                execution.completed_at = now_with_tz()
                await db.commit()
            except:
                pass


# =============================================================================
# GEN + KUBERNETES MODE: Create K8s Job to run gen_webqa
# =============================================================================

async def _start_gen_k8s(execution_id: str, gen_config_dict: Optional[Dict[str, Any]] = None):
    """Gen Mode (kubernetes): Create a K8s Job running gen_webqa.py.

    Accepts a raw config dict (without api_key). Secrets are injected here from
    backend settings before writing the config to shared storage and creating
    the K8s Job. No webqa_agent imports are performed in the backend process —
    all webqa_agent code runs inside the Job container.
    """
    import json

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(Execution).where(Execution.id == UUID(execution_id))
            )
            execution = result.scalar_one_or_none()

            if not execution:
                logger.error(f'[Gen K8s] Execution not found: {execution_id}')
                return

            # If config dict is not passed (e.g. restart), load from execution.config
            if not gen_config_dict and execution.config:
                gen_config_dict = execution.config

            if not gen_config_dict:
                execution.status = 'failed'
                execution.error_message = 'Gen configuration missing'
                execution.completed_at = now_with_tz()
                await db.commit()
                return

            # Inject API key and base URL from backend settings
            llm_cfg = gen_config_dict.setdefault('llm_config', {})
            model_name = llm_cfg.get('model', '')
            if not llm_cfg.get('api_key'):
                llm_cfg['api_key'] = settings.get_api_key_for_model(model_name)
            if not llm_cfg.get('base_url'):
                llm_cfg['base_url'] = settings.get_base_url_for_model(model_name)
            if not llm_cfg.get('max_tokens'):
                llm_cfg['max_tokens'] = 8192

            api_key = llm_cfg.get('api_key', '')
            base_url = llm_cfg.get('base_url', '')

            # Write config to shared storage so the K8s Job container can read it
            config_dir = Path(settings.shared_reports_path) / f'exec_{execution_id}'
            config_dir.mkdir(parents=True, exist_ok=True)
            config_file = config_dir / 'config.yaml'

            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(gen_config_dict, f, indent=2, ensure_ascii=False)

            config_path = str(config_file)

            # Update status
            execution.status = 'running'
            execution.started_at = now_with_tz()
            await db.commit()

            logger.info(f'[Gen K8s] Creating K8s Job: {execution_id}')

            try:
                job_name = await _create_gen_k8s_job(
                    execution_id=execution_id,
                    config_path=config_path,
                    report_dir=str(config_dir),
                    workers=execution.workers or 1,
                    api_key=api_key,
                    base_url=base_url,
                    business_id=execution.business_id,
                )
                logger.info(f'[Gen K8s] Job created: {job_name}')
            except Exception as e:
                logger.exception(f'[Gen K8s] Failed to create Job: {e}')
                execution.status = 'failed'
                execution.error_message = f'Failed to create K8s Gen Job: {e}'
                execution.completed_at = now_with_tz()
                await db.commit()

        except Exception as e:
            logger.exception(f'[Gen K8s] Start failed: {e}')
            try:
                execution.status = 'failed'
                execution.error_message = f'Failed to start Gen execution: {e}'
                execution.completed_at = now_with_tz()
                await db.commit()
            except Exception:
                pass


async def _create_gen_k8s_job(
    execution_id: str,
    config_path: str,
    report_dir: str,
    workers: int,
    api_key: str,
    base_url: str,
    business_id: Optional[UUID] = None,
) -> str:
    """Create a Kubernetes Job that runs gen_webqa.py inside the agent
    image."""
    try:
        from kubernetes import client
        from kubernetes import config as k8s_config
    except ImportError:
        raise RuntimeError('kubernetes 库未安装，请运行: pip install kubernetes')

    k8s_config_path = os.getenv('K8S_CONFIG_PATH')
    if k8s_config_path:
        k8s_config.load_kube_config(config_file=k8s_config_path)
    else:
        k8s_config.load_incluster_config()

    batch_v1 = client.BatchV1Api()

    k8s_namespace = os.getenv('K8S_NAMESPACE', 'webqa')
    k8s_job_image = os.getenv('K8S_JOB_IMAGE', 'webqa-agent:latest')
    k8s_pvc_name = os.getenv('K8S_PVC_NAME', 'webqa-pvc')
    k8s_sa_name = os.getenv('K8S_JOB_SERVICE_ACCOUNT', 'webqa-agent-sa')
    cpu_limit, memory_gi = _compute_k8s_resources(workers, business_id)

    job_name = f'webqa-gen-{execution_id[:8]}'

    job = client.V1Job(
        api_version='batch/v1',
        kind='Job',
        metadata=client.V1ObjectMeta(
            name=job_name,
            namespace=k8s_namespace,
            labels={
                'app': 'webqa-agent',
                'execution-id': execution_id,
                'execution-type': 'gen',
            },
        ),
        spec=client.V1JobSpec(
            ttl_seconds_after_finished=7200,
            active_deadline_seconds=settings.JOB_TIMEOUT_SECONDS,
            backoff_limit=0,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(
                    labels={'app': 'webqa-agent', 'execution-type': 'gen'},
                ),
                spec=client.V1PodSpec(
                    restart_policy='Never',
                    service_account_name=k8s_sa_name or None,
                    image_pull_secrets=[
                        client.V1LocalObjectReference(name='regcred-vpc')
                    ],
                    containers=[
                        client.V1Container(
                            name='webqa-agent',
                            image=k8s_job_image,
                            command=['python', '-m', 'backend.gen_webqa'],
                            args=[
                                '-c', config_path,
                                '--execution-id', execution_id,
                                '--report-dir', report_dir,
                                '--stdout',
                            ],
                            env=[
                                client.V1EnvVar(name='EXECUTION_ID', value=execution_id),
                                client.V1EnvVar(name='SHARED_STORAGE_PATH', value='/shared'),
                                client.V1EnvVar(name='BACKEND_CALLBACK_URL', value=settings.BACKEND_CALLBACK_URL),
                                client.V1EnvVar(name='OPENAI_API_KEY', value=api_key),
                                client.V1EnvVar(name='OPENAI_BASE_URL', value=base_url),
                            ],
                            resources=client.V1ResourceRequirements(
                                requests={'cpu': '0.5', 'memory': f'{memory_gi}Gi'},
                                limits={'cpu': str(cpu_limit), 'memory': f'{memory_gi}Gi'},
                            ),
                            volume_mounts=[
                                client.V1VolumeMount(name='shared-storage', mount_path='/shared'),
                            ],
                        ),
                    ],
                    volumes=[
                        client.V1Volume(
                            name='shared-storage',
                            persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                                claim_name=k8s_pvc_name,
                            ),
                        ),
                    ],
                ),
            ),
        ),
    )

    batch_v1.create_namespaced_job(namespace=k8s_namespace, body=job)
    return job_name


# =============================================================================
# COMMON: Shared preparation logic for Run mode
# =============================================================================

def _build_cases_from_request(
    case_data: Dict[str, Any],
    business_id: Optional[UUID] = None,
) -> list:
    """Build case object list from frontend-passed case data without querying
    the DB."""
    from types import SimpleNamespace

    cases = []
    for tc_id_str, data in case_data.items():
        case = SimpleNamespace(
            id=UUID(tc_id_str),
            business_id=business_id,
            name=data.get('name', 'Draft Case'),
            login_required=data.get('login_required', False),
            steps=data.get('steps', []),
            snapshot=data.get('snapshot'),
            use_snapshot=data.get('use_snapshot'),
        )
        cases.append(case)
        logger.info(f'[Config] Built case from frontend data: {tc_id_str}, '
                    f'name={case.name}, login_required={case.login_required}')
    return cases


async def _prepare_run_config(
    execution_id: str,
    case_data: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Shared preparation for Run mode: fetch data, build config, write to shared storage.

    All Run modes (local/docker/k8s) share this preparation flow.
    On success updates execution.status to 'running'; on failure to 'failed'.

    Returns:
        On success: dict with config_path, config_dir, api_key, base_url, workers, business_id.
        On failure: None (DB status already updated).
    """
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(Execution).where(Execution.id == UUID(execution_id))
            )
            execution = result.scalar_one_or_none()
            if not execution:
                logger.error(f'[Prepare] Execution not found: {execution_id}')
                return None

            environment, test_cases, error = await _fetch_execution_data(db, execution)
            if error:
                logger.error(f'[Prepare] 获取执行数据失败: execution_id={execution_id}, error={error}')
                execution.status = 'failed'
                execution.error_message = error
                execution.completed_at = now_with_tz()
                await db.commit()
                return None

            if case_data:
                frontend_cases = _build_cases_from_request(
                    case_data, business_id=execution.business_id
                )
                case_map = {str(tc.id): tc for tc in test_cases}
                case_map.update({str(tc.id): tc for tc in frontend_cases})
                test_cases = [case_map[cid] for cid in execution.test_case_ids if cid in case_map]

            if not test_cases:
                execution.status = 'failed'
                execution.error_message = '没有可执行的测试用例'
                execution.completed_at = now_with_tz()
                await db.commit()
                return None

            cookies = None
            if environment.auth_type == 'sso' and environment.sso_username:
                try:
                    sso_env = getattr(environment, 'sso_env', 'prod') or 'prod'
                    logger.info(f"[SSO] Environment ID: {environment.id}, sso_env from DB: '{environment.sso_env}', using: '{sso_env}'")
                    _, cookies = generate_sso_cookies(environment.sso_username, environment.sso_password, sso_env)
                except Exception as e:
                    execution.status = 'failed'
                    execution.error_message = f'SSO 认证失败: {e}'
                    execution.completed_at = now_with_tz()
                    await db.commit()
                    return None
            elif environment.auth_type == 'cookies' and environment.cookies:
                cookies = environment.cookies

            configs = _build_agent_configs(
                environment, test_cases, execution.workers, cookies
            )
            if not configs:
                execution.status = 'failed'
                execution.error_message = '没有可执行的测试用例'
                execution.completed_at = now_with_tz()
                await db.commit()
                return None

            api_key = settings.get_api_key_for_model(execution.model)
            base_url = settings.get_base_url_for_model(execution.model)
            for config in configs:
                config['llm_config'] = {
                    'api': settings.LLM_API,
                    'api_key': api_key,
                    'base_url': base_url,
                    'model': execution.model,
                }

            config_dir = Path(settings.shared_reports_path) / f'exec_{execution_id}'
            config_dir.mkdir(parents=True, exist_ok=True)

            if len(configs) == 1:
                config_file = config_dir / 'config.yaml'
                with open(config_file, 'w', encoding='utf-8') as f:
                    yaml.dump(configs[0], f, allow_unicode=True)
                config_path = str(config_file)
            else:
                for idx, config in enumerate(configs):
                    config_file = config_dir / f'config_{idx}.yaml'
                    with open(config_file, 'w', encoding='utf-8') as f:
                        yaml.dump(config, f, allow_unicode=True)
                config_path = str(config_dir)

            execution.status = 'running'
            execution.started_at = now_with_tz()
            await db.commit()

            return {
                'config_path': config_path,
                'config_dir': str(config_dir),
                'api_key': api_key,
                'base_url': base_url,
                'workers': execution.workers,
                'business_id': execution.business_id,
            }

        except Exception as e:
            logger.exception(f'[Prepare] 准备执行失败: {e}')
            try:
                execution.status = 'failed'
                execution.error_message = f'准备执行失败: {e}'
                execution.completed_at = now_with_tz()
                await db.commit()
            except Exception:
                pass
            return None


# =============================================================================
# LOCAL MODE: Start subprocess
# =============================================================================

async def _start_agent_subprocess(execution_id: str, case_data: Optional[Dict[str, Any]] = None):
    """Local mode: start a subprocess to run the Agent."""
    prep = await _prepare_run_config(execution_id, case_data)
    if not prep:
        return

    try:
        logger.info(f'[Local] 启动子进程执行: {execution_id}')

        env = os.environ.copy()
        env['EXECUTION_ID'] = execution_id
        env['SHARED_STORAGE_PATH'] = settings.effective_shared_storage_path
        env['BACKEND_CALLBACK_URL'] = settings.BACKEND_CALLBACK_URL
        env['OPENAI_API_KEY'] = prep['api_key']
        env['OPENAI_BASE_URL'] = prep['base_url']
        env['WEBQA_CASE_TIMEOUT'] = str(settings.WEBQA_CASE_TIMEOUT)

        process = await asyncio.create_subprocess_exec(
            'python', '-m', 'backend.run_webqa',
            '-c', prep['config_path'],
            '-w', str(prep['workers']),
            '--execution-id', execution_id,
            '--report-dir', prep['config_dir'],
            '--stdout',
            cwd=str(PROJECT_ROOT),
            env=env,
        )

        logger.info(f'[Local] 子进程已启动: PID={process.pid}')
        _active_processes[execution_id] = process

        async def monitor_process():
            timeout_seconds = settings.JOB_TIMEOUT_SECONDS
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
                logger.info(f'[Local] 子进程结束: PID={process.pid}, exit_code={process.returncode}')
                _active_processes.pop(execution_id, None)

                if process.returncode != 0:
                    logger.warning(f'[Local] 子进程异常退出: exit_code={process.returncode}')
                    await asyncio.sleep(2)
                    async with AsyncSessionLocal() as db:
                        result = await db.execute(
                            select(Execution).where(Execution.id == UUID(execution_id))
                        )
                        exec_record = result.scalar_one_or_none()
                        if exec_record and exec_record.status == 'running':
                            exec_record.status = 'failed'
                            exec_record.error_message = f'Agent 异常退出 (exit_code={process.returncode})'
                            exec_record.completed_at = now_with_tz()
                            await db.commit()
                            logger.info(f'[Local] 已更新状态为 failed: {execution_id}')

            except asyncio.TimeoutError:
                logger.warning(f'[Local] 子进程超时 ({timeout_seconds}s): PID={process.pid}')
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=10)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()

                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(Execution).where(Execution.id == UUID(execution_id))
                    )
                    exec_record = result.scalar_one_or_none()
                    if exec_record and exec_record.status == 'running':
                        exec_record.status = 'timeout'
                        exec_record.error_message = f'执行超时（超过 {timeout_seconds // 3600} 小时）'
                        exec_record.completed_at = now_with_tz()
                        await db.commit()
                        logger.info(f'[Local] 已更新状态为 timeout: {execution_id}')

            except Exception as e:
                logger.exception(f'[Local] 监控进程异常: {e}')

        asyncio.create_task(monitor_process())

    except Exception as e:
        logger.exception(f'[Local] 启动失败: {e}')
        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(
                    select(Execution).where(Execution.id == UUID(execution_id))
                )
                execution = result.scalar_one_or_none()
                if execution and execution.status == 'running':
                    execution.status = 'failed'
                    execution.error_message = f'启动子进程失败: {e}'
                    execution.completed_at = now_with_tz()
                    await db.commit()
            except Exception:
                pass

# =============================================================================
# KUBERNETES MODE: Create K8s Job
# =============================================================================


async def _start_agent_k8s(execution_id: str, case_data: Optional[Dict[str, Any]] = None):
    """Kubernetes mode: create a K8s Job to run the Agent."""
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(Execution).where(Execution.id == UUID(execution_id))
            )
            execution = result.scalar_one_or_none()

            if not execution:
                logger.error(f'[K8s] Execution not found: {execution_id}')
                return

            # Fetch environment and test cases
            environment, test_cases, error = await _fetch_execution_data(db, execution)
            if error:
                logger.error(f'[K8s] 获取执行数据失败: execution_id={execution_id}, error={error}')
                execution.status = 'failed'
                execution.error_message = error
                execution.completed_at = now_with_tz()
                await db.commit()
                return

            # Debug mode: cases from the frontend use frontend data; the rest (e.g. snapshot) use DB data
            if case_data:
                frontend_cases = _build_cases_from_request(
                    case_data, business_id=execution.business_id
                )
                case_map = {str(tc.id): tc for tc in test_cases}
                case_map.update({str(tc.id): tc for tc in frontend_cases})
                test_cases = [case_map[cid] for cid in execution.test_case_ids if cid in case_map]

            if not test_cases:
                execution.status = 'failed'
                execution.error_message = '没有可执行的测试用例'
                execution.completed_at = now_with_tz()
                await db.commit()
                return

            # Update status
            execution.status = 'running'
            execution.started_at = now_with_tz()
            await db.commit()

            # Create K8s Job
            try:
                job_name = await _create_k8s_job(
                    execution_id=execution_id,
                    environment=environment,
                    test_cases=test_cases,
                    model=execution.model,
                    workers=execution.workers,
                    business_id=execution.business_id,
                )

                logger.info(f'[K8s] Job 创建成功: {job_name}')

            except Exception as e:
                logger.exception(f'[K8s] 创建 Job 失败: {e}')
                execution.status = 'failed'
                execution.error_message = f'创建 K8s Job 失败: {e}'
                execution.completed_at = now_with_tz()
                await db.commit()

        except Exception as e:
            logger.exception(f'[K8s] 启动失败: {e}')


async def _create_k8s_job(
    execution_id: str,
    environment: Environment,
    test_cases: List[TestCase],
    model: str,
    workers: int,
    business_id: Optional[UUID] = None,
) -> str:
    """Create a Kubernetes Job to run webqa-agent."""
    try:
        from kubernetes import client
        from kubernetes import config as k8s_config
    except ImportError:
        raise RuntimeError('kubernetes 库未安装，请运行: pip install kubernetes')

    # Load K8s configuration
    k8s_config_path = os.getenv('K8S_CONFIG_PATH')
    if k8s_config_path:
        k8s_config.load_kube_config(config_file=k8s_config_path)
    else:
        k8s_config.load_incluster_config()

    batch_v1 = client.BatchV1Api()

    # Read K8s settings from environment (defaults suit standard deployment)
    k8s_namespace = os.getenv('K8S_NAMESPACE', 'webqa')
    k8s_job_image = os.getenv('K8S_JOB_IMAGE', 'webqa-agent:latest')
    k8s_pvc_name = os.getenv('K8S_PVC_NAME', 'webqa-pvc')
    k8s_sa_name = os.getenv('K8S_JOB_SERVICE_ACCOUNT', 'webqa-agent-sa')

    cpu_limit, memory_gi = _compute_k8s_resources(workers, business_id)

    # Fetch auth cookies
    cookies = None
    if environment.auth_type == 'sso' and environment.sso_username:
        sso_env = getattr(environment, 'sso_env', 'prod') or 'prod'
        _, cookies = generate_sso_cookies(environment.sso_username, environment.sso_password, sso_env)
    elif environment.auth_type == 'cookies' and environment.cookies:
        cookies = environment.cookies

    # Build configs grouped by login_required
    configs = _build_agent_configs(environment, test_cases, workers, cookies)

    if not configs:
        raise ValueError('没有可执行的测试用例')

    # Add LLM configuration
    api_key = settings.get_api_key_for_model(model)
    base_url = settings.get_base_url_for_model(model)
    for config in configs:
        config['llm_config'] = {
            'api': settings.LLM_API,
            'api_key': api_key,
            'base_url': base_url,
            'model': model,
        }

    config_to_write = configs[0] if len(configs) == 1 else configs
    config_yaml = yaml.dump(config_to_write, allow_unicode=True)

    job_name = f'webqa-exec-{execution_id[:8]}'
    report_dir = f'/shared/reports/exec_{execution_id}'

    job = client.V1Job(
        api_version='batch/v1',
        kind='Job',
        metadata=client.V1ObjectMeta(
            name=job_name,
            namespace=k8s_namespace,
            labels={
                'app': 'webqa-agent',
                'execution-id': execution_id,
            },
        ),
        spec=client.V1JobSpec(
            ttl_seconds_after_finished=7200,
            active_deadline_seconds=settings.JOB_TIMEOUT_SECONDS,
            backoff_limit=0,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(
                    labels={'app': 'webqa-agent'},
                ),
                spec=client.V1PodSpec(
                    restart_policy='Never',
                    service_account_name=k8s_sa_name or None,
                    image_pull_secrets=[
                        client.V1LocalObjectReference(name='regcred-vpc')
                    ],
                    containers=[
                        client.V1Container(
                            name='webqa-agent',
                            image=k8s_job_image,
                            command=['python', '-m', 'backend.run_webqa'],
                            args=[
                                '-c', '/shared/reports/exec_' + execution_id + '/config.yaml',  # Generated config file path
                                '--execution-id', execution_id,
                                '--workers', str(workers),
                                '--report-dir', report_dir,
                                '--stdout',  # Disable file logging, push logs to Backend API
                            ],
                            env=[
                                client.V1EnvVar(name='EXECUTION_ID', value=execution_id),
                                client.V1EnvVar(name='CONFIG_YAML', value=config_yaml),
                                client.V1EnvVar(name='SHARED_STORAGE_PATH', value='/shared'),
                                client.V1EnvVar(name='BACKEND_CALLBACK_URL', value=settings.BACKEND_CALLBACK_URL),
                                client.V1EnvVar(name='OPENAI_API_KEY', value=api_key),
                                client.V1EnvVar(name='OPENAI_BASE_URL', value=base_url),
                                client.V1EnvVar(name='WEBQA_CASE_TIMEOUT', value=str(settings.WEBQA_CASE_TIMEOUT)),
                            ],
                            resources=client.V1ResourceRequirements(
                                requests={'cpu': '0.5', 'memory': f'{memory_gi}Gi'},
                                limits={'cpu': str(cpu_limit), 'memory': f'{memory_gi}Gi'},
                            ),
                            volume_mounts=[
                                client.V1VolumeMount(
                                    name='shared-storage',
                                    mount_path='/shared',
                                ),
                            ],
                        ),
                    ],
                    volumes=[
                        client.V1Volume(
                            name='shared-storage',
                            persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                                claim_name=k8s_pvc_name,
                            ),
                        ),
                    ],
                ),
            ),
        ),
    )

    batch_v1.create_namespaced_job(namespace=k8s_namespace, body=job)

    return job_name


# =============================================================================
# DOCKER MODE: Create standalone agent container
# =============================================================================

def _create_docker_container(
    execution_id: str,
    command: list,
    env_vars: dict,
    cpu_limit: int,
    memory_gi: int,
    container_name: str,
) -> str:
    """Create and start a Docker container for agent execution.

    Blocking call — must be wrapped in asyncio.to_thread(). Returns container
    ID.
    """
    try:
        import docker
    except ImportError:
        raise RuntimeError('docker package not installed: pip install docker')

    client = docker.from_env()

    container = client.containers.run(
        image=settings.DOCKER_AGENT_IMAGE,
        command=command,
        environment=env_vars,
        volumes={settings.DOCKER_SHARED_VOLUME: {'bind': '/shared', 'mode': 'rw'}},
        network=settings.DOCKER_NETWORK,
        detach=True,
        name=container_name,
        mem_limit=f'{memory_gi}g',
        nano_cpus=cpu_limit * 1_000_000_000,
        labels={
            'app': 'webqa-agent',
            'execution-id': execution_id,
            'managed-by': 'webqa-backend',
        },
    )
    return container.id


async def _monitor_docker_container(container_id: str, execution_id: str) -> None:
    """Monitor a Docker container until completion or timeout.

    Handles: normal exit, error exit, timeout, container removal.
    """
    try:
        import docker
    except ImportError:
        logger.error('[Docker] docker package not available for monitoring')
        return

    client = docker.from_env()
    timeout = settings.JOB_TIMEOUT_SECONDS
    start_time = asyncio.get_event_loop().time()

    try:
        while True:
            await asyncio.sleep(5)

            try:
                container = await asyncio.to_thread(client.containers.get, container_id)
                container_status = container.status
            except docker.errors.NotFound:
                logger.info(f'[Docker] Container already removed: {container_id[:12]}')
                _active_containers.pop(execution_id, None)
                return

            if container_status in ('exited', 'dead'):
                exit_code = container.attrs['State']['ExitCode']
                logger.info(f'[Docker] Container finished: {container_id[:12]}, exit_code={exit_code}')
                _active_containers.pop(execution_id, None)

                if exit_code != 0:
                    await asyncio.sleep(2)
                    async with AsyncSessionLocal() as db:
                        result = await db.execute(
                            select(Execution).where(Execution.id == UUID(execution_id))
                        )
                        exec_record = result.scalar_one_or_none()
                        if exec_record and exec_record.status == 'running':
                            exec_record.status = 'failed'
                            exec_record.error_message = f'Agent 容器异常退出 (exit_code={exit_code})'
                            exec_record.completed_at = now_with_tz()
                            await db.commit()

                try:
                    await asyncio.to_thread(container.remove, force=True)
                except Exception:
                    pass
                return

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                logger.warning(f'[Docker] Container timeout ({timeout}s): {container_id[:12]}')
                _active_containers.pop(execution_id, None)

                try:
                    await asyncio.to_thread(container.stop, timeout=10)
                    await asyncio.to_thread(container.remove, force=True)
                except Exception:
                    pass

                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(Execution).where(Execution.id == UUID(execution_id))
                    )
                    exec_record = result.scalar_one_or_none()
                    if exec_record and exec_record.status == 'running':
                        exec_record.status = 'timeout'
                        exec_record.error_message = f'执行超时（超过 {timeout // 3600} 小时）'
                        exec_record.completed_at = now_with_tz()
                        await db.commit()
                return

    except Exception as e:
        logger.exception(f'[Docker] Monitor exception: {e}')
        _active_containers.pop(execution_id, None)


async def _stop_docker_container(execution_id: str) -> bool:
    """Stop a running Docker container."""
    container_id = _active_containers.get(execution_id)
    if not container_id:
        return False

    try:
        import docker
        client = docker.from_env()
        container = await asyncio.to_thread(client.containers.get, container_id)
        await asyncio.to_thread(container.stop, timeout=10)
        logger.info(f'[Docker] Container stopped: {container_id[:12]}')
        _active_containers.pop(execution_id, None)
        return True
    except Exception as e:
        logger.error(f'[Docker] Failed to stop container: {e}')
        _active_containers.pop(execution_id, None)
        return False


async def _start_agent_docker(execution_id: str, case_data: Optional[Dict[str, Any]] = None):
    """Docker mode: create a standalone agent container to run tests."""
    prep = await _prepare_run_config(execution_id, case_data)
    if not prep:
        return

    container_config_path = prep['config_path'].replace(
        settings.effective_shared_storage_path, '/shared'
    )
    container_report_dir = prep['config_dir'].replace(
        settings.effective_shared_storage_path, '/shared'
    )
    cpu_limit, memory_gi = _compute_k8s_resources(prep['workers'], prep['business_id'])

    try:
        container_id = await asyncio.to_thread(
            _create_docker_container,
            execution_id=execution_id,
            command=[
                'python', '-m', 'backend.run_webqa',
                '-c', container_config_path,
                '-w', str(prep['workers']),
                '--execution-id', execution_id,
                '--report-dir', container_report_dir,
                '--stdout',
            ],
            env_vars={
                'EXECUTION_ID': execution_id,
                'SHARED_STORAGE_PATH': '/shared',
                'BACKEND_CALLBACK_URL': settings.BACKEND_CALLBACK_URL,
                'OPENAI_API_KEY': prep['api_key'],
                'OPENAI_BASE_URL': prep['base_url'],
                'WEBQA_CASE_TIMEOUT': str(settings.WEBQA_CASE_TIMEOUT),
            },
            cpu_limit=cpu_limit,
            memory_gi=memory_gi,
            container_name=f'webqa-agent-{execution_id[:8]}',
        )

        logger.info(f'[Docker] Agent container created: {container_id[:12]}')
        _active_containers[execution_id] = container_id
        asyncio.create_task(_monitor_docker_container(container_id, execution_id))

    except Exception as e:
        logger.exception(f'[Docker] Failed to create agent container: {e}')
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Execution).where(Execution.id == UUID(execution_id))
            )
            execution = result.scalar_one_or_none()
            if execution and execution.status == 'running':
                execution.status = 'failed'
                execution.error_message = f'创建 Docker 容器失败: {e}'
                execution.completed_at = now_with_tz()
                await db.commit()


async def _start_gen_docker(execution_id: str, gen_config_dict: Optional[Dict[str, Any]] = None):
    """Gen Mode (docker): Create a Docker container running gen_webqa.py."""
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(Execution).where(Execution.id == UUID(execution_id))
            )
            execution = result.scalar_one_or_none()
            if not execution:
                logger.error(f'[Gen Docker] Execution not found: {execution_id}')
                return

            if not gen_config_dict and execution.config:
                gen_config_dict = execution.config

            if not gen_config_dict:
                execution.status = 'failed'
                execution.error_message = 'Gen configuration missing'
                execution.completed_at = now_with_tz()
                await db.commit()
                return

            llm_cfg = gen_config_dict.setdefault('llm_config', {})
            model_name = llm_cfg.get('model', '')
            if not llm_cfg.get('api_key'):
                llm_cfg['api_key'] = settings.get_api_key_for_model(model_name)
            if not llm_cfg.get('base_url'):
                llm_cfg['base_url'] = settings.get_base_url_for_model(model_name)
            if not llm_cfg.get('max_tokens'):
                llm_cfg['max_tokens'] = 8192

            api_key = llm_cfg.get('api_key', '')
            base_url = llm_cfg.get('base_url', '')

            config_dir = Path(settings.shared_reports_path) / f'exec_{execution_id}'
            config_dir.mkdir(parents=True, exist_ok=True)
            config_file = config_dir / 'config.yaml'

            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(gen_config_dict, f, indent=2, ensure_ascii=False)

            container_config_path = str(config_file).replace(
                settings.effective_shared_storage_path, '/shared'
            )
            container_report_dir = str(config_dir).replace(
                settings.effective_shared_storage_path, '/shared'
            )

            execution.status = 'running'
            execution.started_at = now_with_tz()
            await db.commit()

            logger.info(f'[Gen Docker] Creating container: {execution_id}')
            cpu_limit, memory_gi = _compute_k8s_resources(
                execution.workers or 1, execution.business_id
            )

            container_id = await asyncio.to_thread(
                _create_docker_container,
                execution_id=execution_id,
                command=[
                    'python', '-m', 'backend.gen_webqa',
                    '-c', container_config_path,
                    '--execution-id', execution_id,
                    '--report-dir', container_report_dir,
                    '--stdout',
                ],
                env_vars={
                    'EXECUTION_ID': execution_id,
                    'SHARED_STORAGE_PATH': '/shared',
                    'BACKEND_CALLBACK_URL': settings.BACKEND_CALLBACK_URL,
                    'OPENAI_API_KEY': api_key,
                    'OPENAI_BASE_URL': base_url,
                },
                cpu_limit=cpu_limit,
                memory_gi=memory_gi,
                container_name=f'webqa-gen-{execution_id[:8]}',
            )

            logger.info(f'[Gen Docker] Container created: {container_id[:12]}')
            _active_containers[execution_id] = container_id
            asyncio.create_task(_monitor_docker_container(container_id, execution_id))

        except Exception as e:
            logger.exception(f'[Gen Docker] Start failed: {e}')
            try:
                execution.status = 'failed'
                execution.error_message = f'Failed to start Docker container: {e}'
                execution.completed_at = now_with_tz()
                await db.commit()
            except Exception:
                pass


# =============================================================================
# Shared helper functions
# =============================================================================

async def _fetch_execution_data(
    db, execution: Execution
) -> Tuple[Optional[Environment], Optional[List[TestCase]], Optional[str]]:
    """Fetch environment and test case data required for execution."""
    env_result = await db.execute(
        select(Environment).where(Environment.id == execution.environment_id)
    )
    environment = env_result.scalar_one_or_none()

    if not environment:
        return None, None, 'Environment does not exist'

    test_cases = []
    for case_id in execution.test_case_ids:
        case_result = await db.execute(
            select(TestCase).where(TestCase.id == UUID(case_id))
        )
        case = case_result.scalar_one_or_none()
        if case:
            test_cases.append(case)

    # Don't error on empty test_cases here — draft cases from case_overrides
    # will be added later by _apply_case_overrides in the caller
    return environment, test_cases, None


def _build_case_dict(case: TestCase) -> Dict[str, Any]:
    """Build the configuration dict for a single case."""
    case_dict = {
        'name': case.name,
        'case_id': str(case.id),
        'steps': [],
    }

    for step in case.steps:
        step_dict = {}
        if step.get('step_type') == 'action':
            step_dict['action'] = step.get('description', '')
        elif step.get('step_type') == 'verify':
            step_dict['verify'] = step.get('assertion', '')

        # Handle args, especially file paths
        args = (step.get('args') or {}).copy()
        if args.get('file_path'):
            file_path = args['file_path']
            base_path = f'{settings.effective_shared_storage_path}/files/{case.business_id}'

            # Support single file (string) or multiple files (array)
            if isinstance(file_path, list):
                # Multiple files: convert each path
                full_paths = [f'{base_path}/{fn}' for fn in file_path]
                args['file_path'] = full_paths
                logger.info(f'[Config] Step file_path 转换: {file_path} -> {full_paths}')
            else:
                # Single file
                full_path = f'{base_path}/{file_path}'
                args['file_path'] = full_path
                logger.info(f'[Config] Step file_path 转换: {file_path} -> {full_path}')

        if args:
            step_dict['args'] = args

        case_dict['steps'].append(step_dict)

    if case.snapshot:
        case_dict['snapshot'] = case.snapshot
    if case.use_snapshot:
        case_dict['use_snapshot'] = case.use_snapshot

    return case_dict


def _build_agent_configs(
    environment: Environment,
    test_cases: List[TestCase],
    workers: int,
    cookies: Optional[List[Dict]] = None,
) -> List[Dict[str, Any]]:
    """Build webqa-agent config list grouped by login_required.

    - Cases that require login → include cookies
    - Cases that do not require login → no cookies

    Returns:
        List of one or two configs.
    """
    # Group by login requirement
    login_cases = [c for c in test_cases if c.login_required]
    no_login_cases = [c for c in test_cases if not c.login_required]

    logger.info(f'[Config] Cases 分组: 需要登录={len(login_cases)}, 不需要登录={len(no_login_cases)}')

    configs = []

    # Fix escaping in ignore_rules (JSON may turn \ into \\)
    def _fix_ignore_rules_escaping(rules: dict) -> dict:
        if not rules:
            return rules
        fixed = {}
        for key in ['network', 'console']:
            if key in rules and isinstance(rules[key], list):
                fixed[key] = []
                for rule in rules[key]:
                    fixed_rule = dict(rule)
                    if 'pattern' in fixed_rule and isinstance(fixed_rule['pattern'], str):
                        # Restore double backslashes to single backslashes
                        fixed_rule['pattern'] = fixed_rule['pattern'].replace('\\\\', '\\')
                    fixed[key].append(fixed_rule)
            elif key in rules:
                fixed[key] = rules[key]
        return fixed

    fixed_ignore_rules = _fix_ignore_rules_escaping(environment.ignore_rules) if environment.ignore_rules else None

    # Base browser configuration
    base_browser_config = environment.browser_config or {
        'viewport': {'width': 1500, 'height': 800},
        'headless': True,
        'language': 'zh-CN',
    }

    # Build config for login-required cases (with cookies)
    if login_cases:
        browser_config_with_auth = {**base_browser_config}
        if cookies:
            browser_config_with_auth['cookies'] = cookies
            logger.info('[Config] 需要登录的 cases 已添加 cookies')
        else:
            logger.warning(f'[Config] 有 {len(login_cases)} 个 case 需要登录，但环境未配置认证')

        config_with_auth = {
            'target': {
                'url': environment.url,
                'max_concurrent_tests': workers,
            },
            'browser_config': browser_config_with_auth,
            'cases': [_build_case_dict(c) for c in login_cases],
        }
        if fixed_ignore_rules:
            config_with_auth['ignore_rules'] = fixed_ignore_rules
            logger.info(f'[Config] ignore_rules 已添加到配置: {fixed_ignore_rules}')
        else:
            logger.info('[Config] 没有配置 ignore_rules')
        configs.append(config_with_auth)

    # Build config for cases that do not require login (no cookies)
    if no_login_cases:
        config_no_auth = {
            'target': {
                'url': environment.url,
                'max_concurrent_tests': workers,
            },
            'browser_config': {**base_browser_config},  # no cookies
            'cases': [_build_case_dict(c) for c in no_login_cases],
        }
        if fixed_ignore_rules:
            config_no_auth['ignore_rules'] = fixed_ignore_rules
        configs.append(config_no_auth)
        logger.info('[Config] 不需要登录的 cases 配置完成（无 cookies）')

    return configs
