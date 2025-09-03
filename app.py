#!/usr/bin/env python3
"""
WebQA Agent Gradio启动脚本
"""

import sys
import os
import subprocess
import asyncio

# 添加项目路径到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入并启动Gradio应用
if __name__ == "__main__":
    try:
        from demo_gradio import create_gradio_interface, queue_manager, process_queue
        import threading
        from playwright.async_api import async_playwright, Error as PlaywrightError
        
        print("🚀 启动WebQA Agent Gradio界面...")
        print("📱 界面将在 http://localhost:7860 启动")
        print("⚠️  注意：请确保已安装所有依赖包 (pip install -r requirements.txt)")
        print("🔍 正在检查 Playwright 浏览器依赖...")

        async def _check_playwright():
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    await browser.close()
                return True
            except PlaywrightError:
                return False
            except Exception:
                return False

        ok = asyncio.run(_check_playwright())
        if not ok:
            print("⚠️  检测到 Playwright 浏览器未安装，正在自动安装...")
            try:
                cmd = [sys.executable, "-m", "playwright", "install"]
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                print(result.stdout)
            except Exception as e:
                print(f"❌ 自动安装失败：{e}\n请手动执行：playwright install")
                sys.exit(1)

            # 安装后再次校验
            ok_after = asyncio.run(_check_playwright())
            if not ok_after:
                print("❌ Playwright 浏览器仍不可用，请手动执行：playwright install")
                sys.exit(1)
        print("✅ Playwright 浏览器可用")
        
        # 启动队列处理器
        def run_queue_processor():
            """在后台线程中运行队列处理器"""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(process_queue())
        
        queue_thread = threading.Thread(target=run_queue_processor, daemon=True)
        queue_thread.start()
        print("✅ 任务队列处理器已启动")
        
        # 创建并启动Gradio应用
        app = create_gradio_interface()
        print("✅ Gradio界面已创建")
        
        app.launch(
            server_name="0.0.0.0",
            server_port=7860,
            share=False,
            show_error=True,
            inbrowser=True  # 自动打开浏览器
        )
        
    except ImportError as e:
        print(f"❌ 导入错误: {e}")
        print("请确保已安装所有依赖包:")
        print("pip install -r requirements.txt")
        sys.exit(1)
    
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
