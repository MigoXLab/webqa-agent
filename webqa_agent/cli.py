#!/usr/bin/env python3
"""WebQA Agent CLI - Command line interface for web quality assurance testing."""

import argparse
import asyncio
import importlib.util
import os
import sys
import traceback
from pathlib import Path

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


def get_version():
    """Get the package version."""
    from webqa_agent import __version__
    return __version__


def get_template_content(mode):
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
    """Load ``run_cc_mini`` from the sibling webqa-cc-mini tree on demand."""
    cc_mini_root = Path(__file__).resolve().parent.parent / 'webqa-cc-mini'
    runner_path = cc_mini_root / 'runner.py'

    if not runner_path.exists():
        raise FileNotFoundError(f'webqa-cc-mini runner not found: {runner_path}')

    module_name = 'webqa_cc_mini_runner'
    cached_module = sys.modules.get(module_name)
    if cached_module is not None:
        run_cc_mini = getattr(cached_module, 'run_cc_mini', None)
        if callable(run_cc_mini):
            return run_cc_mini

    original_sys_path = list(sys.path)
    try:
        if str(cc_mini_root) not in sys.path:
            sys.path.insert(0, str(cc_mini_root))

        spec = importlib.util.spec_from_file_location(module_name, runner_path)
        if spec is None or spec.loader is None:
            raise ImportError(f'Failed to create import spec for {runner_path}')

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_sys_path

    run_cc_mini = getattr(module, 'run_cc_mini', None)
    if not callable(run_cc_mini):
        raise AttributeError(f'run_cc_mini not found in {runner_path}')
    return run_cc_mini


