#!/usr/bin/env python3
"""WebQA Agent CLI - Command line interface for web quality assurance testing."""

import argparse
import asyncio
import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path

from webqa_agent.executor import ParallelMode
from webqa_agent.utils import (check_lighthouse_installation,
                               check_nuclei_installation,
                               check_playwright_browsers_async,
                               find_config_file, load_cookies, load_yaml,
                               load_yaml_files)


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
    # Try to find template in multiple locations
    current_dir = Path(__file__).parent.parent  # webqa-agent root

    if mode == 'gen':
        template_paths = [
            current_dir / 'config' / 'config.yaml.example',
            Path('config/config.yaml.example'),
        ]
    elif mode == 'run':
        template_paths = [
            current_dir / 'config' / 'config_run.yaml.example',
            Path('config/config_run.yaml.example'),
        ]
    else:
        raise ValueError(f'Invalid mode: {mode}')

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

    # Display configuration (masked)
    api_key_masked = f'{api_key[:8]}...{api_key[-4:]}' if len(api_key) > 12 else '***'
    print('✅ LLM configuration validated:')
    print(f'   Model: {model}')
    if filter_model != model:
        print(f'   Filter Model: {filter_model}')
    print(f'   API Key: {api_key_masked}')
    print(f'   Base URL: {base_url}')

    return llm_config


# ============================================================================
# Test Configuration Builder
# ============================================================================

def build_test_configurations(cfg, cookies=None):
    """Build test configurations from config file."""
    tests = []
    tconf = cfg.get('test_config', {})

    is_docker = os.getenv('DOCKER_ENV') == 'true'
    config_headless = cfg.get('browser_config', {}).get('headless', True)
    headless = True if is_docker else config_headless

    base_browser = {
        'viewport': cfg.get('browser_config', {}).get('viewport', {'width': 1280, 'height': 720}),
        'headless': headless,
    }
    business_objectives = tconf.get('function_test', {}).get('business_objectives', '')
    if not business_objectives:
        business_objectives = ''
    # Function test
    if tconf.get('function_test', {}).get('enabled'):
        if tconf['function_test'].get('type') == 'ai':
            tests.append({
                'test_type': 'ui_agent_langgraph',
                'enabled': True,
                'browser_config': base_browser,
                'test_specific_config': {
                    'cookies': cookies,
                    'business_objectives': business_objectives,
                    'dynamic_step_generation': tconf['function_test'].get('dynamic_step_generation', {}),
                },
            })
        else:
            tests.append({
                'test_type': 'basic_test',
                'enabled': True,
                'browser_config': base_browser,
                'test_specific_config': {},
            })

    # UX test
    if tconf.get('ux_test', {}).get('enabled'):
        tests.append({
            'test_type': 'ux_test',
            'enabled': True,
            'browser_config': base_browser,
            'test_specific_config': {},
        })

    # Performance test
    if tconf.get('performance_test', {}).get('enabled'):
        tests.append({
            'test_type': 'performance',
            'enabled': True,
            'browser_config': base_browser,
            'test_specific_config': {},
        })

    # Security test
    if tconf.get('security_test', {}).get('enabled'):
        tests.append({
            'test_type': 'security',
            'enabled': True,
            'browser_config': base_browser,
            'test_specific_config': {},
        })

    return tests


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
        print('   Expected template files:', file=sys.stderr)
        print('   - config/config.yaml.example (Gen mode)', file=sys.stderr)
        print('   - config/config_run.yaml.example (Run mode)', file=sys.stderr)
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

    # Configure screenshot saving
    from webqa_agent.actions.action_handler import ActionHandler
    save_screenshots = cfg.get('browser_config', {}).get('save_screenshots', False)
    ActionHandler.set_screenshot_config(save_screenshots=save_screenshots)
    if not save_screenshots:
        print('📸 Screenshot saving: disabled (screenshots will be captured but not saved to disk)')
    else:
        print('📸 Screenshot saving: enabled')

    # Execute based on mode
    if execution_mode == 'run':
        await execute_run_mode(config_path, workers=workers)
    else:  # gen mode
        # Resolve workers: CLI > config > default (2)
        w = workers if workers is not None else cfg.get('target', {}).get('max_concurrent_tests', 2)
        try:
            workers = max(1, int(w))
        except (ValueError, TypeError):
            workers = 2
        print('🎯 Mode: Gen Mode (AI-driven test generation)')
        await execute_gen_mode(cfg, workers=workers)


