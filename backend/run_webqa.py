#!/usr/bin/env python3
"""WebQA Agent 执行脚本.

功能：
1. 加载配置文件并执行 webqa-agent 测试
2. 执行完成后回调 Backend API 通知结果

使用方式：
  python -m backend.run_webqa -c config.yaml -w 2 --execution-id xxx
"""

import argparse
import asyncio
import json
import os
import random
import string
import sys
import threading
import time
from typing import Dict, Optional

import yaml

# 共享存储和回调配置（从环境变量读取）
SHARED_STORAGE_PATH = os.getenv('SHARED_STORAGE_PATH', '')
BACKEND_CALLBACK_URL = os.getenv('BACKEND_CALLBACK_URL', '')

# 导入 webqa-agent 的模块
try:
    from webqa_agent.config_models.base_config import (BrowserConfig,
                                                       LLMConfig, LogConfig,
                                                       ReportConfig)
    from webqa_agent.config_models.run_config import RunConfig
    from webqa_agent.executor.run_executor import RunExecutor
    from webqa_agent.utils import (check_playwright_browsers_async, load_yaml,
                                   load_yaml_files)
    WEBQA_AGENT_AVAILABLE = True
except ImportError as e:
    print(f'警告: 无法导入 webqa-agent 模块: {e}')


