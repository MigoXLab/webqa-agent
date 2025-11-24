#!/usr/bin/env python3
"""
WebQA Agent Gradio Launch Script
"""

import sys
import os
import subprocess
import asyncio

# Add project path to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Language configuration from environment variable
def get_gradio_language():
    """Get Gradio interface language from environment variable with validation"""
    supported_languages = ["zh-CN", "en-US"]
    env_lang = os.getenv("GRADIO_LANGUAGE", "en-US")  # Default to English
    
    if env_lang in supported_languages:
        return env_lang
    else:
        print(f"⚠️  Warning: Unsupported language '{env_lang}', falling back to 'en-US'")
        return "en-US"

GRADIO_LANGUAGE = get_gradio_language()

# Import and launch Gradio application
if __name__ == "__main__":
    # Check Gradio installation and version
    try:
        import gradio
    except ImportError:
        print("❌ Error: Gradio is not installed.")
        print("Please install Gradio: uv add \"gradio>5.44.0\"")
        sys.exit(1)

    try:
        from packaging import version
        required_gradio_version = "5.44.0"
        if version.parse(gradio.__version__) <= version.parse(required_gradio_version):
            print(f"❌ Error: Gradio version {gradio.__version__} is installed, but > {required_gradio_version} is required.")
            print(f"Please upgrade Gradio: uv add \"gradio>{required_gradio_version}\"")
            sys.exit(1)
    except ImportError:
        pass  # packaging not found, skip version check

    try:
        from app_gradio.demo_gradio import create_gradio_interface, queue_manager, process_queue
        import threading
        from playwright.async_api import async_playwright, Error as PlaywrightError
        
        print("🚀 Starting WebQA Agent Gradio interface...")
        print("📱 Interface will start at http://localhost:7860")
        print(f"🌐 Interface language: {GRADIO_LANGUAGE}")
        print("💡 Tip: Set environment variable GRADIO_LANGUAGE=en-US for English or GRADIO_LANGUAGE=zh-CN for Chinese")
        print("⚠️  Note: Please ensure all dependencies are installed (uv sync)")
        print("🔍 Checking Playwright browser dependencies...")

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
            print("⚠️  Detected Playwright browsers not installed, installing automatically...")
            try:
                cmd = [sys.executable, "-m", "playwright", "install"]
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                print(result.stdout)
            except Exception as e:
                print(f"❌ Automatic installation failed: {e}\nPlease run manually: playwright install")
                sys.exit(1)

            # Verify again after installation
            ok_after = asyncio.run(_check_playwright())
            if not ok_after:
                print("❌ Playwright browsers still unavailable, please run manually: playwright install")
                sys.exit(1)
        print("✅ Playwright browsers available")
        
        # Start queue processor
        def run_queue_processor():
            """Run queue processor in background thread"""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(process_queue())
        
        queue_thread = threading.Thread(target=run_queue_processor, daemon=True)
        queue_thread.start()
        print("✅ Task queue processor started")
        
        # Create and launch Gradio application with language configuration
        app = create_gradio_interface(language=GRADIO_LANGUAGE)
        print(f"✅ Gradio interface created with language: {GRADIO_LANGUAGE}")
        
        app.launch(
            server_name="0.0.0.0",
            server_port=7860,
            share=False,
            show_error=True,
            inbrowser=True  # Auto open browser
        )
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Please ensure all dependencies are installed:")
        print("pip install -r requirements.txt")
        sys.exit(1)
    
    except Exception as e:
        print(f"❌ Startup failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