async def execute_gen_mode(cfg, workers: int = 1):
    """Execute Gen mode tests."""
    # Check enabled tests
    tconf = cfg.get('test_config', {})
    enabled_tests = []
    if tconf.get('function_test', {}).get('enabled'):
        test_type = tconf.get('function_test', {}).get('type', 'default')
        enabled_tests.append(f'Function Test ({test_type})')
    if tconf.get('ux_test', {}).get('enabled'):
        enabled_tests.append('User Experience Test')
    if tconf.get('performance_test', {}).get('enabled'):
        enabled_tests.append('Performance Test')
    if tconf.get('security_test', {}).get('enabled'):
        enabled_tests.append('Security Test')

    if not enabled_tests:
        print('⚠️ No test types enabled in configuration')
        sys.exit(1)

    print(f"📋 Tests enabled: {', '.join(enabled_tests)}")

    # Check dependencies
    needs_browser = any([
        tconf.get('function_test', {}).get('enabled'),
        tconf.get('ux_test', {}).get('enabled'),
        tconf.get('performance_test', {}).get('enabled'),
        tconf.get('security_test', {}).get('enabled'),
    ])

    if needs_browser:
        ok = await check_playwright_browsers_async()
        if not ok:
            print('\n💡 Install browsers with: playwright install chromium', file=sys.stderr)
            sys.exit(1)

    if tconf.get('performance_test', {}).get('enabled'):
        if not check_lighthouse_installation():
            print('\n💡 Install Lighthouse: npm install lighthouse chrome-launcher', file=sys.stderr)
            sys.exit(1)

    if tconf.get('security_test', {}).get('enabled'):
        if not check_nuclei_installation():
            print('\n💡 Install Nuclei: https://github.com/projectdiscovery/nuclei', file=sys.stderr)
            sys.exit(1)

    # Validate LLM config
    try:
        llm_config = validate_and_build_llm_config(cfg)
    except ValueError as e:
        print(f'\n{e}', file=sys.stderr)
        sys.exit(1)

    # Build test configurations
    cookies_value = cfg.get('browser_config', {}).get('cookies', [])
    cookies = load_cookies(cookies_value)
    test_configurations = build_test_configurations(cfg, cookies=cookies)
    target_url = cfg.get('target', {}).get('url', '')

    if not target_url:
        print('❌ No target URL specified in configuration', file=sys.stderr)
        sys.exit(1)

    print(f'🎯 Target URL: {target_url}')

    # Execute tests
    try:
        print(f'⚙️ Concurrency: {workers}')

        parallel_mode = ParallelMode([], max_concurrent_tests=workers)
        results, report_path, html_report_path, result_count = await parallel_mode.run(
            url=target_url,
            llm_config=llm_config,
            test_configurations=test_configurations,
            log_cfg=cfg.get('log', {'level': 'info'}),
            report_cfg=cfg.get('report', {'language': 'en-US'})
        )

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
    from webqa_agent.executor.case_mode import CaseMode

    # Load config(s)
    is_folder = os.path.isdir(config_path)
    if is_folder:
        try:
            configs = load_yaml_files(config_path)
        except Exception as e:
            print(f'❌ Failed to load configs: {e}', file=sys.stderr)
            sys.exit(1)
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

    # Resolve workers: CLI > config > default (2)
    w = workers if workers is not None else configs[0].get('target', {}).get('max_concurrent_tests', 2)
    try:
        workers = max(1, int(w))
    except (ValueError, TypeError):
        workers = 2
    mode_info = f'parallel ({workers} workers)' if workers > 1 else 'serial'
    print(f'🎯 Mode: Run Mode ({mode_info})')

    # Validate LLM config
    try:
        llm_config = validate_and_build_llm_config(configs[0])
    except ValueError as e:
        print(f'\n{e}', file=sys.stderr)
        sys.exit(1)

    # Check Playwright browsers
    ok = await check_playwright_browsers_async()
    if not ok:
        print('\n💡 Install browsers with: playwright install chromium', file=sys.stderr)
        sys.exit(1)

    # Execute cases (unified API handles both single/multi config)
    try:
        case_mode = CaseMode()
        results, report_path, html_report_path, result_count = await case_mode.run(
            configs=configs,  # Pass all configs - run() handles single vs multi
            llm_config=llm_config,
            log_config=configs[0].get('log', {'level': 'info'}),
            report_config=configs[0].get('report', {'language': 'en-US'}),
            workers=workers,
        )

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
        import traceback
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

    asyncio.run(run_tests(cfg, execution_mode='gen', workers=workers))


