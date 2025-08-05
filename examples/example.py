import asyncio
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from webqa_agent.executor import ParallelMode

async def example():
    llm_config = {
        "api": "openai",
        "model": "gpt-4o-mini",
        "api_key": os.getenv("OPENAI_API_KEY"),
        "base_url": os.getenv("OPENAI_BASE_URL")
    }
    user_selection = {
        "function_test_type": "ai",  # "default" or "ai"
        "ui_test_enabled": False,
        "performance_test_enabled": False,
        "security_test_enabled": True,
    }

    test_configurations = []

    # ---------- Function tests ----------
    if user_selection["function_test_type"]:
        if user_selection["function_test_type"] == "ai":
            test_configurations.append({
                "test_type": "ui_agent_langgraph",
                "test_name": "智能UI功能测试",
                "enabled": True,
                "browser_config": {
                    "viewport": {"width": 1280, "height": 720},
                    "headless": False
                },
                "test_specific_config": {
                    "business_objectives": "测试页面导航栏功能，只生成1个case",
                    # "cookies": cookies
                }
            })
        else:  # default function tests
                test_configurations.append({
                    "test_type": "button_test",
                    "test_name": "按钮功能测试",
                    "enabled": True,
                    "browser_config": {
                        "viewport": {"width": 1280, "height": 720},
                        "headless": False
                    },
                    "test_specific_config": {}
                })
                test_configurations.append({
                    "test_type": "web_basic_check",
                    "test_name": "技术健康度检查",
                    "enabled": True,
                    "browser_config": {
                        "viewport": {"width": 1280, "height": 720},
                        "headless": False
                    },
                    "test_specific_config": {}
                })

    # ---------- UI tests ----------
    if user_selection["ui_test_enabled"]:
        test_configurations.append({
            "test_type": "ux_test",
            "test_name": "用户体验评估",
            "enabled": True,
            "browser_config": {
                "viewport": {"width": 1366, "height": 768},
                "headless": False
            },
            "test_specific_config": {}
        })

    # ---------- Performance tests ----------
    if user_selection["performance_test_enabled"]:
        test_configurations.append({
            "test_type": "lighthouse",
            "test_name": "前端性能基准测试",
            "enabled": True,
            "browser_config": {
                "viewport": {"width": 1920, "height": 1080},
            },
            "test_specific_config": {}
        })

    # ---------- Security tests (optional) ----------
    if user_selection["security_test_enabled"]:
        test_configurations.append({
            "test_type": "security",
            "test_name": "安全基线检查",
            "enabled": True,
            "browser_config": {
                "browser_type": "chromium",
                "viewport": {"width": 1280, "height": 800},
                "headless": True  
            },
            "test_specific_config": {
                "include_severity_scans": True
            }
        })

    # Create parallel mode
    parallel_mode = ParallelMode([], max_concurrent_tests=4)
    
    try:
        await parallel_mode.run(
            url="https://baidu.com/",
            llm_config=llm_config,
            test_configurations=test_configurations
        )

        
    except Exception as e:
        print(f"自定义测试执行失败: {e}")


async def main():
    """Main function - Run all examples"""

    try:
        await example()
        
    except Exception as e:
        print(f"示例执行出错: {e}")


if __name__ == "__main__":
    # Run examples
    asyncio.run(main()) 