#!/usr/bin/env python3
import argparse
import asyncio
import os
import subprocess
import sys
import traceback

import yaml
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from webqa_agent.executor import ParallelMode


def find_config_file(args_config=None):
    """Intelligently find configuration file."""
    # 1. Command line arguments have highest priority
    if args_config:
        if os.path.isfile(args_config):
            print(f"✅ Using specified config file: {args_config}")
            return args_config
        else:
            raise FileNotFoundError(f"❌ Specified config file not found: {args_config}")

    # 2. Search default locations by priority
    current_dir = os.getcwd()
    script_dir = os.path.dirname(os.path.abspath(__file__))

    default_paths = [
        os.path.join(current_dir, "config", "config.yaml"),  # config in current directory
        os.path.join(script_dir, "config", "config.yaml"),  # config in script directory
        os.path.join(current_dir, "config.yaml"),  # compatible location in current directory
        os.path.join(script_dir, "config.yaml"),  # compatible location in script directory
        "/app/config/config.yaml",  # absolute path in Docker container
    ]

    for path in default_paths:
        if os.path.isfile(path):
            print(f"✅ Auto-discovered config file: {path}")
            return path

    # If none found, provide clear error message
    print("❌ Config file not found, please check these locations:")
    for path in default_paths:
        print(f"   - {path}")
    raise FileNotFoundError("Config file does not exist")


