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
                               find_config_file, load_cookies, load_yaml)


def get_version():
    """Get the package version."""
    from webqa_agent import __version__
    return __version__


def get_template_content(mode):
    """Get configuration template content from example files.
    
    Args:
        mode: 'ai' or 'case'
        
    Returns:
        Template content as string, or None if not found
    """
    # Try to find template in multiple locations
    current_dir = Path(__file__).parent.parent  # webqa-agent root
    
    if mode == 'ai':
        template_paths = [
            current_dir / 'config' / 'config.yaml.example',
            Path('config/config.yaml.example'),
        ]
    elif mode == 'case':  # case
        template_paths = [
            current_dir / 'config' / 'config_case.yaml.example',
            Path('config/config_case.yaml.example'),
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
    temperature = llm_cfg_raw.get('temperature', 0.1)
    top_p = llm_cfg_raw.get('top_p')
    max_tokens = llm_cfg_raw.get('max_tokens')
    reasoning = llm_cfg_raw.get('reasoning')
    text_cfg = llm_cfg_raw.get('text')

    # Validate required fields
    if not api_key or api_key == 'your_api_key_here':
        raise ValueError(
            '❌ LLM API Key not configured!\n'
            '   Please set one of the following:\n'
            '   - Environment variable: OPENAI_API_KEY\n'
            '   - Config file: llm_config.api_key'
        )

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

    # Function test
    if tconf.get('function_test', {}).get('enabled'):
        if tconf['function_test'].get('type') == 'ai':
            tests.append({
                'test_type': 'ui_agent_langgraph',
                'enabled': True,
                'browser_config': base_browser,
                'test_specific_config': {
                    'cookies': cookies,
                    'business_objectives': tconf['function_test'].get('business_objectives', ''),
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
    mode = args.mode or 'ai'
    if mode == 'ai':
        output_path = 'config.yaml'
    elif mode == 'case':
        output_path = 'config_case.yaml'
    # Validate mode
    if mode not in ['ai', 'case']:
        print(f'❌ Invalid mode: {mode}')
        print('   Valid modes: ai, case')
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
        print(f'   - config/config.yaml.example (AI mode)', file=sys.stderr)
        print(f'   - config/config_case.yaml.example (case mode)', file=sys.stderr)
        sys.exit(1)

    # Write config file
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(template)

        mode_name = 'AI Mode' if mode == 'ai' else 'Case Mode'
        print(f'✅ Configuration file created: {output_path} ({mode_name})')
        print()
        print('📝 Next steps:')
        print(f'   1. Edit {output_path} to configure:')
        print('      - target.url: The website URL to test')
        print('      - llm_config.api: The LLM API provider (openai, anthropic, etc.)')
        print('      - llm_config.api_key: Your API key')
        print('      - llm_config.base_url: The base URL of the API')
        
        if mode == 'ai':
            print('      - test_config: Enable/disable test types')
        else:
            print('      - cases: Define your test cases and steps')
        
        print()
        print('   2. Run tests:')
        print(f'      webqa-agent run -c {output_path}')

    except Exception as e:
        print(f'❌ Failed to create config file: {e}', file=sys.stderr)
        sys.exit(1)


# ============================================================================
# Command: run
# ============================================================================

async def run_tests(cfg, execution_mode):
    """Execute the test suite.
    
    Args:
        cfg: Configuration dictionary
        execution_mode: Execution mode ('ai' or 'case')
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
    if execution_mode == 'case':
        print('🎯 Mode: Case Mode (YAML-defined test cases)')
        await run_case_mode(cfg)
    else:  # ai mode
        print('🎯 Mode: AI Mode (AI-driven test generation)')
        await run_ai_mode(cfg)


async def run_ai_mode(cfg):
    """Execute AI mode tests."""
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
        raw_concurrency = cfg.get('target', {}).get('max_concurrent_tests', 2)
        try:
            max_concurrent_tests = max(1, int(raw_concurrency))
        except (ValueError, TypeError):
            max_concurrent_tests = 2

        print(f'⚙️ Concurrency: {max_concurrent_tests}')

        parallel_mode = ParallelMode([], max_concurrent_tests=max_concurrent_tests)
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


async def run_case_mode(cfg):
    """Execute test cases defined in YAML configuration."""
    from webqa_agent.executor.case_mode import CaseMode

    # Validate LLM config
    try:
        llm_config = validate_and_build_llm_config(cfg)
    except ValueError as e:
        print(f'\n{e}', file=sys.stderr)
        sys.exit(1)

    # Get target URL
    target_url = cfg.get('target', {}).get('url', '')
    if not target_url:
        print('❌ No target URL specified in configuration', file=sys.stderr)
        sys.exit(1)

    print(f'🎯 Target URL: {target_url}')

    # Get cases
    cases = cfg.get('cases', [])
    if not cases:
        print('⚠️ No cases defined in configuration', file=sys.stderr)
        sys.exit(1)

    print(f'📋 Total cases: {len(cases)}')

    # Check Playwright browsers
    ok = await check_playwright_browsers_async()
    if not ok:
        print('\n💡 Install browsers with: playwright install chromium', file=sys.stderr)
        sys.exit(1)

    # Get browser config
    is_docker = os.getenv('DOCKER_ENV') == 'true'
    config_headless = cfg.get('browser_config', {}).get('headless', True)
    headless = True if is_docker else config_headless

    browser_config = {
        'viewport': cfg.get('browser_config', {}).get('viewport', {'width': 1280, 'height': 720}),
        'headless': headless,
        'language': cfg.get('browser_config', {}).get('language', 'en-US'),
    }

    # Get cookies if any
    cookies_value = cfg.get('browser_config', {}).get('cookies', [])
    cookies = load_cookies(cookies_value)

    # Get ignore rules if any
    ignore_rules = cfg.get('ignore_rules', {})
    if ignore_rules:
        network_count = len(ignore_rules.get('network', []))
        console_count = len(ignore_rules.get('console', []))
        print(f'🚫 Ignore rules: {network_count} network, {console_count} console')

    # Execute cases
    try:
        case_mode = CaseMode()
        results, report_path, html_report_path, result_count = await case_mode.run(
            cases=cases,
            target_url=target_url,
            llm_config=llm_config,
            browser_config=browser_config,
            cookies=cookies,
            ignore_rules=ignore_rules,
            log_cfg=cfg.get('log', {'level': 'info'}),
            report_cfg=cfg.get('report', {'language': 'en-US'}),
        )

        if result_count:
            print('📊 Results Summary:')
            print(f"   Total: {result_count.get('total', 0)}")
            print(f"   ✅ Passed: {result_count.get('passed', 0)}")
            print(f"   ⚠️ Warning: {result_count.get('warning', 0)}")
            print(f"   ❌ Failed: {result_count.get('failed', 0)}")

        if html_report_path:
            print(f'\n📄 Report: {html_report_path}')

        # Exit with appropriate code
        if result_count.get('failed', 0) > 0:
            sys.exit(1)

    except Exception:
        sys.exit(1)


def cmd_run(args):
    """Run command handler."""
    specified_mode = args.mode if hasattr(args, 'mode') else None
    config_path = args.config if hasattr(args, 'config') else None
    
    # Scenario 1: No --mode specified (default AI mode)
    if not specified_mode:
        if not config_path:
            # Auto-search for config file
            config_path = find_config_file(None)
            if config_path is None:
                print('❌ No configuration file found!')
                print()
                print('📍 Searched locations:')
                print('   - ./config.yaml')
                print('   - ./config/config.yaml')
                print()
                print('💡 Create a new configuration file:')
                print('   webqa-agent init')
                sys.exit(1)
            
            print(f'📂 Using config: {config_path}')
            cfg = load_yaml(config_path)
            
            # Validate config has test_config
            if 'test_config' not in cfg:
                print('❌ AI mode requires "test_config" field in configuration', file=sys.stderr)
                print('💡 Create an AI mode config: webqa-agent init', file=sys.stderr)
                sys.exit(1)
            
            # Execute AI mode
            asyncio.run(run_tests(cfg, execution_mode='ai'))
        else:
            # Config path specified, auto-detect mode from config structure
            print(f'📂 Using config: {config_path}')
            cfg = load_yaml(config_path)
            
            # Priority: cases > test_config
            if 'cases' in cfg:
                execution_mode = 'case'
            elif 'test_config' in cfg:
                execution_mode = 'ai'
            else:
                print('❌ Config must contain either "cases" or "test_config" field', file=sys.stderr)
                sys.exit(1)
            
            asyncio.run(run_tests(cfg, execution_mode=execution_mode))
    
    # Scenario 2: --mode specified
    else:
        # Validate mode value
        if specified_mode not in ['ai', 'case']:
            print(f'❌ Invalid mode: {specified_mode}')
            print('   Valid modes: ai, case')
            sys.exit(1)
        
        # Must specify -c when using --mode
        if not config_path:
            print(f'❌ --mode {specified_mode} requires -c/--config to specify config file path', file=sys.stderr)
            print(f'   Example: webqa-agent run --mode {specified_mode} -c config.yaml', file=sys.stderr)
            sys.exit(1)
        
        print(f'📂 Using config: {config_path}')
        cfg = load_yaml(config_path)
        
        # Validate config structure matches specified mode
        if specified_mode == 'ai':
            if 'test_config' not in cfg:
                print('❌ AI mode requires "test_config" field in configuration', file=sys.stderr)
                print('💡 Create an AI mode config: webqa-agent init', file=sys.stderr)
                sys.exit(1)
        elif specified_mode == 'case':
            if 'cases' not in cfg:
                print('❌ Case mode requires "cases" field in configuration', file=sys.stderr)
                print('💡 Create a Case mode config: webqa-agent init --mode case', file=sys.stderr)
                sys.exit(1)
        
        # Execute specified mode
        asyncio.run(run_tests(cfg, execution_mode=specified_mode))


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
  webqa-agent init                          Create AI mode config (default)
  webqa-agent init --mode case              Create Case mode config
  
  # Run tests
  webqa-agent run                           AI mode, auto-search config.yaml
  webqa-agent run -c myconfig.yaml          Auto-detect mode from config
  webqa-agent run --mode ai -c config.yaml  AI mode with validation
  webqa-agent run --mode case -c config_case.yaml  Case mode with validation
  
  # Launch web UI
  webqa-agent ui                            Start Gradio interface
  webqa-agent ui --lang zh-CN               Start with Chinese interface

Modes:
  - AI Mode: AI-driven test generation (function, UX, performance, security)
  - Case Mode: Execute predefined YAML test cases
  
Run behavior:
  - No --mode: Default AI mode, searches ./config.yaml or ./config/config.yaml
  - --mode specified: Requires -c flag, validates config structure
  - Only -c: Auto-detects mode (cases field → Case mode, otherwise AI mode)

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
        choices=['ai', 'case'],
        default='ai',
        help='Configuration mode: ai (AI-driven test generation) or case (YAML-defined test cases). Default: ai'
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

    # run command
    run_parser = subparsers.add_parser(
        'run',
        help='Run quality assurance tests',
        description='Execute web quality assurance tests. Default: AI mode with auto-searched config.'
    )
    run_parser.add_argument(
        '--mode', '-m',
        choices=['ai', 'case'],
        help='Execution mode (requires -c). Validates config structure matches mode.'
    )
    run_parser.add_argument(
        '--config', '-c',
        metavar='PATH',
        help='Config file path. Without --mode: auto-detects mode from structure.'
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
        print('   # AI Mode - AI-driven test, automatically generate and execute test cases')
        print('   webqa-agent init')
        print('   webqa-agent run')
        print()
        print('   # Case Mode - explicit mode validation')
        print('   webqa-agent init --mode case')
        print('   webqa-agent run --mode case -c config_case.yaml')
        print()
        print('   # Custom config - auto-detect mode')
        print('   webqa-agent run -c myconfig.yaml')
        sys.exit(0)

    # Dispatch to command handler
    if args.command == 'init':
        cmd_init(args)
    elif args.command == 'run':
        cmd_run(args)
    elif args.command == 'ui':
        cmd_ui(args)


if __name__ == '__main__':
    main()