async def _execute_cc_mini_mode(
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
    skills_dir: str | None = None,
    log_level: str = 'info',
    on_event=None,
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
    """
    from webqa_agent.utils.get_log import GetLog
    GetLog.get_log(log_level=log_level)

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
        skills_dir=skills_dir,
        on_event=on_event,
    )


def _render_cc_mini_report(
    result, *, cfg: dict, url: str, task: str,
) -> str | None:
    """Render an HTML report for a cc-mini RunResult.

    Preferred path reuses the gen-mode React frontend by mapping the
    RunResult into a ``ParallelTestSession`` (via
    :mod:`webqa_agent.executor.cc_mini_report_adapter`) and handing it to
    :class:`ResultAggregator`. This way CLI users see the same UI
    regardless of which backend executed the run.

    The standalone ``webqa-cc-mini/features/report.py`` utility is kept
    as a fallback so that:
        1. Library users (no webqa_agent installed) still get an HTML
           artifact without pulling in the gen-mode stack.
        2. A broken gen-mode static bundle does not prevent CLI users
           from getting *some* report.

    Returns the absolute report path on success, ``None`` on failure.
    Report generation must never block the run — all exceptions are
    caught and surfaced as warnings.
    """
    import datetime as _dt
    from pathlib import Path as _Path

    report_dir = (cfg.get('report') or {}).get('report_dir') or \
        f"reports/cc_mini_{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_path = _Path(report_dir) / 'report.html'
    language = (cfg.get('report') or {}).get('language', 'zh-CN')

    # Preferred: gen-mode frontend via adapter + ResultAggregator.
    # The React shell reads ``window.testResultData`` expecting the
    # gen-mode aggregated shape (``{"gen": {"case_1_<safe>": {...},
    # "index": {...}}}``). ``ParallelTestSession.to_dict()`` produces a
    # different schema, so always pass the synthesized aggregated dict
    # via ``aggregated_data=`` — the session only carries metadata.
    try:
        from webqa_agent.executor.cc_mini_report_adapter import (
            run_result_to_aggregated_data, run_result_to_session)
        from webqa_agent.executor.result_aggregator import ResultAggregator

        session = run_result_to_session(
            result, url=url, task=task,
            report_dir=str(out_path.parent), language=language,
        )
        aggregated_data = run_result_to_aggregated_data(
            result, url=url, task=task, language=language,
        )
        aggregator = ResultAggregator(report_config={
            'language': language, 'report_dir': str(out_path.parent),
        })
        # ResultAggregator writes ``test_report.html`` (gen-mode convention)
        # and returns its absolute path on success, empty string on failure.
        generated_path = aggregator.generate_html_report_fully_inlined(
            session,
            report_dir=str(out_path.parent),
            aggregated_data=aggregated_data,
        )
        if generated_path and _Path(generated_path).exists():
            return generated_path
    except Exception as exc:
        print(
            f'⚠️  Gen-mode report rendering failed, falling back to '
            f'standalone renderer: {exc}',
            file=sys.stderr,
        )

    # Fallback: standalone cc-mini utility (self-contained, no gen deps).
    try:
        cc_mini_root = _Path(__file__).resolve().parent.parent / 'webqa-cc-mini'
        if str(cc_mini_root) not in sys.path:
            sys.path.insert(0, str(cc_mini_root))
        from features.report import render_html_report
    except ImportError as exc:
        print(f'⚠️  Could not import render_html_report: {exc}', file=sys.stderr)
        return None

    try:
        html_path = render_html_report(
            result, out_path, title=f'WebQA cc-mini — {url}',
            url=url, task=task,
        )
        return str(html_path)
    except Exception as exc:
        print(f'⚠️  Report generation failed: {exc}', file=sys.stderr)
        return None


def _make_cc_mini_stream_handler():
    """Return an ``on_event`` callback that streams runner progress to stdout.

    Without this handler the user sees only the final ``result.final_text``
    after the entire run completes, which makes a multi-step web agent feel
    unresponsive. The handler forwards every engine event the moment it
    arrives:

    * ``text`` chunks — printed inline, flushed per chunk
    * ``tool_call`` — one line with the MCP activity description
    * ``tool_result`` — only errors are surfaced (success is implicit)
    * ``usage`` — per-call token counts so long runs have visible heartbeat
    * ``error`` — non-fatal API errors forwarded verbatim

    The handler tracks whether the last printed character was a newline so
    tool-call markers don't glue onto a half-streamed sentence.
    """
    # Mutable flag captured by closure; list form avoids ``nonlocal`` noise.
    text_open = [False]

    def _close_text() -> None:
        if text_open[0]:
            print('', flush=True)
            text_open[0] = False

    def handle(evt) -> None:
        kind = evt[0]
        if kind == 'text':
            chunk = evt[1]
            print(chunk, end='', flush=True)
            text_open[0] = not chunk.endswith('\n')
        elif kind == 'waiting':
            _close_text()
        elif kind == 'tool_call':
            _close_text()
            _, name, _tool_input, activity = evt
            print(f'🔧 {activity or name}', flush=True)
        elif kind == 'tool_result':
            _, name, _input, result = evt
            if result.is_error:
                content = result.content if isinstance(result.content, str) else str(result.content)
                snippet = content[:200].replace('\n', ' ')
                print(f'   ❌ [{name}] {snippet}', flush=True)
        elif kind == 'usage':
            u = evt[1]
            inp = getattr(u, 'input_tokens', 0) or 0
            out = getattr(u, 'output_tokens', 0) or 0
            print(f'   📊 {inp}↑ {out}↓', flush=True)
        elif kind == 'error':
            _close_text()
            print(f'⚠️  {evt[1]}', flush=True)

    return handle


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

        mode_name = 'Gen Mode' if mode == 'gen' else 'Run Mode'
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
    use_cc_mini = bool(tconf.get('use_cc_mini', False))

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

    if use_cc_mini:
        task = business_objectives.strip()
        if not task:
            print('❌ test_config.business_objectives is required when test_config.use_cc_mini=true', file=sys.stderr)
            sys.exit(1)

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

        print('📋 Tests enabled: Gen Mode (cc-mini backend)')
        print(f'⚙️ cc-mini URL: {target_url}')
        print(f'📝 cc-mini Task: {task}')
        print(f'🤖 cc-mini Provider: {provider}')
        print('-' * 60, flush=True)

        log_level = cfg.get('log', {}).get('level', 'info')

        try:
            result = await _execute_cc_mini_mode(
                url=target_url,
                task=task,
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
                log_level=log_level,
                on_event=_make_cc_mini_stream_handler(),
            )
        except Exception:
            print('\n❌ cc-mini execution failed:', file=sys.stderr)
            traceback.print_exc()
            sys.exit(1)

        # The final assistant text was already streamed via on_event; only
        # print a summary bar so the user sees totals at a glance.
        print('\n' + '-' * 60)
        print(
            f'✅ Done  |  Steps: {len(result.steps)}  |  '
            f'Tokens: {result.input_tokens}↑ {result.output_tokens}↓  |  '
            f'Aborted: {result.aborted}'
        )

        # Generate HTML report — mirrors the gen-mode GenExecutor flow so
        # both backends produce the same deliverable for CLI users.
        report_path = _render_cc_mini_report(
            result, cfg=cfg, url=target_url, task=task,
        )
        if report_path:
            print(f'📄 Report: {report_path}')
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
