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
    """智能查找配置文件."""
    # 1. 命令行参数优先级最高
    if args_config:
        if os.path.isfile(args_config):
            print(f"✅ 使用指定配置文件: {args_config}")
            return args_config
        else:
            raise FileNotFoundError(f"❌ 指定的配置文件不存在: {args_config}")

    # 2. 按优先级搜索默认位置
    current_dir = os.getcwd()
    script_dir = os.path.dirname(os.path.abspath(__file__))

    default_paths = [
        os.path.join(current_dir, "config", "config.yaml"),  # 当前目录下的config
        os.path.join(script_dir, "config", "config.yaml"),  # 脚本目录下的config
        os.path.join(current_dir, "config.yaml"),  # 当前目录兼容位置
        os.path.join(script_dir, "config.yaml"),  # 脚本目录兼容位置
        "/app/config/config.yaml",  # Docker容器内绝对路径
    ]

    for path in default_paths:
        if os.path.isfile(path):
            print(f"✅ 自动发现配置文件: {path}")
            return path

    # 如果都找不到，给出清晰的错误信息
    print("❌ 未找到配置文件，请检查以下位置:")
    for path in default_paths:
        print(f"   - {path}")
    raise FileNotFoundError("配置文件不存在")


def load_yaml(path):
    if not os.path.isfile(path):
        print(f"[ERROR] 配置文件不存在: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"[ERROR] 读取 YAML 失败: {e}", file=sys.stderr)
        sys.exit(1)


async def check_playwright_browsers_async():
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            await browser.close()
        print("✅ Playwright 浏览器可用（Async API 启动成功）")
        return True
    except PlaywrightError as e:
        print(f"⚠️ Playwright 浏览器不可用（Async API 失败）：{e}")
        return False
    except Exception as e:
        print(f"❌ 检查 Playwright 异常：{e}")
        return False


def check_lighthouse_installation():
    """检查 Lighthouse 是否正确安装."""
    # 获取项目根目录和当前工作目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    current_dir = os.getcwd()

    # 判断操作系统类型，Windows下lighthouse是.cmd文件
    is_windows = os.name == "nt"
    lighthouse_exe = "lighthouse.cmd" if is_windows else "lighthouse"

    # 可能的lighthouse路径（本地安装优先）
    lighthouse_paths = [
        os.path.join(current_dir, "node_modules", ".bin", lighthouse_exe),  # 当前目录本地安装
        os.path.join(script_dir, "node_modules", ".bin", lighthouse_exe),  # 脚本目录本地安装
        "lighthouse",  # 全局安装路径（兜底）
    ]

    # 只在非Windows环境下添加Docker路径
    if not is_windows:
        lighthouse_paths.insert(-1, os.path.join("/app", "node_modules", ".bin", "lighthouse"))

    for lighthouse_path in lighthouse_paths:
        try:
            result = subprocess.run([lighthouse_path, "--version"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version = result.stdout.strip()
                path_type = "本地安装" if "node_modules" in lighthouse_path else "全局安装"
                print(f"✅ Lighthouse 安装成功，版本：{version} ({path_type})")
                return True
        except subprocess.TimeoutExpired:
            continue
        except FileNotFoundError:
            continue
        except Exception:
            continue

    print("❌ Lighthouse 未找到，已检查路径:")
    for path in lighthouse_paths:
        print(f"   - {path}")
    print("请确认 Lighthouse 已正确安装：`npm install lighthouse chrome-launcher`")
    return False


def check_nuclei_installation():
    """检查 Nuclei 是否正确安装."""
    try:
        # 检查 nuclei 命令是否可用
        result = subprocess.run(["nuclei", "-version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            version = result.stdout.strip()
            print(f"✅ Nuclei 安装成功，版本：{version}")
            return True
        else:
            print(f"⚠️ Nuclei 命令执行失败：{result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print("❌ Nuclei 检查超时")
        return False
    except FileNotFoundError:
        print("❌ Nuclei 未安装或不在 PATH 中")
        return False
    except Exception as e:
        print(f"❌ 检查 Nuclei 异常：{e}")
        return False


def validate_and_build_llm_config(cfg):
    """验证并构建LLM配置，环境变量优先于配置文件."""
    # 从配置文件读取
    llm_cfg_raw = cfg.get("llm_config", {})

    # 环境变量优先于配置文件
    api_key = os.getenv("OPENAI_API_KEY") or llm_cfg_raw.get("api_key", "")
    base_url = os.getenv("OPENAI_BASE_URL") or llm_cfg_raw.get("base_url", "")
    model = llm_cfg_raw.get("model", "gpt-4o-mini")
    # 采样配置：默认 temperature 为 0.1；top_p 默认不设置
    temperature = llm_cfg_raw.get("temperature", 0.1)
    top_p = llm_cfg_raw.get("top_p")

    # 验证必填字段
    if not api_key:
        raise ValueError(
            "❌ LLM API Key 未配置！请设置以下之一：\n"
            "   - 环境变量: OPENAI_API_KEY\n"
            "   - 配置文件: llm_config.api_key"
        )

    if not base_url:
        print("⚠️  未设置 base_url，将使用 OpenAI 默认地址")
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

    # 显示配置来源（隐藏敏感信息）
    api_key_masked = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
    env_api_key = bool(os.getenv("OPENAI_API_KEY"))
    env_base_url = bool(os.getenv("OPENAI_BASE_URL"))

    print("✅ LLM配置验证成功:")
    print(f"   - API Key: {api_key_masked} ({'环境变量' if env_api_key else '配置文件'})")
    print(f"   - Base URL: {base_url} ({'环境变量' if env_base_url else '配置文件/默认'})")
    print(f"   - Model: {model}")
    print(f"   - Temperature: {temperature}")
    if top_p is not None:
        print(f"   - Top_p: {top_p}")

    return llm_config


def build_test_configurations(cfg, cookies=None):
    tests = []
    tconf = cfg.get("test_config", {})

    # Docker环境检测：强制headless模式
    is_docker = os.getenv("DOCKER_ENV") == "true"
    config_headless = cfg.get("browser_config", {}).get("headless", True)

    if is_docker and not config_headless:
        print("⚠️  检测到Docker环境，强制启用headless模式")
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
                    "test_name": "智能功能测试",
                    "enabled": True,
                    "browser_config": base_browser,
                    "test_specific_config": {
                        "cookies": cookies,
                        "business_objectives": tconf["function_test"].get("business_objectives", ""),
                    },
                }
            )
        else:
            tests += [
                {
                    "test_type": "button_test",
                    "test_name": "遍历测试",
                    "enabled": True,
                    "browser_config": base_browser,
                    "test_specific_config": {},
                },
                {
                    "test_type": "web_basic_check",
                    "test_name": "技术健康度检查",
                    "enabled": True,
                    "browser_config": base_browser,
                    "test_specific_config": {},
                },
            ]

    # ux test
    if tconf.get("ux_test", {}).get("enabled"):
        tests.append(
            {
                "test_type": "ux_test",
                "test_name": "用户体验测试",
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
                "test_name": "性能测试",
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
                "test_name": "安全测试",
                "enabled": True,
                "browser_config": base_browser,
                "test_specific_config": {},
            }
        )

    return tests


async def run_tests(cfg):
    # 0. 显示运行环境信息
    is_docker = os.getenv("DOCKER_ENV") == "true"
    print(f"🏃 运行环境: {'Docker容器' if is_docker else '本地环境'}")
    if is_docker:
        print("🐳 Docker模式：自动启用headless浏览器")

    # 1. 根据配置检查所需工具
    tconf = cfg.get("test_config", {})

    # 显示启用的测试类型
    enabled_tests = []
    if tconf.get("function_test", {}).get("enabled"):
        test_type = tconf.get("function_test", {}).get("type", "default")
        enabled_tests.append(f"功能测试({test_type})")
    if tconf.get("ux_test", {}).get("enabled"):
        enabled_tests.append("用户体验测试")
    if tconf.get("performance_test", {}).get("enabled"):
        enabled_tests.append("性能测试")
    if tconf.get("security_test", {}).get("enabled"):
        enabled_tests.append("安全测试")

    if enabled_tests:
        print(f"📋 启用的测试类型: {', '.join(enabled_tests)}")
        print("🔧 正在根据配置检查所需工具...")
    else:
        print("⚠️  未启用任何测试类型，请检查配置文件")
        sys.exit(1)

    # 检查是否需要浏览器（大部分测试都需要）
    needs_browser = any(
        [
            tconf.get("function_test", {}).get("enabled"),
            tconf.get("ux_test", {}).get("enabled"),
            tconf.get("performance_test", {}).get("enabled"),
            tconf.get("security_test", {}).get("enabled"),
        ]
    )

    if needs_browser:
        print("🔍 检查 Playwright 浏览器...")
        ok = await check_playwright_browsers_async()
        if not ok:
            print("请手动执行：`playwright install` 来安装浏览器二进制，然后重试。", file=sys.stderr)
            sys.exit(1)

    # 检查是否需要 Lighthouse（性能测试）
    if tconf.get("performance_test", {}).get("enabled"):
        print("🔍 检查 Lighthouse 安装...")
        lighthouse_ok = check_lighthouse_installation()
        if not lighthouse_ok:
            print("请确认 Lighthouse 已正确安装：`npm install lighthouse chrome-launcher`", file=sys.stderr)
            sys.exit(1)

    # 检查是否需要 Nuclei（安全测试）
    if tconf.get("security_test", {}).get("enabled"):
        print("🔍 检查 Nuclei 安装...")
        nuclei_ok = check_nuclei_installation()
        if not nuclei_ok:
            print("请确认 Nuclei 已正确安装并在 PATH 中", file=sys.stderr)
            sys.exit(1)

    # 验证和构建 LLM 配置
    try:
        llm_config = validate_and_build_llm_config(cfg)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    # 构造 test_configurations
    cookies = []
    test_configurations = build_test_configurations(cfg, cookies=cookies)

    target_url = cfg.get("target", {}).get("url", "")

    # 调用执行器
    try:
        # 从配置读取并行度（默认2），允许用户在 config.target.max_concurrent_tests 指定
        raw_concurrency = cfg.get("target", {}).get("max_concurrent_tests", 2)
        try:
            max_concurrent_tests = int(raw_concurrency)
            if max_concurrent_tests < 1:
                raise ValueError
        except Exception:
            print(f"⚠️  无效的并行设置: {raw_concurrency}，已回退为 2")
            max_concurrent_tests = 2

        print(f"⚙️ 并行度: {max_concurrent_tests}")

        parallel_mode = ParallelMode([], max_concurrent_tests=max_concurrent_tests)
        results, report_path, html_report_path = await parallel_mode.run(
            url=target_url, llm_config=llm_config, test_configurations=test_configurations,
            log_cfg=cfg.get("log", {"level": "info"})
        )
        if html_report_path:
            print("html报告路径: ", html_report_path)
        else:
            print("html报告生成失败")
    except Exception:
        print("测试执行失败，堆栈如下：", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(description="WebQA Agent 测试入口")
    parser.add_argument("--config", "-c", help="YAML 配置文件路径 (可选，默认自动搜索 config/config.yaml)")
    return parser.parse_args()


def main():
    args = parse_args()

    # 智能查找配置文件
    try:
        config_path = find_config_file(args.config)
        cfg = load_yaml(config_path)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    # 运行测试
    asyncio.run(run_tests(cfg))


if __name__ == "__main__":
    main()