def load_yaml_file(yaml_path: str) -> Dict:
    """加载 YAML 文件."""
    with open(yaml_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def save_yaml_file(yaml_path: str, data: Dict):
    """保存 YAML 文件."""
    with open(yaml_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def validate_and_build_llm_config(cfg):
    """Validate and build LLM configuration (from webqa-agent CLI).

    支持两种格式：
    1. llm_config 在顶层
    2. llm_config 在 config 列表中
    """
    # 先检查顶层是否有 llm_config
    llm_cfg_raw = cfg.get('llm_config', {})

    # 如果顶层没有，检查 config 列表中是否有
    if not llm_cfg_raw and 'config' in cfg:
        for cfg_item in cfg['config']:
            if 'llm_config' in cfg_item:
                llm_cfg_raw = cfg_item['llm_config']
                break

    # Environment variables take priority
    api = llm_cfg_raw.get('api', 'openai')
    api_key = os.getenv('OPENAI_API_KEY') or llm_cfg_raw.get('api_key', '')
    base_url = os.getenv('OPENAI_BASE_URL') or llm_cfg_raw.get('base_url', '')
    model = llm_cfg_raw.get('model', 'gpt-4o-mini')
    filter_model = llm_cfg_raw.get('filter_model', model)
    temperature = llm_cfg_raw.get('temperature')
    top_p = llm_cfg_raw.get('top_p')
    max_tokens = llm_cfg_raw.get('max_tokens')
    reasoning = llm_cfg_raw.get('reasoning')
    text_cfg = llm_cfg_raw.get('text')

    # Validate required fields
    if not api_key or api_key == 'your_openai_api_key' or api_key == 'your_anthropic_api_key' or api_key == 'your_gemini_api_key':
        raise ValueError('❌ LLM API Key not configured!')

    if not base_url:
        print('⚠️  base_url not set, using OpenAI default')
        base_url = 'https://api.openai.com/v1'

    llm_config = {
        'api': api,
        'model': model,
        'filter_model': filter_model,
        'api_key': api_key,
        'base_url': base_url,
        'temperature': temperature,
    }

    if top_p is not None:
        llm_config['top_p'] = top_p
    if max_tokens is not None:
        llm_config['max_tokens'] = max_tokens
    if reasoning is not None:
        llm_config['reasoning'] = reasoning
    if text_cfg is not None:
        llm_config['text'] = text_cfg

    return llm_config


async def execute_webqa_agent(config_path: str, workers: int = 4, report_dir_override: str = None):
    """执行 webqa-agent 测试.

    Args:
        config_path: 配置文件路径（支持文件夹和单个文件）
        workers: 并行数
        report_dir_override: 报告目录（可选）

    Returns:
        (results, report_path, html_report_path, result_count): 执行结果
    """
    if not WEBQA_AGENT_AVAILABLE:
        raise Exception('webqa-agent 模块不可用')

    try:
        # 加载配置
        is_folder = os.path.isdir(config_path)
        if is_folder:
            # 文件夹：使用 load_yaml_files 加载所有 YAML 文件
            configs = load_yaml_files(config_path)
        else:
            # 单个文件：直接加载（可能是单个配置或配置列表）
            loaded = load_yaml(config_path)
            # 支持单个配置或配置列表
            if isinstance(loaded, list):
                # 配置列表，直接使用（Backend 生成的多配置格式）
                configs = loaded
            else:
                # 单个配置，包装为列表
                configs = [loaded]

        # 统计
        total_cases = sum(len(c.get('cases', [])) for c in configs)
        if not total_cases:
            raise ValueError('配置中没有定义用例')

        # 展示分组信息
        for i, cfg in enumerate(configs):
            cases = cfg.get('cases', [])
            has_cookies = 'cookies' in cfg.get('browser_config', {})
            print(f'[配置] 配置 {i+1}: {len(cases)} 个用例, {"带登录" if has_cookies else "免登录"}')
        print(f'[配置] 共 {len(configs)} 个配置，{total_cases} 个用例')

        # 注意：SSO 登录和分组已由 Backend 处理

        # 验证 LLM 配置
        llm_cfg_dict = validate_and_build_llm_config(configs[0])
        llm_config = LLMConfig(
            model=llm_cfg_dict['model'],
            api_key=llm_cfg_dict['api_key'],
            base_url=llm_cfg_dict.get('base_url'),
            temperature=llm_cfg_dict.get('temperature'),
            max_tokens=llm_cfg_dict.get('max_tokens'),
            reasoning=llm_cfg_dict.get('reasoning'),
            top_p=llm_cfg_dict.get('top_p'),
            text=llm_cfg_dict.get('text'),
            filter_model=llm_cfg_dict.get('filter_model'),
        )

        # 检查 Playwright
        if not await check_playwright_browsers_async():
            raise RuntimeError('Playwright 浏览器未安装')

        # 设置 workers (虽然 RunConfig 中设置了，但这里可能是为了兼容旧逻辑或者确保 config 中的 workers 设置)
        # 注意：RunExecutor 会使用 RunConfig 中的 workers

        # 报告配置
        report_config = ReportConfig(
            language=configs[0].get('report', {}).get('language', 'zh-CN'),
            save_screenshots=configs[0].get('report', {}).get('save_screenshots', True),
            report_dir=report_dir_override
        )

        # 浏览器配置
        browser_cfg_data = configs[0].get('browser_config', {})
        browser_config = BrowserConfig(
            browser_type=browser_cfg_data.get('browser_type', 'chromium'),
            headless=browser_cfg_data.get('headless', True),
            viewport=browser_cfg_data.get('viewport', {'width': 1280, 'height': 720}),
            language=browser_cfg_data.get('language', 'zh-CN'),
            cookies=browser_cfg_data.get('cookies')
        )

        # 日志配置（从环境变量读取 stdout 模式）
        stdout = os.getenv('WEBQA_STDOUT', 'false').lower() == 'true'
        log_config = LogConfig(
            level=configs[0].get('log', {}).get('level', 'info'),
            stdout=stdout
        )

        # 构建 RunConfig
        run_config = RunConfig(
            llm_config=llm_config,
            browser_config=browser_config,
            report_config=report_config,
            log_config=log_config,
            cases_path=config_path,
            workers=workers
        )

        # 执行测试
        executor = RunExecutor(run_config)
        results, report_path, html_report_path, result_count = await executor.execute()

        return results, report_path, html_report_path, result_count

    except Exception as e:
        print(f'[错误] 执行失败: {e}')
        import traceback
        traceback.print_exc()
        return None, None, None, None


def callback_backend(execution_id: str, status: str, result_count: Dict = None,
                     report_path: str = None, log_path: str = None, error_message: str = None):
    """执行完成后回调 Backend API.

    Args:
        execution_id: 执行 ID
        status: 执行状态 (passed, failed, warning, timeout)
        result_count: 结果统计
        report_path: 报告路径（共享存储中）
        log_path: 日志路径（共享存储中）
        error_message: 错误信息
    """
    if not BACKEND_CALLBACK_URL:
        print('[回调] BACKEND_CALLBACK_URL 未配置，跳过回调')
        return

    url = f'{BACKEND_CALLBACK_URL}/api/internal/executions/{execution_id}/complete'
    payload = {
        'status': status,
        'result_count': result_count,
        'report_path': report_path,
        'log_path': log_path,
        'error_message': error_message,
    }

    print(f'[回调] 开始回调 Backend: {url}')
    print(f'[回调] 数据: {json.dumps(payload, indent=2, ensure_ascii=False)}')

    try:
        import requests
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        print(f'[回调] 成功: {result}')
        if result.get('oss_report_url'):
            print(f"[回调] OSS 报告 URL: {result['oss_report_url']}")
    except Exception as e:
        print(f'[回调] 失败: {e}')
        # 失败时写入标记文件，供后续补救
        if report_path and os.path.exists(report_path):
            marker_file = os.path.join(report_path, '.callback_failed')
            try:
                with open(marker_file, 'w') as f:
                    f.write(json.dumps({
                        'execution_id': execution_id,
                        'status': status,
                        'result_count': result_count,
                        'error': str(e),
                    }))
                print(f'[回调] 已写入失败标记文件: {marker_file}')
            except Exception as write_err:
                print(f'[回调] 写入标记文件失败: {write_err}')


def send_start_notification(env: str, execution_id: str):
    """发送开始执行的飞书通知."""
    url = 'https://aicarrier.feishu.cn/base/workflow/webhook/event/DVUBaJT4Vwf0yVhbMi6celSanub'
    payload = {
        'TARGET_ENV': env,
        'EXECUTION_ID': execution_id
    }
    try:
        import requests
        res = requests.post(url, json=payload, timeout=10)
        print(f'[前置] 发送开始执行通知响应: {res.status_code}')
    except Exception as e:
        print(f'[前置] 发送开始执行通知失败: {e}')


class ProgressPusher:
    """后台线程，定期推送执行进度到 Backend API."""

    def __init__(self, callback_url: str, execution_id: str, interval: float = 1.0):
        self.callback_url = callback_url
        self.execution_id = execution_id
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._display = None

    def start(self):
        """启动进度推送线程."""
        from webqa_agent.utils.task_display_util import Display
        self._display = Display
        self._thread = threading.Thread(target=self._push_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止进度推送线程，并做最后一次推送."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        # Final push to ensure completed tasks are captured
        self._push_progress()

    def _push_loop(self):
        """推送循环."""
        while not self._stop_event.is_set():
            self._push_progress()
            time.sleep(self.interval)

    def _push_progress(self):
        """推送进度到 Backend."""
        if not self._display or not self._display.display:
            return

        try:
            progress = self._display.display.get_progress()
            url = f'{self.callback_url}/api/internal/executions/{self.execution_id}/progress'

            import requests
            requests.post(url, json=progress, timeout=2)
        except Exception:
            pass  # Silent failure


def main():
    parser = argparse.ArgumentParser(description='WebQA Agent 执行脚本')
    parser.add_argument('-c', '--config', required=True, help='YAML 配置文件路径')
    parser.add_argument('-w', '--workers', type=int, default=1, help='并行 worker 数量')
    parser.add_argument('--execution-id', help='执行 ID（可选，默认从环境变量或随机生成）')
    parser.add_argument('--report-dir', help='报告目录（可选，默认使用共享存储路径）')
    parser.add_argument('--stdout', action='store_true',
                        help='Disable file logging, push logs to Backend API instead')

    args = parser.parse_args()

    # 确定 execution_id: 优先级 CLI > 环境变量 > 随机生成
    execution_id = args.execution_id or os.getenv('EXECUTION_ID')
    if not execution_id:
        characters = string.ascii_letters + string.digits
        execution_id = ''.join(random.choices(characters, k=14))
        print(f'[执行] 随机生成 execution_id: {execution_id}')

    os.environ['EXECUTION_ID'] = execution_id

    config_path = os.path.abspath(args.config)
    
    # 检查是否需要从环境变量生成配置文件
    config_yaml_content = os.getenv('CONFIG_YAML')
    if config_yaml_content:
        # 确保配置目录存在
        config_dir = os.path.dirname(config_path)
        os.makedirs(config_dir, exist_ok=True)
        
        try:
            # 尝试解析 YAML 内容
            parsed_config = yaml.safe_load(config_yaml_content)
            
            # 如果是列表，说明有多个配置，需要拆分为多个文件
            if isinstance(parsed_config, list):
                print(f'[执行] 检测到多配置列表，正在拆分为多个文件...')
                
                # 写入多个子配置文件
                for i, cfg in enumerate(parsed_config):
                    sub_config_path = os.path.join(config_dir, f'config_{i}.yaml')
                    with open(sub_config_path, 'w', encoding='utf-8') as f:
                        yaml.dump(cfg, f, allow_unicode=True)
                    print(f'[执行] 已写入子配置: {sub_config_path}')
                
                # 更新 config_path 为目录，以便加载该目录下所有配置
                config_path = config_dir
                print(f'[执行] 配置路径已更新为目录: {config_path}')
            else:
                # 单个配置，照常写入
                with open(config_path, 'w', encoding='utf-8') as f:
                    f.write(config_yaml_content)
                print(f'[执行] 已从 CONFIG_YAML 环境变量生成配置文件: {config_path}')
                
        except Exception as e:
            print(f'[警告] 解析 CONFIG_YAML 失败，回退到直接写入: {e}')
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(config_yaml_content)
    
    if not os.path.exists(config_path):
        print(f'错误: 配置文件不存在: {config_path}')
        sys.exit(1)

    # 确定报告目录
    report_dir = args.report_dir
    if not report_dir and SHARED_STORAGE_PATH:
        report_dir = f'{SHARED_STORAGE_PATH}/reports/exec_{execution_id}'

    # ========== 初始化 Display（no-file-logs 模式用于进度推送） ==========
    progress_pusher: Optional[ProgressPusher] = None
    if args.stdout:
        # 设置环境变量，供 execute_webqa_agent 中的 LogConfig 读取
        os.environ['WEBQA_STDOUT'] = 'true'
        from webqa_agent.utils.task_display_util import Display
        Display.init(language='zh-CN', no_terminal_ui=True)
        print(f'[执行] stdout 模式启用，日志将推送到 Backend API')

        # 如果配置了 Backend URL，启动进度推送
        if BACKEND_CALLBACK_URL:
            progress_pusher = ProgressPusher(BACKEND_CALLBACK_URL, execution_id, interval=1.0)
            print(f'[执行] 进度推送已配置: {BACKEND_CALLBACK_URL}')

    try:
        # ========== 启动进度推送 ==========
        if progress_pusher:
            progress_pusher.start()

        # ========== 执行测试 ==========
        print(f'\n[执行] 开始运行 webqa-agent...')
        print(f'[执行] 配置: {config_path}')
        print(f'[执行] Workers: {args.workers}')
        print(f'[执行] 报告目录: {report_dir}')

        results, report_path, html_report_path, result_count = asyncio.run(
            execute_webqa_agent(config_path, args.workers, report_dir_override=report_dir)
        )

        if results is None:
            raise Exception('webqa-agent 执行失败')

        # ========== 停止进度推送（最后推送一次完整状态） ==========
        if progress_pusher:
            progress_pusher.stop()

        # ========== 输出结果 ==========
        final_report_path = report_path or report_dir
        print(f'\n[完成] 报告路径: {final_report_path}')
        if result_count:
            print(f'[完成] 测试结果: {result_count}')

        # ========== 回调 Backend ==========
        if BACKEND_CALLBACK_URL:
            # 执行层面状态：completed 表示 Agent 正常完成执行
            # Case 结果通过 result_count 展示（passed/failed/warning 数量）
            status = 'completed'

            # stdout 模式下不写日志文件，日志通过 API 推送
            callback_backend(
                execution_id=execution_id,
                status=status,
                result_count=result_count,
                report_path=final_report_path,
                log_path=None,  # stdout 模式下不写日志文件
                error_message=None,
            )

    except KeyboardInterrupt:
        print('\n[中断] 用户中断执行')
        if progress_pusher:
            progress_pusher.stop()
        if BACKEND_CALLBACK_URL:
            callback_backend(execution_id, 'failed', None, None, None, '用户中断执行')
        sys.exit(130)

    except Exception as e:
        print(f'\n[错误] {e}')
        import traceback
        traceback.print_exc()
        if progress_pusher:
            progress_pusher.stop()
        if BACKEND_CALLBACK_URL:
            callback_backend(execution_id, 'failed', None, None, None, str(e))
        sys.exit(1)


if __name__ == '__main__':
    main()