def load_yaml(path):
    if not os.path.isfile(path):
        print(f"[ERROR] Config file not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"[ERROR] Failed to read YAML: {e}", file=sys.stderr)
        sys.exit(1)


async def check_playwright_browsers_async():
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            await browser.close()
        print("✅ Playwright browsers available (Async API startup successful)")
        return True
    except PlaywrightError as e:
        print(f"⚠️ Playwright browsers unavailable (Async API failed): {e}")
        return False
    except Exception as e:
        print(f"❌ Playwright check exception: {e}")
        return False


def check_lighthouse_installation():
    """Check if Lighthouse is properly installed."""
    # Get project root directory and current working directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    current_dir = os.getcwd()

    # Determine OS type, lighthouse is .cmd file on Windows
    is_windows = os.name == "nt"
    lighthouse_exe = "lighthouse.cmd" if is_windows else "lighthouse"

    # Possible lighthouse paths (local installation priority)
    lighthouse_paths = [
        os.path.join(current_dir, "node_modules", ".bin", lighthouse_exe),  # local installation in current directory
        os.path.join(script_dir, "node_modules", ".bin", lighthouse_exe),  # local installation in script directory
        "lighthouse",  # global installation path (fallback)
    ]

    # Add Docker path only in non-Windows environments
    if not is_windows:
        lighthouse_paths.insert(-1, os.path.join("/app", "node_modules", ".bin", "lighthouse"))

    for lighthouse_path in lighthouse_paths:
        try:
            result = subprocess.run([lighthouse_path, "--version"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version = result.stdout.strip()
                path_type = "Local installation" if "node_modules" in lighthouse_path else "Global installation"
                print(f"✅ Lighthouse installation successful, version: {version} ({path_type})")
                return True
        except subprocess.TimeoutExpired:
            continue
        except FileNotFoundError:
            continue
        except Exception:
            continue

    print("❌ Lighthouse not found, checked paths:")
    for path in lighthouse_paths:
        print(f"   - {path}")
    print("Please confirm Lighthouse is properly installed: `npm install lighthouse chrome-launcher`")
    return False


def check_nuclei_installation():
    """Check if Nuclei is properly installed."""
    try:
        # Check if nuclei command is available
        result = subprocess.run(["nuclei", "-version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            version = result.stdout.strip()
            print(f"✅ Nuclei installation successful, version: {version}")
            return True
        else:
            print(f"⚠️ Nuclei command execution failed: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print("❌ Nuclei check timeout")
        return False
    except FileNotFoundError:
        print("❌ Nuclei not installed or not in PATH")
        return False
    except Exception as e:
        print(f"❌ Nuclei check exception: {e}")
        return False


def validate_and_build_llm_config(cfg):
    """Validate and build LLM configuration, environment variables take priority over config file."""
    # Read from config file
    llm_cfg_raw = cfg.get("llm_config", {})

    # Environment variables take priority over config file
    api_key = os.getenv("OPENAI_API_KEY") or llm_cfg_raw.get("api_key", "")
    base_url = os.getenv("OPENAI_BASE_URL") or llm_cfg_raw.get("base_url", "")
    model = llm_cfg_raw.get("model", "gpt-4o-mini")
    # Sampling configuration: default temperature is 0.1; top_p not set by default
    temperature = llm_cfg_raw.get("temperature", 0.1)
    top_p = llm_cfg_raw.get("top_p")

    # Validate required fields
    if not api_key:
        raise ValueError(
            "❌ LLM API Key not configured! Please set one of the following:\n"
            "   - Environment variable: OPENAI_API_KEY\n"
            "   - Config file: llm_config.api_key"
        )

    if not base_url:
        print("⚠️  base_url not set, will use OpenAI default address")
        base_url = "https://api.openai.com/v1"

    llm_config = {
        "api": "openai",
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
    }
    if top_p is not None:
        llm_config["top_p"] = top_p

    # Show configuration source (hide sensitive information)
    api_key_masked = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
    env_api_key = bool(os.getenv("OPENAI_API_KEY"))
    env_base_url = bool(os.getenv("OPENAI_BASE_URL"))

    print("✅ LLM configuration validation successful:")
    print(f"   - API Key: {api_key_masked} ({'Environment variable' if env_api_key else 'Config file'})")
    print(f"   - Base URL: {base_url} ({'Environment variable' if env_base_url else 'Config file/Default'})")
    print(f"   - Model: {model}")
    print(f"   - Temperature: {temperature}")
    if top_p is not None:
        print(f"   - Top_p: {top_p}")

    return llm_config


def build_test_configurations(cfg, cookies=None):
    tests = []
    tconf = cfg.get("test_config", {})

    # Docker environment detection: force headless mode
    is_docker = os.getenv("DOCKER_ENV") == "true"
    config_headless = cfg.get("browser_config", {}).get("headless", True)

    if is_docker and not config_headless:
        print("⚠️  Docker environment detected, forcing headless mode")
        headless = True
    else:
        headless = config_headless

    base_browser = {
        "viewport": cfg.get("browser_config", {}).get("viewport", {"width": 1280, "height": 720}),
        "headless": headless,
    }

    # function test
    if tconf.get("function_test", {}).get("enabled"):

        if tconf["function_test"].get("type") == "ai":
            tests.append(
                {
                    "test_type": "ui_agent_langgraph",
                    "enabled": True,
                    "browser_config": base_browser,
                    "test_specific_config": {
                        "cookies": cookies,
                        "business_objectives": tconf["function_test"].get("business_objectives", ""),
                        "dynamic_step_generation": tconf["function_test"].get("dynamic_step_generation", {}),
                    },
                }
            )
        else:
            tests += [
                {
                    "test_type": "basic_test",
                    "enabled": True,
                    "browser_config": base_browser,
                    "test_specific_config": {},
                }
            ]

    # ux test
    if tconf.get("ux_test", {}).get("enabled"):
        tests.append(
            {
                "test_type": "ux_test",
                "enabled": True,
                "browser_config": base_browser,
                "test_specific_config": {},
            }
        )
  
    # performance test
    if tconf.get("performance_test", {}).get("enabled"):
        tests.append(
            {
                "test_type": "performance",
                "enabled": True,
                "browser_config": base_browser,
                "test_specific_config": {},
            }
        )

    # security test
    if tconf.get("security_test", {}).get("enabled"):
        tests.append(
            {
                "test_type": "security",
                "enabled": True,
                "browser_config": base_browser,
                "test_specific_config": {},
            }
        )

    return tests


async def run_tests(cfg):
    # 0. Display runtime environment information
    is_docker = os.getenv("DOCKER_ENV") == "true"
    print(f"🏃 Runtime environment: {'Docker container' if is_docker else 'Local environment'}")
    if is_docker:
        print("🐳 Docker mode: automatically enable headless browser")

    # 1. Check required tools based on configuration
    tconf = cfg.get("test_config", {})

    # Display enabled test types
    enabled_tests = []
    if tconf.get("function_test", {}).get("enabled"):
        test_type = tconf.get("function_test", {}).get("type", "default")
        enabled_tests.append(f"Function Test ({test_type})")
    if tconf.get("ux_test", {}).get("enabled"):
        enabled_tests.append("User Experience Test")
    if tconf.get("performance_test", {}).get("enabled"):
        enabled_tests.append("Performance Test")
    if tconf.get("security_test", {}).get("enabled"):
        enabled_tests.append("Security Test")

    if enabled_tests:
        print(f"📋 Enabled test types: {', '.join(enabled_tests)}")
        print("🔧 Checking required tools based on configuration...")
    else:
        print("⚠️  No test types enabled, please check configuration file")
        sys.exit(1)

    # Check if browser is needed (most tests require it)
    needs_browser = any(
        [
            tconf.get("function_test", {}).get("enabled"),
            tconf.get("ux_test", {}).get("enabled"),
            tconf.get("performance_test", {}).get("enabled"),
            tconf.get("security_test", {}).get("enabled"),
        ]
    )

    if needs_browser:
        print("🔍 Checking Playwright browsers...")
        ok = await check_playwright_browsers_async()
        if not ok:
            print("Please manually run: `playwright install` to install browser binaries, then retry.", file=sys.stderr)
            sys.exit(1)

    # Check if Lighthouse is needed (performance test)
    if tconf.get("performance_test", {}).get("enabled"):
        print("🔍 Checking Lighthouse installation...")
        lighthouse_ok = check_lighthouse_installation()
        if not lighthouse_ok:
            print("Please confirm Lighthouse is properly installed: `npm install lighthouse chrome-launcher`", file=sys.stderr)
            sys.exit(1)

    # Check if Nuclei is needed (security test)
    if tconf.get("security_test", {}).get("enabled"):
        print("🔍 Checking Nuclei installation...")
        nuclei_ok = check_nuclei_installation()
        if not nuclei_ok:
            print("Please confirm Nuclei is properly installed and in PATH", file=sys.stderr)
            sys.exit(1)

    # Validate and build LLM configuration
    try:
        llm_config = validate_and_build_llm_config(cfg)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    # Build test_configurations
    cookies = []
    test_configurations = build_test_configurations(cfg, cookies=cookies)

    target_url = cfg.get("target", {}).get("url", "")

    # Call executor
    try:
        # Read concurrency from config (default 2), allow users to specify in config.target.max_concurrent_tests
        raw_concurrency = cfg.get("target", {}).get("max_concurrent_tests", 2)
        try:
            max_concurrent_tests = int(raw_concurrency)
            if max_concurrent_tests < 1:
                raise ValueError
        except Exception:
            print(f"⚠️  Invalid concurrency setting: {raw_concurrency}, fallback to 2")
            max_concurrent_tests = 2

        print(f"⚙️ Concurrency: {max_concurrent_tests}")

        parallel_mode = ParallelMode([], max_concurrent_tests=max_concurrent_tests)
        results, report_path, html_report_path, result_count = await parallel_mode.run(
            url=target_url, llm_config=llm_config, test_configurations=test_configurations,
            log_cfg=cfg.get("log", {"level": "info"}),
            report_cfg=cfg.get("report", {"language": "en-US"})
        )
        if result_count:
            print(f"🔢 Total evaluations: {result_count.get('total', 0)}")
            print(f"✅ Passed: {result_count.get('passed', 0)}")
            print(f"❌ Failed: {result_count.get('failed', 0)}")

        if html_report_path:
            print("HTML report path: ", html_report_path)
        else:
            print("HTML report generation failed")
    except Exception:
        print("Test execution failed, stack trace:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(description="WebQA Agent Test Entry Point")
    parser.add_argument("--config", "-c", help="YAML configuration file path (optional, default auto-search config/config.yaml)")
    return parser.parse_args()


def main():
    args = parse_args()

    # Intelligently find configuration file
    try:
        config_path = find_config_file(args.config)
        cfg = load_yaml(config_path)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    # Run tests
    asyncio.run(run_tests(cfg))


if __name__ == "__main__":
    main()
