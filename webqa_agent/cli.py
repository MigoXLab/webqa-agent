#!/usr/bin/env python3
"""WebQA Agent CLI - Command line interface for web quality assurance testing."""

import argparse
import asyncio
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from webqa_agent.config_models.base_config import (BrowserConfig, LLMConfig,
                                                   LogConfig, ReportConfig)
from webqa_agent.config_models.gen_config import (CustomToolsConfig,
                                                  DynamicStepConfig, GenConfig)
from webqa_agent.executor.gen_executor import GenExecutor
from webqa_agent.utils import (check_lighthouse_installation,
                               check_nuclei_installation,
                               check_playwright_browsers_async,
                               find_config_file, load_accounts, load_cookies,
                               load_yaml, load_yaml_files, resolve_config_dir)


def get_version() -> str:
    """Get the package version."""
    from webqa_agent import __version__
    return __version__


def get_template_content(mode: str) -> str | None:
    """Get configuration template content from example files.

    Args:
        mode: 'gen' or 'run'

    Returns:
        Template content as string, or None if not found
    """
    if mode == 'gen':
        template_filename = 'config.yaml.example'
    elif mode == 'run':
        template_filename = 'config_run.yaml.example'
    else:
        raise ValueError(f'Invalid mode: {mode}')

    package_dir = Path(__file__).parent  # webqa_agent package directory
    project_root = package_dir.parent

    template_paths = [
        # 1. Inside the pip package (webqa_agent/templates/)
        package_dir / 'templates' / template_filename,
        # 2. Project root config/ (development mode)
        project_root / 'config' / template_filename,
        # 3. Current working directory config/
        Path('config') / template_filename,
    ]

    for template_path in template_paths:
        if template_path.exists():
            try:
                with open(template_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception:
                continue

    return None


# ============================================================================
# LLM Configuration
# ============================================================================

def validate_and_build_llm_config(cfg):
    """Validate and build LLM configuration."""
    llm_cfg_raw = cfg.get('llm_config', {})

    # Environment variables take priority
    api = llm_cfg_raw.get('api', 'openai')
    api_key = os.getenv('OPENAI_API_KEY') or llm_cfg_raw.get('api_key', '')
    base_url = os.getenv('OPENAI_BASE_URL') or llm_cfg_raw.get('base_url', '')
    model = llm_cfg_raw.get('model', 'gpt-4o-mini')
    filter_model = llm_cfg_raw.get('filter_model', model)
    temperature = llm_cfg_raw.get('temperature')  # No default - let provider handle it
    top_p = llm_cfg_raw.get('top_p')
    max_tokens = llm_cfg_raw.get('max_tokens')
    reasoning = llm_cfg_raw.get('reasoning')
    text_cfg = llm_cfg_raw.get('text')
    timeout = llm_cfg_raw.get('timeout')

    # Validate required fields
    placeholder_keys = {'your_openai_api_key', 'your_anthropic_api_key', 'your_gemini_api_key'}
    if not api_key or api_key in placeholder_keys:
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
    if timeout is not None:
        llm_config['timeout'] = timeout

    # Display configuration (masked)
    api_key_masked = f'{api_key[:8]}...{api_key[-4:]}' if len(api_key) > 12 else '***'
    print('✅ LLM configuration validated:')
    print(f'   Model: {model}')
    if filter_model != model:
        print(f'   Filter Model: {filter_model}')
    print(f'   API Key: {api_key_masked}')
    print(f'   Base URL: {base_url}')

    return llm_config


def _load_cc_mini_runner():
    """Load ``run_cc_mini`` (the Flash engine entrypoint) on demand."""
    from webqa_agent.utils.flash_utils import load_flash_runner
    return load_flash_runner(module_name='webqa_cc_mini_runner')


async def execute_cc_mini_mode(
    *,
    url: str,
    task: str,
    provider: str,
    model: str,
    api_key: str,
    base_url: str | None = None,
    effort: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    max_time_seconds: float | None = None,
    skills_dir: str | None = None,
    file_catalog: str | None = None,
    save_screenshots: bool = False,
    screenshot_dir: str | None = None,
    data_flow_sink=None,
    browser_headless: bool = False,
    browser_viewport: tuple[int, int] | None = None,
    log_level: str = 'info',
    on_event=None,
    worker_id: int = 0,
    extensions: Any = None,
    filter_model: str | None = None,
):
    """Execute one cc-mini run without blocking the main event loop.

    Initialises the shared logger so cc-mini's ``cc_mini.runner`` /
    ``cc_mini.mcp`` loggers inherit file + stream handlers. Without this
    call the cc-mini path bypasses ``GenExecutor`` (which normally wires
    logging) and every ``log.info`` in cc-mini is silently dropped by
    Python's ``lastResort`` handler.

    ``skills_dir`` is forwarded to ``run_cc_mini``. When provided, the
    cc-mini engine discovers skills under that directory and exposes
    them via Progressive Disclosure (see webqa-cc-mini/skills/README.md).

    ``worker_id`` is threaded through so concurrent CLI invocations get
    distinct Chromium profiles + CDP ports (each worker uses port
    ``9222 + worker_id``). Defaults to 0 for the single-case CLI flow.

    ``extensions`` accepts a ``features.cookies.Extensions`` instance (or
    duck-typed equivalent exposing ``as_kwargs()``). When set, its
    ``pre_engine_hook`` / ``extra_tools`` / ``extra_section`` are spread
    into ``run_cc_mini``. Use a single param so adding new feature bundles
    in the future doesn't require expanding this signature each time.
    """
    from webqa_agent.utils.get_log import GetLog
    GetLog.get_log(log_level=log_level)

    extension_kwargs: dict = {}
    if extensions is not None and hasattr(extensions, 'as_kwargs'):
        extension_kwargs = extensions.as_kwargs()

    run_cc_mini = _load_cc_mini_runner()
    return await asyncio.to_thread(
        run_cc_mini,
        url,
        task,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        effort=effort,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        timeout=timeout,
        max_time_seconds=max_time_seconds,
        skills_dir=skills_dir,
        file_catalog=file_catalog,
        save_screenshots=save_screenshots,
        screenshot_dir=screenshot_dir,
        data_flow_sink=data_flow_sink,
        browser_headless=browser_headless,
        browser_viewport=browser_viewport,
        worker_id=worker_id,
        on_event=on_event,
        filter_model=filter_model,
        **extension_kwargs,
    )


_execute_cc_mini_mode = execute_cc_mini_mode


def _resolve_cc_mini_report_dir(*, cfg: dict, run_timestamp: str | None) -> str:
    report_base_dir = (cfg.get('report') or {}).get('report_dir')
    timestamp = (
        run_timestamp
        or os.getenv('WEBQA_REPORT_TIMESTAMP')
        or os.getenv('WEBQA_TIMESTAMP')
        or datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
    )
    if report_base_dir and str(report_base_dir).strip():
        base_path = Path(report_base_dir)
        if base_path.name.startswith('test_'):
            return str(base_path)
        return str(base_path / f'test_{timestamp}')
    return f'reports/test_{timestamp}'


# ============================================================================
# Command: init
# ============================================================================

def cmd_init(args):
    """Initialize a new configuration file."""
    output_path = args.output or 'config.yaml'
    mode = args.mode or 'gen'
    if mode == 'gen':
        output_path = 'config.yaml'
    elif mode == 'run':
        output_path = 'config_run.yaml'
    # Validate mode
    if mode not in ['gen', 'run']:
        print(f'❌ Invalid mode: {mode}')
        print('   Valid modes: gen, run')
        sys.exit(1)

    # Check if file already exists
    if os.path.exists(output_path) and not args.force:
        print(f'❌ Config file already exists: {output_path}')
        print('   Use --force to overwrite, or specify a different path with --output')
        sys.exit(1)

    # Create directory if needed
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        print(f'📁 Created directory: {output_dir}')

    # Load template from example file
    template = get_template_content(mode)
    if template is None:
        print(f'❌ Template file not found for mode: {mode}', file=sys.stderr)
        print('   Searched locations:', file=sys.stderr)
        print('   - webqa_agent/templates/ (pip package)', file=sys.stderr)
        print('   - config/ (project root or cwd)', file=sys.stderr)
        sys.exit(1)

    # Write config file
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(template)

        mode_name = (
            'Gen Mode (Flash engine by default)' if mode == 'gen'
            else 'Run Mode (Standard engine)'
        )
        print(f'✅ Configuration file created: {output_path} ({mode_name})')
        print()
        print('📝 Next steps:')
        print(f'   1. Edit {output_path} to configure:')
        print('      - target.url: The website URL to test')
        print('      - llm_config.api: The LLM API provider (openai, anthropic, etc.)')
        print('      - llm_config.api_key: Your API key')
        print('      - llm_config.base_url: The base URL of the API')

        if mode == 'gen':
            print('      - test_config: Enable/disable test types')
        else:
            print('      - cases: Define your test cases and steps')

        print()
        print('   2. Run tests:')
        if mode == 'gen':
            print(f'      webqa-agent gen -c {output_path}')
        else:
            print(f'      webqa-agent run -c {output_path}')

    except Exception as e:
        print(f'❌ Failed to create config file: {e}', file=sys.stderr)
        sys.exit(1)


# ============================================================================
# Command: run & gen
# ============================================================================

async def run_tests(cfg, execution_mode, config_path: str = None, workers: int = None):
    """Execute the test suite.

    Args:
        cfg: Configuration dictionary
        execution_mode: Execution mode ('gen' or 'run')
        config_path: Path to config file/folder (required for run mode)
        workers: Number of parallel workers from CLI (None if not specified)
    """
    # Display runtime info
    is_docker = os.getenv('DOCKER_ENV') == 'true'
    print(f"🏃 Runtime: {'Docker container' if is_docker else 'Local environment'}")

    # Execute based on mode
    if execution_mode == 'run':
        await execute_run_mode(config_path, workers=workers)
    else:  # gen mode
        # Resolve workers: CLI > config > default (4)
        w = workers if workers is not None else cfg.get('target', {}).get('max_concurrent_tests', 4)
        try:
            workers = max(1, int(w))
        except (ValueError, TypeError):
            workers = 4
        print('🎯 Mode: Gen Mode (AI-driven test generation)')
        await execute_gen_mode(cfg, config_path=config_path, workers=workers)


async def execute_gen_mode(cfg, config_path: str | None = None, workers: int = 1):
    """Execute Gen mode tests using GenConfig and GenExecutor."""
    # Get config sections
    tconf = cfg.get('test_config', {})
    target_url = cfg.get('target', {}).get('url', '')

    if not target_url:
        print('❌ No target URL specified in configuration', file=sys.stderr)
        sys.exit(1)

    print(f'🎯 Target URL: {target_url}')

    planning_mode = tconf.get('planning_mode', 'explore')
    business_objectives = tconf.get('business_objectives', '')
    engine = str(cfg.get('engine', 'flash')).strip().lower()
    if engine not in {'flash', 'standard'}:
        print(f'❌ Invalid engine: "{engine}". Supported engines are: "flash", "standard"', file=sys.stderr)
        sys.exit(1)
    use_flash = (engine == 'flash')

    # Validate and build LLM config
    try:
        llm_config_dict = validate_and_build_llm_config(cfg)
        llm_config = LLMConfig(
            model=llm_config_dict['model'],
            api_key=llm_config_dict['api_key'],
            base_url=llm_config_dict.get('base_url'),
            filter_model=llm_config_dict.get('filter_model'),
            temperature=llm_config_dict.get('temperature'),
            top_p=llm_config_dict.get('top_p'),
            max_tokens=llm_config_dict.get('max_tokens'),
            reasoning=llm_config_dict.get('reasoning'),
            timeout=llm_config_dict.get('timeout'),
        )
    except ValueError as e:
        print(f'\n{e}', file=sys.stderr)
        sys.exit(1)

    if use_flash:
        # Normalize tasks: accept either a single string (legacy) or a list of
        # strings (new — concurrent batch). Whitespace-only entries are dropped
        # so a stray blank line in YAML doesn't waste a worker slot.
        if isinstance(business_objectives, str):
            tasks = [business_objectives.strip()] if business_objectives.strip() else []
        elif isinstance(business_objectives, list):
            tasks = [
                str(t).strip() for t in business_objectives
                if isinstance(t, (str,)) and str(t).strip()
            ]
        else:
            print(
                '❌ test_config.business_objectives must be a string or list of '
                f'strings, got {type(business_objectives).__name__}',
                file=sys.stderr,
            )
            sys.exit(1)
        if not tasks:
            print('❌ test_config.business_objectives is required when engine is flash', file=sys.stderr)
            sys.exit(1)

        run_timestamp = (
            os.getenv('WEBQA_REPORT_TIMESTAMP')
            or os.getenv('WEBQA_TIMESTAMP')
            or datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
        )
        resolved_report_dir = _resolve_cc_mini_report_dir(
            cfg=cfg, run_timestamp=run_timestamp,
        )
        report_cfg_raw = cfg.get('report', {})
        save_screenshots = bool(report_cfg_raw.get('save_screenshots', False))
        save_dataflow = bool(report_cfg_raw.get('save_dataflow', True))

        from webqa_agent.utils.data_flow_reporter import set_dataflow_enabled
        set_dataflow_enabled(save_dataflow)

        provider = llm_config.get_provider()
        if provider == 'gemini':
            print('ℹ️ cc-mini will use OpenAI-compatible mode for Gemini-style endpoints')
            provider = 'openai'
        elif provider not in {'anthropic', 'openai'}:
            print(f'❌ Unsupported provider for cc-mini: {provider}', file=sys.stderr)
            sys.exit(1)

        effort = llm_config.reasoning.get('effort') if llm_config.reasoning else None

        # Anthropic users without an explicit base_url must not inherit the
        # OpenAI default injected by validate_and_build_llm_config() — passing
        # https://api.openai.com/v1 to the Anthropic SDK breaks every request.
        cc_mini_base_url = llm_config.base_url
        if provider == 'anthropic' and cc_mini_base_url == 'https://api.openai.com/v1':
            cc_mini_base_url = None

        # Resolve concurrency: CLI arg already lives in `workers`; fall back to
        # config target.max_concurrent_tests (the same key non-cc-mini gen mode
        # reads). Single-task runs are forced serial regardless.
        max_concurrent_raw = (
            workers if workers is not None
            else cfg.get('target', {}).get('max_concurrent_tests', 1)
        )
        try:
            max_concurrent = max(1, int(max_concurrent_raw))
        except (ValueError, TypeError):
            max_concurrent = 1
        if len(tasks) == 1:
            max_concurrent = 1

        print('📋 Tests enabled: Gen Mode (Flash engine)')
        print(f'🌐 Flash URL: {target_url}')
        print(f'📝 Flash Tasks: {len(tasks)} (concurrency={max_concurrent})')
        for i, t in enumerate(tasks, start=1):
            print(f'   {i}. {t}')
        print(f'🤖 Flash LLM Provider: {provider}')
        print('-' * 60, flush=True)

        log_level = cfg.get('log', {}).get('level', 'info')

        browser_cfg_raw = cfg.get('browser_config', {})
        is_docker = os.getenv('DOCKER_ENV') == 'true'
        browser_headless = True if is_docker else bool(
            browser_cfg_raw.get('headless', True),
        )
        print(f'🌐 Flash browser headless: {browser_headless}', flush=True)
        _vp = browser_cfg_raw.get('viewport')
        browser_viewport: tuple[int, int] | None = (
            (int(_vp['width']), int(_vp['height'])) if isinstance(_vp, dict) else None
        )

        # Mirror GenExecutor: when the user configured a test-files directory
        # (+ optional filename whitelist) we build an LLM-readable catalog and
        # inject it into the cc-mini system prompt so the agent can autonomously
        # plan uploads with mcp__browser__upload_file.
        cc_mini_file_catalog: str | None = None
        cc_mini_test_files_dir = tconf.get('test_files_dir')
        if cc_mini_test_files_dir:
            try:
                from webqa_agent.utils.test_file_library import TestFileLibrary
                _whitelist = tconf.get('test_files')
                if _whitelist is not None and not isinstance(_whitelist, list):
                    print(f'⚠️ Ignoring malformed test_config.test_files (expected list, got {type(_whitelist).__name__})')
                    _whitelist = None
                _library = TestFileLibrary(cc_mini_test_files_dir, file_whitelist=_whitelist)
                if _library.files:
                    cc_mini_file_catalog = _library.get_catalog_for_llm() or None
                    print(f'📎 cc-mini test files: {len(_library.files)} from {cc_mini_test_files_dir}')
                else:
                    print(f'ℹ️ cc-mini test_files_dir={cc_mini_test_files_dir} has no eligible files; catalog skipped')
            except Exception as exc:
                print(f'⚠️ Failed to build cc-mini file catalog: {exc}')

        # Build cookie-injection extensions from the top-level `accounts:`
        # config (and the legacy `browser_config.cookies` fallback). This
        # is the only path that turns config-file accounts into cc-mini
        # cookie state — see CUSTOM_TOOL_DEVELOPMENT.md / cc-mini README.
        cc_mini_extensions: Any = None
        try:
            from webqa_agent.utils.flash_utils import \
                build_cookie_extensions_from_config
            cc_mini_extensions = build_cookie_extensions_from_config(
                cfg, source_file=cfg.get('_source_file'),
            )
            if cc_mini_extensions is not None:
                acc_count = len(cc_mini_extensions.extra_tools or [])
                if acc_count:
                    print(f'🔐 Flash accounts: {acc_count} switch_account tool(s) registered')
                else:
                    print('🔐 Flash cookies: startup-injection extension active')
        except ValueError as exc:
            # Friendly error wrapping for config mistakes — the underlying
            # validator messages are user-readable; surface them without
            # a stacktrace and exit cleanly.
            print(f'\n❌ cc-mini cookie configuration error: {exc}',
                  file=sys.stderr)
            sys.exit(1)
        except Exception as exc:
            # Unexpected — print the trace because this is a bug, not a
            # config issue.
            print(f'\n❌ Failed to build cc-mini cookie extensions: {exc}',
                  file=sys.stderr)
            traceback.print_exc()
            sys.exit(1)

        # Build the executor: shared kwargs go to every task; the executor
        # injects per-task task/worker_id/screenshot_dir/on_event/sink.
        from webqa_agent.executor import FlashExecutor
        executor = FlashExecutor(
            shared_kwargs=dict(
                url=target_url,
                provider=provider,
                model=llm_config.model,
                api_key=llm_config.api_key,
                base_url=cc_mini_base_url,
                effort=effort,
                temperature=llm_config.temperature,
                top_p=llm_config.top_p,
                max_tokens=llm_config.max_tokens,
                timeout=llm_config.timeout,
                skills_dir=tconf.get('cc_mini_skills_dir'),
                file_catalog=cc_mini_file_catalog,
                save_screenshots=save_screenshots,
                browser_headless=browser_headless,
                browser_viewport=browser_viewport,
                log_level=log_level,
                extensions=cc_mini_extensions,
                filter_model=llm_config.filter_model,
            ),
            max_concurrent=max_concurrent,
            report_dir=resolved_report_dir,
            url=target_url,
            language=(cfg.get('report') or {}).get('language', 'zh-CN'),
            save_screenshots=save_screenshots,
            save_dataflow=save_dataflow,
            invoke_runner=_execute_cc_mini_mode,
        )

        prev_report_ts = os.environ.get('WEBQA_REPORT_TIMESTAMP')
        os.environ['WEBQA_REPORT_TIMESTAMP'] = run_timestamp
        try:
            batch = await executor.execute(tasks)
        except Exception:
            # Only infrastructure-level failure (e.g. ResultAggregator crash)
            # reaches here; per-task crashes are absorbed inside the executor.
            print('\n❌ cc-mini batch execution failed:', file=sys.stderr)
            traceback.print_exc()
            sys.exit(1)
        finally:
            if prev_report_ts is None:
                os.environ.pop('WEBQA_REPORT_TIMESTAMP', None)
            else:
                os.environ['WEBQA_REPORT_TIMESTAMP'] = prev_report_ts

        passed_count = sum(1 for s in batch.statuses if s == 'passed')
        print('\n' + '-' * 60)
        status_label = (
            '✅ Done' if batch.overall_status == 'passed'
            else '❌ Some cases failed'
        )
        print(
            f'{status_label}  |  Cases: {passed_count}/{len(tasks)} passed  |  '
            f'Steps: {batch.total_steps}  |  '
            f'Tokens: {batch.total_input_tokens}↑ {batch.total_output_tokens}↓'
        )
        for i, (task_text, status) in enumerate(zip(tasks, batch.statuses), start=1):
            icon = {'passed': '✅', 'warning': '⚠️ ', 'failed': '❌'}.get(status, '❌')
            preview = task_text if len(task_text) <= 60 else task_text[:57] + '...'
            print(f'   case-{i} {icon} {status:<7}  {preview}')

        # Surface extension-loading failures from any case. Each result keeps
        # its own list; merge them so users see the union without duplicates.
        ext_failed_all: list[str] = []
        seen: set[str] = set()
        for r in batch.run_results:
            for line in (getattr(r, 'extensions_failed', None) or []):
                if line not in seen:
                    seen.add(line)
                    ext_failed_all.append(line)
        if ext_failed_all:
            print('⚠️  cc-mini extensions reported failures:', file=sys.stderr)
            for line in ext_failed_all:
                print(f'   - {line}', file=sys.stderr)

        if batch.report_path:
            print(f'📄 Report: {batch.report_path}')
        if batch.dataflow_path:
            print(f'📊 Data flow: {batch.dataflow_path}')
        if batch.overall_status != 'passed':
            sys.exit(1)
        return

    # Check Playwright browsers
    ok = await check_playwright_browsers_async()
    if not ok:
        print('\n💡 Install browsers with: playwright install chromium', file=sys.stderr)
        sys.exit(1)

    # Check custom tool dependencies
    custom_tools_enabled = tconf.get('custom_tools', {}).get('enabled', [])
    if 'lighthouse' in custom_tools_enabled:
        if not check_lighthouse_installation():
            print('\n💡 Install Lighthouse: npm install lighthouse chrome-launcher (local, recommended) or npm install -g lighthouse chrome-launcher (global)', file=sys.stderr)
            sys.exit(1)

    if 'nuclei' in custom_tools_enabled:
        if not check_nuclei_installation():
            print('\n💡 Install Nuclei: go install -v github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest or download from https://github.com/projectdiscovery/nuclei/releases', file=sys.stderr)
            sys.exit(1)

    # Build browser config
    browser_cfg_raw = cfg.get('browser_config', {})
    is_docker = os.getenv('DOCKER_ENV') == 'true'
    headless = True if is_docker else browser_cfg_raw.get('headless', True)

    config_dir = resolve_config_dir(config_path)
    cookies_value = browser_cfg_raw.get('cookies', [])
    cookies = load_cookies(cookies_value, config_dir=config_dir)
    browser_config = BrowserConfig(
        browser_type=browser_cfg_raw.get('browser_type', 'chromium'),
        headless=headless,
        viewport=browser_cfg_raw.get('viewport', {'width': 1280, 'height': 720}),
        language=browser_cfg_raw.get('language', 'en-US'),
        cookies=cookies
    )

    # Build report config
    report_cfg_raw = cfg.get('report', {})
    report_config = ReportConfig(
        language=report_cfg_raw.get('language', 'en-US'),
        report_dir=report_cfg_raw.get('report_dir'),
        save_screenshots=report_cfg_raw.get('save_screenshots', False),
        save_dataflow=report_cfg_raw.get('save_dataflow', True),
    )

    # Build log config
    log_cfg_raw = cfg.get('log', {})
    log_config = LogConfig(
        level=log_cfg_raw.get('level', 'info')
    )

    # Build test configuration
    dynamic_step_cfg = tconf.get('dynamic_step_generation', {})
    dynamic_step_config = DynamicStepConfig(
        enabled=dynamic_step_cfg.get('enabled', True),
        max_dynamic_steps=dynamic_step_cfg.get('max_dynamic_steps', 8),
        min_elements_threshold=dynamic_step_cfg.get('min_elements_threshold', 2)
    )

    custom_tools_cfg = tconf.get('custom_tools', {})
    custom_tools_config = CustomToolsConfig(
        enabled=custom_tools_cfg.get('enabled', [])
    )
    # Reflection: enable_reflection in YAML maps to skip_reflection in GenConfig
    enable_reflection = tconf.get('enable_reflection', True)
    skip_reflection = not enable_reflection

    # Test files directory for upload testing
    test_files_dir = tconf.get('test_files_dir')

    # Build GenConfig
    gen_config = GenConfig(
        target_url=target_url,
        llm_config=llm_config,
        browser_config=browser_config,
        report_config=report_config,
        log_config=log_config,
        planning_mode=planning_mode,
        business_objectives=business_objectives,
        dynamic_step_generation=dynamic_step_config,
        custom_tools=custom_tools_config,
        max_concurrent_tests=workers,
        skip_reflection=skip_reflection,
        test_files_dir=test_files_dir,
    )

    # Display configuration
    print('📋 Tests enabled: Gen Mode')
    if custom_tools_enabled:
        print(f'🔧 Custom tools: {", ".join(custom_tools_enabled)}')

    # Execute tests
    try:
        print(f'⚙️ Concurrency: {workers}')

        executor = GenExecutor(gen_config)
        results, report_path, html_report_path, result_count = await executor.execute()

        if result_count:
            print('📊 Results Summary:')
            print(f"   Total: {result_count.get('total', 0)}")
            print(f"   ✅ Passed: {result_count.get('passed', 0)}")
            print(f"   ⚠️ Warning: {result_count.get('warning', 0)}")
            print(f"   ❌ Failed: {result_count.get('failed', 0)}")

        if html_report_path:
            print(f'\n📄 Report: {html_report_path}')

    except Exception:
        print('\n❌ Test execution failed:', file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


async def execute_run_mode(config_path: str, workers: int = None):
    """Execute test cases from file or folder.

    Args:
        config_path: Path to config file or folder
        workers: Workers value from CLI (None if not specified)
    """
    from webqa_agent.config_models.run_config import RunConfig
    from webqa_agent.executor.run_executor import RunExecutor

    # Load first config to extract settings
    try:
        if os.path.isdir(config_path):
            configs = load_yaml_files(config_path)
            total_cases = sum(len(c.get('cases', [])) for c in configs)
            print(f'📋 Loaded {len(configs)} config(s) with {total_cases} total cases')
        else:
            configs = [load_yaml(config_path)]
            cases = configs[0].get('cases', [])
            if not cases:
                print('⚠️ No cases defined in configuration', file=sys.stderr)
                sys.exit(1)
            target_url = configs[0].get('target', {}).get('url', '')
            if target_url:
                print(f'🎯 Target URL: {target_url}')
            print(f'📋 Total cases: {len(cases)}')
    except Exception as e:
        print(f'❌ Failed to load configs: {e}', file=sys.stderr)
        sys.exit(1)

    # Ensure run mode only executes on 'standard' engine
    engine = str(configs[0].get('engine', 'standard')).strip().lower()
    if engine != 'standard':
        print(f'❌ Run Mode is only supported on the "standard" engine, but "engine: {engine}" was configured.', file=sys.stderr)
        sys.exit(1)

    # Pre-process cookies for all configs (load from file path if needed)
    for cfg in configs:
        raw_cookies = cfg.get('cookies') or cfg.get('browser_config', {}).get('cookies')
        if raw_cookies:
            loaded_cookies = load_cookies(
                raw_cookies,
                config_dir=resolve_config_dir(cfg.get('_source_file') or config_path),
            )
            # Update both possible locations to ensure consistency
            if 'cookies' in cfg:
                cfg['cookies'] = loaded_cookies
            if cfg.get('browser_config', {}).get('cookies'):
                cfg['browser_config']['cookies'] = loaded_cookies

    # Resolve workers: CLI > config > default (4)
    w = workers if workers is not None else configs[0].get('target', {}).get('max_concurrent_tests', 4)
    try:
        workers = max(1, int(w))
    except (ValueError, TypeError):
        workers = 4
    mode_info = f'parallel ({workers} workers)' if workers > 1 else 'serial'
    print(f'🎯 Mode: Run Mode ({mode_info})')

    # Validate LLM config
    try:
        llm_config_dict = validate_and_build_llm_config(configs[0])
    except ValueError as e:
        print(f'\n{e}', file=sys.stderr)
        sys.exit(1)

    # Check Playwright browsers
    ok = await check_playwright_browsers_async()
    if not ok:
        print('\n💡 Install browsers with: playwright install chromium', file=sys.stderr)
        sys.exit(1)

    # Build RunConfig from loaded settings
    try:
        run_config = RunConfig(
            llm_config=LLMConfig(**llm_config_dict),
            browser_config=BrowserConfig(**configs[0].get('browser_config', {})),
            report_config=ReportConfig(**configs[0].get('report', {'language': 'en-US'})),
            log_config=LogConfig(**configs[0].get('log', {'level': 'info'})),
            cases_path=config_path,  # Pass original path for RunExecutor to load
            workers=workers,
            ignore_rules=configs[0].get('ignore_rules'),
            accounts=load_accounts(
                configs[0].get('accounts'),
                source_file=configs[0].get('_source_file') or config_path,
            ),
        )
    except Exception as e:
        print(f'❌ Failed to create RunConfig: {e}', file=sys.stderr)
        sys.exit(1)

    # Execute cases using RunExecutor
    try:
        executor = RunExecutor(run_config)
        results, report_path, html_report_path, result_count = await executor.execute()

        # Print results
        if result_count:
            print('📊 Results Summary:')
            print(f"   Total: {result_count.get('total', 0)}")
            print(f"   ✅ Passed: {result_count.get('passed', 0)}")
            print(f"   ⚠️ Warning: {result_count.get('warning', 0)}")
            print(f"   ❌ Failed: {result_count.get('failed', 0)}")

        if html_report_path:
            print(f'\n📄 Report: {html_report_path}')

        if result_count and result_count.get('failed', 0) > 0:
            sys.exit(1)

    except Exception as e:
        print(f'\n❌ Test execution failed: {e}', file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


def cmd_run(args):
    """Run command handler (Run Mode)."""
    config_path = args.config if hasattr(args, 'config') else None
    workers = args.workers if hasattr(args, 'workers') else None

    if not config_path:
        # Auto-search for config file, but prioritize config_run.yaml or config_run.yaml
        for p in ['config_run.yaml', './config/config_run.yaml']:
            if os.path.exists(p):
                config_path = p
                break

        if not config_path:
            config_path = find_config_file(None)

        if config_path is None:
            print('❌ No configuration file found!')
            print('💡 Create a new Run mode config: webqa-agent init --mode run')
            sys.exit(1)

    if os.path.isdir(config_path):
        print(f'📂 Using config folder: {config_path}')
        asyncio.run(execute_run_mode(config_path, workers=workers))
    else:
        print(f'📂 Using config: {config_path}')
        cfg = load_yaml(config_path)
        if 'cases' not in cfg:
            print('⚠️ Warning: Config does not contain "cases" field, but running in Run mode.', file=sys.stderr)

        asyncio.run(run_tests(cfg, execution_mode='run', config_path=config_path, workers=workers))


def cmd_gen(args):
    """Gen command handler (Gen Mode / AI Mode)."""
    config_path = args.config if hasattr(args, 'config') else None
    workers = args.workers if hasattr(args, 'workers') else None

    if not config_path:
        # Auto-search for config file
        config_path = find_config_file(None)
        if config_path is None:
            print('❌ No configuration file found!')
            print('💡 Create a new Gen mode config: webqa-agent init')
            sys.exit(1)

    print(f'📂 Using config: {config_path}')
    cfg = load_yaml(config_path)

    if 'test_config' not in cfg:
        print('❌ Gen mode requires "test_config" field in configuration', file=sys.stderr)
        print('💡 Create a Gen mode config: webqa-agent init', file=sys.stderr)
        sys.exit(1)

    asyncio.run(run_tests(cfg, execution_mode='gen', config_path=config_path, workers=workers))


# ============================================================================
# Main Entry Point
# ============================================================================

def create_parser():
    """Create argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog='webqa-agent',
        description='WebQA Agent - AI-powered web quality assurance testing',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initialize configuration
  webqa-agent init                          Create Gen mode config (default)
  webqa-agent init --mode run               Create Run mode config

  # Run tests
  webqa-agent gen                           Gen mode, auto-search config.yaml
  webqa-agent gen -c myconfig.yaml          Gen mode with custom config
  webqa-agent run -c config_run.yaml        Run mode with custom config
  webqa-agent run -c config_folder -w 4     Run mode with 4 workers

Modes:
  - Gen Mode: AI-driven test generation (function, UX, performance, security)
  - Run Mode: Execute predefined YAML test cases

Documentation: https://github.com/MigoXLab/webqa-agent
"""
    )

    parser.add_argument(
        '--version', '-v',
        action='version',
        version=f'%(prog)s {get_version()}'
    )

    subparsers = parser.add_subparsers(
        title='Commands',
        dest='command',
        metavar='<command>'
    )

    # init command
    init_parser = subparsers.add_parser(
        'init',
        help='Create a new configuration file',
        description='Initialize a new WebQA Agent configuration file with default settings.'
    )
    init_parser.add_argument(
        '--mode', '-m',
        choices=['gen', 'run'],
        default='gen',
        help='Configuration mode: gen (AI-driven test generation) or run (YAML-defined test cases). Default: gen'
    )
    init_parser.add_argument(
        '--output', '-o',
        metavar='PATH',
        default='config.yaml',
        help='Output path for config file (default: config.yaml)'
    )
    init_parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Overwrite existing config file'
    )

    # gen command
    gen_parser = subparsers.add_parser(
        'gen',
        help='AI-driven test generation and execution',
        description='Automatically generate and execute test cases based on business objectives.'
    )
    gen_parser.add_argument(
        '--config', '-c',
        metavar='PATH',
        help='Config file path (default: search for config.yaml)'
    )
    gen_parser.add_argument(
        '--workers', '-w',
        type=int,
        default=None,
        metavar='N',
        help='Number of parallel workers. Priority: CLI arg > config max_concurrent_tests > default 4'
    )

    # run command
    run_parser = subparsers.add_parser(
        'run',
        help='Execute predefined test cases',
        description='Execute web quality assurance tests from YAML case files.'
    )
    run_parser.add_argument(
        '--config', '-c',
        metavar='PATH',
        help='Config file or folder path. Folder input loads all YAML files.'
    )
    run_parser.add_argument(
        '--workers', '-w',
        type=int,
        default=None,
        metavar='N',
        help='Number of parallel workers (1=serial, >1=parallel). Priority: CLI arg > config max_concurrent_tests > default 4'
    )
    # ui command
    ui_parser = subparsers.add_parser(
        'ui',
        help='Launch Gradio web UI',
        description='Start the Gradio interface for WebQA Agent.'
    )
    ui_parser.add_argument(
        '--lang', '-l',
        default=os.getenv('GRADIO_LANGUAGE', 'en-US'),
        help='Interface language (en-US or zh-CN). Defaults to GRADIO_LANGUAGE env or en-US.'
    )
    ui_parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='Host to bind (default: 0.0.0.0)'
    )
    ui_parser.add_argument(
        '--port',
        type=int,
        default=7860,
        help='Port to serve (default: 7860)'
    )
    ui_parser.add_argument(
        '--no-browser',
        action='store_true',
        help='Do not auto-open browser'
    )

    return parser


def main():
    """Main entry point for the CLI."""
    parser = create_parser()
    args = parser.parse_args()

    # Show help if no command provided
    if args.command is None:
        parser.print_help()
        print()
        print('💡 Quick start:')
        print('   # Gen Mode - AI-driven test, automatically generate and execute test cases')
        print('   webqa-agent init')
        print('   webqa-agent gen')
        print()
        print('   # Run Mode - Execute predefined test cases')
        print('   webqa-agent init --mode run')
        print('   webqa-agent run -c config_run.yaml')
        print()
        sys.exit(0)

    # Dispatch to command handler
    if args.command == 'init':
        cmd_init(args)
    elif args.command == 'gen':
        cmd_gen(args)
    elif args.command == 'run':
        cmd_run(args)


if __name__ == '__main__':
    main()