def cmd_ui(args):
    """Launch Gradio web UI."""
    # Set language if provided
    if args.lang:
        os.environ['GRADIO_LANGUAGE'] = args.lang

    # Check gradio
    try:
        import gradio
    except ImportError:
        print("❌ Gradio is not installed. Install with: uv add \"gradio>5.44.0\"")
        sys.exit(1)

    # Optional version check
    try:
        from packaging import version
        required = '5.44.0'
        if version.parse(gradio.__version__) <= version.parse(required):
            print(f'❌ Gradio version {gradio.__version__} detected, need >= {required}')
            print(f"Install/upgrade: uv add \"gradio>={required}\"")
            sys.exit(1)
    except ImportError:
        pass

    # Import UI factory
    try:
        from app_gradio.demo_gradio import (create_gradio_interface,
                                            process_queue)
    except ImportError as e:
        print(f'❌ Failed to import Gradio app: {e}')
        sys.exit(1)

    # Ensure Playwright browsers
    ok = asyncio.run(check_playwright_browsers_async())
    if not ok:
        print('🔍 Playwright browsers missing, installing chromium ...')
        try:
            subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], check=True)
            ok = asyncio.run(check_playwright_browsers_async())
        except Exception as e:
            print(f'❌ Failed to install Playwright browsers: {e}')
            print('Please run manually: playwright install chromium')
            sys.exit(1)

    if not ok:
        print('❌ Playwright browsers still unavailable. Please run: playwright install chromium')
        sys.exit(1)

    # Start queue processor thread
    def _run_queue():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(process_queue())

    queue_thread = threading.Thread(target=_run_queue, daemon=True)
    queue_thread.start()

    language = os.getenv('GRADIO_LANGUAGE', 'en-US')
    print('🚀 Starting WebQA Agent Gradio UI ...')
    print(f'🌐 Language: {language}')
    print(f'🔗 http://{args.host}:{args.port}')
    print('💡 Set GRADIO_LANGUAGE=en-US or zh-CN to switch interface language.')

    app = create_gradio_interface(language=language)
    try:
        app.launch(
            server_name=args.host,
            server_port=args.port,
            share=False,
            show_error=True,
            inbrowser=not args.no_browser,
        )
    except Exception as e:
        print(f'❌ Failed to launch Gradio UI: {e}')
        sys.exit(1)


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

  # Launch web UI
  webqa-agent ui                            Start Gradio interface
  webqa-agent ui --lang zh-CN               Start with Chinese interface

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
        help='Number of parallel workers. Priority: CLI arg > config max_concurrent_tests > default 2'
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
        help='Number of parallel workers (1=serial, >1=parallel). Priority: CLI arg > config max_concurrent_tests > default 2'
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
    elif args.command == 'ui':
        cmd_ui(args)


if __name__ == '__main__':
    main()
