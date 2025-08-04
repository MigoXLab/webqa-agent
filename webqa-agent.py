#!/usr/bin/env python3
from datetime import datetime
import argparse
import asyncio
import os
import sys
import yaml
import json
import traceback
from pathlib import Path

from playwright.async_api import async_playwright, Error as PlaywrightError

from webqa_agent.executor import ParallelMode


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


def build_test_configurations(cfg, cookies=None):
    tests = []
    tconf = cfg.get("test_config", {})

    base_browser = {
        "browser_type": cfg.get("browser_config", {}).get("type", "chromium"),
        "viewport": cfg.get("browser_config", {}).get("viewport", {"width": 1920, "height": 1080}),
        "headless": cfg.get("browser_config", {}).get("headless", False),
    }

    # function test
    if tconf.get("function_test", {}).get("enabled"):
        if tconf["function_test"].get("type") == "ai":
            tests.append({
                "test_type": "ui_agent_langgraph",
                "test_name": "智能功能测试",
                "enabled": True,
                "browser_config": base_browser,
                "test_specific_config": {"cookies": cookies},
            })
        else:
            tests += [
                {
                    "test_type": "button_test",
                    "test_name": "按钮测试",
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
                }
            ]

    # ui test
    if tconf.get("ui_test", {}).get("enabled"):
        tests.append({
            "test_type": "ux_test",
            "test_name": "用户体验测试",
            "enabled": True,
            "browser_config": base_browser,
            "test_specific_config": {},
        })

    # performance test
    if tconf.get("performance_test", {}).get("enabled"):
        tests.append({
            "test_type": "performance",
            "test_name": "性能测试",
            "enabled": True,
            "browser_config": base_browser,
            "test_specific_config": {},
        })

    # security test
    if tconf.get("security_test", {}).get("enabled"):
        tests.append({
            "test_type": "security",
            "test_name": "安全测试",
            "enabled": True,
            "browser_config": base_browser,
            "test_specific_config": {},
        })

    return tests


async def run_tests(cfg):
    # 1. 检查 Playwright 浏览器
    ok = await check_playwright_browsers_async()
    if not ok:
        print("请手动执行：`playwright install` 来安装浏览器二进制，然后重试。", file=sys.stderr)
        sys.exit(1)

    # 2. 构造 test_configurations
    cookies = None  # 如果需要可从 cfg 或 SSO 获取
    test_configurations = build_test_configurations(cfg, cookies=cookies)

    # 3. llm_config
    llm_cfg_raw = cfg.get("llm_config", {})
    llm_config = {
        "api": "openai",
        "model": llm_cfg_raw.get("model", "gpt-4o-mini"),
        "api_key": llm_cfg_raw.get("api_key", ""),
        "base_url": llm_cfg_raw.get("base_url", ""),
    }

    target_url = cfg.get("target", {}).get("url", "")

    # 4. 调用执行器
    try:
        parallel_mode = ParallelMode([], max_concurrent_tests=4)  # 依据实际调整
        results, report_path, html_report_path = await parallel_mode.run(
            url=target_url,
            llm_config=llm_config,
            test_configurations=test_configurations
        )
        return {
            "target_url": target_url,
            "llm_config": llm_config,
            "test_configurations": test_configurations,
            "results": results,
            "report_path": report_path,
            "html_report_path": html_report_path,
        }
    except Exception:
        print("测试执行失败，堆栈如下：", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(description="WebQA Agent 测试入口")
    parser.add_argument("--config", "-c", required=True, help="YAML 配置文件路径")
    parser.add_argument("--output", "-o", default="webqa-agent-output.json", help="结果输出 JSON 文件")
    return parser.parse_args()


def main():
    args = parse_args()
    print(f"[INFO] 使用配置文件: {args.config}")
    cfg = load_yaml(args.config)
    result = asyncio.run(run_tests(cfg))

    # 确保 results 目录存在
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    # 生成带时间戳的文件名
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = args.output if args.output != "webqa-agent-output.json" else f"webqa-agent-output_{ts}.json"
    out_path = results_dir / filename

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"✅ 结果已写入: {out_path}")
    except Exception as e:
        print(f"[ERROR] 写输出文件失败: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
