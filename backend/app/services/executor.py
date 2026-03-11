"""
Execution service - 统一执行模式

所有模式都通过启动独立的 Agent 进程执行，Agent 完成后回调 Backend API。
- local: 启动子进程运行 run_webqa.py
- kubernetes: 创建 K8s Job 运行
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


# Store active processes for cancellation
_active_processes: Dict[str, asyncio.subprocess.Process] = {}


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

    # 2. K8s mode: delete the Job from cluster
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
        k8s_namespace = os.getenv('K8S_NAMESPACE', 'cloud-staging')

        # 查询 execution 的 trigger_type 确定 Job 名前缀
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

        # 删除 Job 及其 Pod（propagationPolicy=Background 会级联删除 Pod）
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
            return True  # Job 已经不在了，视为成功
        logger.error(f'[Executor] Failed to delete K8s Job: {e}')
        return False


def generate_sso_cookies(username: str, password: str, env: str = 'prod') -> Tuple[Optional[str], Optional[List[Dict]]]:
    """使用 SSO 账号生成 cookies。"""
    try:
        from app.utils.get_sso_token import get_sso_token_sync

        logger.info(f'[SSO] 生成 cookies: username={username}, env={env}')
        token, cookie_json = get_sso_token_sync(username, password, env)
        cookies = json.loads(cookie_json)
        logger.info('[SSO] Cookies 生成成功')
        return token, cookies
    except Exception:
        logger.exception(f'[SSO] Cookies 生成失败: username={username}, env={env}')
        raise


def _time_id_prefix(execution_id: str, started_at=None) -> str:
    """生成 OSS 路径用的「时间_id 的第一部分」：{YYYYMMDD_HHMMSS}_{exec_id 前 8 位}。"""
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
    """上传报告目录到 OSS。oss_key_dir 建议使用「时间_id 的第一部分」如 20250227_143022_abc12345。"""
    if not report_dir or not os.path.exists(report_dir):
        logger.warning(f'[OSS] 报告目录不存在: {report_dir}')
        return None

    try:
        from app.utils.oss_utils import upload_dir_to_oss

        # 兼容调用方仅传 execution_id 的情况，统一转换为时间前缀目录
        normalized_oss_key_dir = (
            oss_key_dir if oss_key_dir and '_' in oss_key_dir else _time_id_prefix(oss_key_dir)
        )
        oss_key_prefix = f'test/webqa_agent/reports/{normalized_oss_key_dir}'

        logger.info(f'[OSS] 开始上传: {report_dir} -> {oss_key_prefix}')
        uploaded_files = upload_dir_to_oss(report_dir, oss_key_prefix=oss_key_prefix)

        if not uploaded_files:
            return None

        # 查找主 HTML 报告
        html_files = [f for f in uploaded_files.keys() if f.endswith('.html')]
        if html_files:
            main_html = next(
                (f for f in html_files if 'test_report' in f or 'report' in f.lower()),
                html_files[0]
            )
            report_url = uploaded_files[main_html]
            logger.info(f'[OSS] 上传成功，报告 URL: {report_url}')
            return report_url

        return list(uploaded_files.values())[0]

    except Exception:
        logger.exception(f'[OSS] 上传失败: report_dir={report_dir}, oss_key_dir={oss_key_dir}')
        return None


async def run_execution(execution_id: str, case_data: Optional[Dict[str, Any]] = None, gen_config_dict: Optional[Dict[str, Any]] = None):
    """执行测试任务（入口函数）。

    根据 EXECUTION_MODE 配置选择启动方式：
    - local: 启动子进程
    - kubernetes: 创建 K8s Job

    所有模式统一通过回调 API 接收结果。

    Args:
        execution_id: 执行记录 ID
        case_data: Debug 模式下前端直传的 case 数据，不存 DB。
            格式: {case_id_str: {login_required: bool, name: str, steps: [...], ...}}
        gen_config_dict: Gen 模式的原始配置字典（不含 api_key，由 executor 注入）
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
        else:
            await _start_gen_executor(execution_id, gen_config_dict)
    elif mode == 'kubernetes':
        await _start_agent_k8s(execution_id, case_data=case_data)
    else:
        # local 模式（默认）
        await _start_agent_subprocess(execution_id, case_data=case_data)


async def _start_gen_executor(execution_id: str, gen_config_dict: Optional[Dict[str, Any]] = None):
    """Gen Mode (local): Start subprocess running run_gen_webqa.py.

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
                'python', '-m', 'backend.run_gen_webqa',
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
# GEN + KUBERNETES MODE: 创建 K8s Job 运行 run_gen_webqa
# =============================================================================

async def _start_gen_k8s(execution_id: str, gen_config_dict: Optional[Dict[str, Any]] = None):
    """Gen Mode (kubernetes): Create a K8s Job running run_gen_webqa.py.

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
) -> str:
    """Create a Kubernetes Job that runs run_gen_webqa.py inside the agent
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

    k8s_namespace = os.getenv('K8S_NAMESPACE', 'cloud-staging')
    k8s_job_image = os.getenv('K8S_JOB_IMAGE', 'eng-center-registry-vpc.cn-shanghai.cr.aliyuncs.com/qa/webqa-agent:latest')
    k8s_pvc_name = os.getenv('K8S_PVC_NAME', 'webqa-pvc')
    k8s_sa_name = os.getenv('K8S_JOB_SERVICE_ACCOUNT', 'webqa-agent-sa')
    k8s_cpu_request = os.getenv('K8S_JOB_CPU_REQUEST', '0.5')
    k8s_cpu_limit = os.getenv('K8S_JOB_CPU_LIMIT', '2')
    # 内存按并发数动态分配：每个 worker 2Gi
    memory_gi = max(1, workers) * settings.K8S_MEMORY_PER_WORKER_GI
    k8s_memory_request = f'{memory_gi}Gi'
    k8s_memory_limit = f'{memory_gi}Gi'
    # /dev/shm 按并发数扩容：每个 worker 512Mi，Chromium 渲染进程需要足够的共享内存
    dshm_size = f'{max(1, workers)}Gi'

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
                            command=['python', '-m', 'backend.run_gen_webqa'],
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
                                requests={'cpu': k8s_cpu_request, 'memory': k8s_memory_request},
                                limits={'cpu': k8s_cpu_limit, 'memory': k8s_memory_limit},
                            ),
                            volume_mounts=[
                                client.V1VolumeMount(name='shared-storage', mount_path='/shared'),
                                client.V1VolumeMount(name='dshm', mount_path='/dev/shm'),
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
                        client.V1Volume(
                            name='dshm',
                            empty_dir=client.V1EmptyDirVolumeSource(
                                medium='Memory',
                                size_limit=dshm_size,
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
# LOCAL MODE: 启动子进程
# =============================================================================

def _build_cases_from_request(
    case_data: Dict[str, Any],
    business_id: Optional[UUID] = None,
) -> list:
    """直接从前端传入的 case 数据构建 case 对象列表，不查 DB。"""
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


async def _start_agent_subprocess(execution_id: str, case_data: Optional[Dict[str, Any]] = None):
    """Local 模式：启动子进程运行 Agent。"""
    async with AsyncSessionLocal() as db:
        try:
            # 获取执行记录
            result = await db.execute(
                select(Execution).where(Execution.id == UUID(execution_id))
            )
            execution = result.scalar_one_or_none()

            if not execution:
                logger.error(f'[Local] Execution not found: {execution_id}')
                return

            # 获取环境和用例
            environment, test_cases, error = await _fetch_execution_data(db, execution)
            if error:
                logger.error(f'[Local] 获取执行数据失败: execution_id={execution_id}, error={error}')
                execution.status = 'failed'
                execution.error_message = error
                execution.completed_at = now_with_tz()
                await db.commit()
                return

            # Debug 模式：前端传入的 case 用前端数据，其余（如 snapshot 依赖）用 DB 数据
            if case_data:
                frontend_cases = _build_cases_from_request(
                    case_data, business_id=execution.business_id
                )
                # 合并：前端数据优先，DB 数据补充，按 test_case_ids 顺序排列
                case_map = {str(tc.id): tc for tc in test_cases}
                case_map.update({str(tc.id): tc for tc in frontend_cases})
                test_cases = [case_map[cid] for cid in execution.test_case_ids if cid in case_map]

            if not test_cases:
                execution.status = 'failed'
                execution.error_message = '没有可执行的测试用例'
                execution.completed_at = now_with_tz()
                await db.commit()
                return

            # 获取认证 cookies（如果环境配置了认证）
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
                    return
            elif environment.auth_type == 'cookies' and environment.cookies:
                cookies = environment.cookies

            # 按 login_required 分组构建配置
            # - 需要登录的 cases → 带 cookies
            # - 不需要登录的 cases → 不带 cookies
            configs = _build_agent_configs(
                environment, test_cases, execution.workers, cookies
            )

            if not configs:
                execution.status = 'failed'
                execution.error_message = '没有可执行的测试用例'
                execution.completed_at = now_with_tz()
                await db.commit()
                return

            # 添加 LLM 配置到每个 config
            api_key = settings.get_api_key_for_model(execution.model)
            base_url = settings.get_base_url_for_model(execution.model)
            for config in configs:
                config['llm_config'] = {
                    'api': settings.LLM_API,
                    'api_key': api_key,
                    'base_url': base_url,
                    'model': execution.model,
                }

            # 写入临时配置文件
            config_dir = Path(settings.shared_reports_path) / f'exec_{execution_id}'
            config_dir.mkdir(parents=True, exist_ok=True)

            # 如果有多个配置，写入到单独的文件中让 RunExecutor 加载整个文件夹
            # 如果只有一个配置，写入单个文件
            if len(configs) == 1:
                config_file = config_dir / 'config.yaml'
                with open(config_file, 'w', encoding='utf-8') as f:
                    yaml.dump(configs[0], f, allow_unicode=True)
                config_path = str(config_file)
            else:
                # 多个配置：写入到多个文件，让 RunExecutor 加载整个目录
                for idx, config in enumerate(configs):
                    config_file = config_dir / f'config_{idx}.yaml'
                    with open(config_file, 'w', encoding='utf-8') as f:
                        yaml.dump(config, f, allow_unicode=True)
                config_path = str(config_dir)

            # 更新状态
            execution.status = 'running'
            execution.started_at = now_with_tz()
            await db.commit()

            # 启动子进程
            logger.info(f'[Local] 启动子进程执行: {execution_id}')

            env = os.environ.copy()
            env['EXECUTION_ID'] = execution_id
            env['SHARED_STORAGE_PATH'] = settings.effective_shared_storage_path
            env['BACKEND_CALLBACK_URL'] = settings.BACKEND_CALLBACK_URL
            env['OPENAI_API_KEY'] = api_key
            env['OPENAI_BASE_URL'] = base_url
            env['WEBQA_CASE_TIMEOUT'] = str(settings.WEBQA_CASE_TIMEOUT)

            # 静默模式：输出直接打印到终端（方便 K8s Job 查看 kubectl logs）
            # 不写入日志文件，减少 I/O
            process = await asyncio.create_subprocess_exec(
                'python', '-m', 'backend.run_webqa',
                '-c', config_path,
                '-w', str(execution.workers),
                '--execution-id', execution_id,
                '--report-dir', str(config_dir),
                '--stdout',  # Disable file logging, push logs to Backend API
                cwd=str(PROJECT_ROOT),
                env=env,
                # stdout/stderr 不重定向，直接打印到终端
            )

            logger.info(f'[Local] 子进程已启动: PID={process.pid}')
            _active_processes[execution_id] = process

            # 启动后台任务：监控进程并处理超时/崩溃
            async def monitor_process():
                timeout_seconds = settings.JOB_TIMEOUT_SECONDS
                try:
                    # 等待进程完成或超时
                    await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
                    logger.info(f'[Local] 子进程结束: PID={process.pid}, exit_code={process.returncode}')

                    # Remove from active processes
                    _active_processes.pop(execution_id, None)

                    # 检查进程是否异常退出（非零退出码且未回调）
                    if process.returncode != 0:
                        logger.warning(f'[Local] 子进程异常退出: exit_code={process.returncode}')
                        # 延迟 2 秒，等待可能的回调完成
                        await asyncio.sleep(2)
                        # 检查状态是否仍为 running（说明回调失败）
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
                    # 超时：终止进程并更新状态
                    logger.warning(f'[Local] 子进程超时 ({timeout_seconds}s): PID={process.pid}')
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=10)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()

                    # 更新数据库状态为 timeout
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

            # 不等待进程完成，让它在后台运行
            # Agent 完成后会回调 /api/internal/executions/{id}/complete

        except Exception as e:
            logger.exception(f'[Local] 启动失败: {e}')
            # 更新状态为失败
            try:
                execution.status = 'failed'
                execution.error_message = f'启动子进程失败: {e}'
                execution.completed_at = now_with_tz()
                await db.commit()
            except:
                pass

# =============================================================================
# KUBERNETES MODE: 创建 K8s Job
# =============================================================================

async def _start_agent_k8s(execution_id: str, case_data: Optional[Dict[str, Any]] = None):
    """Kubernetes 模式：创建 K8s Job 运行 Agent。"""
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(Execution).where(Execution.id == UUID(execution_id))
            )
            execution = result.scalar_one_or_none()

            if not execution:
                logger.error(f'[K8s] Execution not found: {execution_id}')
                return

            # 获取环境和用例
            environment, test_cases, error = await _fetch_execution_data(db, execution)
            if error:
                logger.error(f'[K8s] 获取执行数据失败: execution_id={execution_id}, error={error}')
                execution.status = 'failed'
                execution.error_message = error
                execution.completed_at = now_with_tz()
                await db.commit()
                return

            # Debug 模式：前端传入的 case 用前端数据，其余（如 snapshot 依赖）用 DB 数据
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

            # 更新状态
            execution.status = 'running'
            execution.started_at = now_with_tz()
            await db.commit()

            # 创建 K8s Job
            try:
                job_name = await _create_k8s_job(
                    execution_id=execution_id,
                    environment=environment,
                    test_cases=test_cases,
                    model=execution.model,
                    workers=execution.workers,
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
) -> str:
    """创建 Kubernetes Job 来运行 webqa-agent。"""
    try:
        from kubernetes import client
        from kubernetes import config as k8s_config
    except ImportError:
        raise RuntimeError('kubernetes 库未安装，请运行: pip install kubernetes')

    # 加载 K8s 配置
    k8s_config_path = os.getenv('K8S_CONFIG_PATH')
    if k8s_config_path:
        k8s_config.load_kube_config(config_file=k8s_config_path)
    else:
        k8s_config.load_incluster_config()

    batch_v1 = client.BatchV1Api()

    # 从环境变量获取 K8s 配置 (默认值适用于标准部署)
    k8s_namespace = os.getenv('K8S_NAMESPACE', 'cloud-staging')
    k8s_job_image = os.getenv('K8S_JOB_IMAGE', 'eng-center-registry-vpc.cn-shanghai.cr.aliyuncs.com/qa/webqa-agent:latest')
    k8s_pvc_name = os.getenv('K8S_PVC_NAME', 'webqa-pvc')
    k8s_sa_name = os.getenv('K8S_JOB_SERVICE_ACCOUNT', 'webqa-agent-sa')

    # K8s Job 资源配置：内存按并发数动态分配，每个 worker 2Gi
    k8s_cpu_request = os.getenv('K8S_JOB_CPU_REQUEST', '0.5')
    k8s_cpu_limit = os.getenv('K8S_JOB_CPU_LIMIT', '2')
    memory_gi = max(1, workers) * settings.K8S_MEMORY_PER_WORKER_GI
    k8s_memory_request = f'{memory_gi}Gi'
    k8s_memory_limit = f'{memory_gi}Gi'
    # /dev/shm 按并发数扩容：每个 worker 512Mi，Chromium 渲染进程需要足够的共享内存
    dshm_size = f'{max(1, workers)}Gi'

    # 获取认证 cookies
    cookies = None
    if environment.auth_type == 'sso' and environment.sso_username:
        sso_env = getattr(environment, 'sso_env', 'prod') or 'prod'
        _, cookies = generate_sso_cookies(environment.sso_username, environment.sso_password, sso_env)
    elif environment.auth_type == 'cookies' and environment.cookies:
        cookies = environment.cookies

    # 按 login_required 分组构建配置
    configs = _build_agent_configs(environment, test_cases, workers, cookies)

    if not configs:
        raise ValueError('没有可执行的测试用例')

    # 添加 LLM 配置
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
                                '-c', '/shared/reports/exec_' + execution_id + '/config.yaml',  # 使用生成的配置文件路径
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
                                requests={'cpu': k8s_cpu_request, 'memory': k8s_memory_request},
                                limits={'cpu': k8s_cpu_limit, 'memory': k8s_memory_limit},
                            ),
                            volume_mounts=[
                                client.V1VolumeMount(
                                    name='shared-storage',
                                    mount_path='/shared',
                                ),
                                # Chromium uses /dev/shm for shared memory; the K8s
                                # default of 64 MB causes renderer crashes / hangs.
                                client.V1VolumeMount(
                                    name='dshm',
                                    mount_path='/dev/shm',
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

                        client.V1Volume(
                            name='dshm',
                            empty_dir=client.V1EmptyDirVolumeSource(
                                medium='Memory',
                                size_limit=dshm_size,
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
# 公共辅助函数
# =============================================================================

async def _fetch_execution_data(
    db, execution: Execution
) -> Tuple[Optional[Environment], Optional[List[TestCase]], Optional[str]]:
    """获取执行所需的环境和测试用例数据。"""
    env_result = await db.execute(
        select(Environment).where(Environment.id == execution.environment_id)
    )
    environment = env_result.scalar_one_or_none()

    if not environment:
        return None, None, '环境不存在'

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
    """构建单个 case 的配置字典。"""
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

        # 处理参数，特别是文件路径
        args = (step.get('args') or {}).copy()
        if args.get('file_path'):
            file_path = args['file_path']
            base_path = f'{settings.effective_shared_storage_path}/files/{case.business_id}'

            # 支持单个文件(字符串)或多个文件(数组)
            if isinstance(file_path, list):
                # 多个文件：转换每个路径
                full_paths = [f'{base_path}/{fn}' for fn in file_path]
                args['file_path'] = full_paths
                logger.info(f'[Config] Step file_path 转换: {file_path} -> {full_paths}')
            else:
                # 单个文件
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
    """按 login_required 分组构建 webqa-agent 配置列表。

    - 需要登录的 cases → 带 cookies
    - 不需要登录的 cases → 不带 cookies

    Returns:
        配置列表，可能包含 1-2 个配置
    """
    # 分组
    login_cases = [c for c in test_cases if c.login_required]
    no_login_cases = [c for c in test_cases if not c.login_required]

    logger.info(f'[Config] Cases 分组: 需要登录={len(login_cases)}, 不需要登录={len(no_login_cases)}')

    configs = []

    # 处理 ignore_rules 中的转义问题
    # JSON 传输时 \ 会被转义为 \\，需要还原
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
                        # 将双反斜杠还原为单反斜杠
                        fixed_rule['pattern'] = fixed_rule['pattern'].replace('\\\\', '\\')
                    fixed[key].append(fixed_rule)
            elif key in rules:
                fixed[key] = rules[key]
        return fixed

    # 修复 ignore_rules 的转义问题
    fixed_ignore_rules = _fix_ignore_rules_escaping(environment.ignore_rules) if environment.ignore_rules else None

    # 基础浏览器配置
    base_browser_config = environment.browser_config or {
        'viewport': {'width': 1500, 'height': 800},
        'headless': True,
        'language': 'zh-CN',
    }

    # 构建需要登录的配置（带 cookies）
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

    # 构建不需要登录的配置（不带 cookies）
    if no_login_cases:
        config_no_auth = {
            'target': {
                'url': environment.url,
                'max_concurrent_tests': workers,
            },
            'browser_config': {**base_browser_config},  # 不带 cookies
            'cases': [_build_case_dict(c) for c in no_login_cases],
        }
        if fixed_ignore_rules:
            config_no_auth['ignore_rules'] = fixed_ignore_rules
        configs.append(config_no_auth)
        logger.info('[Config] 不需要登录的 cases 配置完成（无 cookies）')

    return configs
