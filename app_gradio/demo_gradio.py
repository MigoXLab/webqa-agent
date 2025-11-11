import asyncio
import json
import os
import tempfile
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Dict, Any, Optional, Tuple
import queue
import html as html_lib
from urllib.parse import quote as url_quote
import re

import gradio as gr
import yaml

# Import project modules
from webqa_agent.executor import ParallelMode

# Simple submission history (in-memory storage for current session only)
submission_history: list = []

# Load i18n data
def load_i18n() -> Dict[str, Dict]:
    """Load internationalization data from JSON file"""
    i18n_path = Path(__file__).parent / "gradio_i18n.json"
    try:
        with open(i18n_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to load i18n file: {e}")
        return {"zh-CN": {}, "en-US": {}}

I18N_DATA = load_i18n()

def get_text(lang: str, key: str, **kwargs):
    """Get localized text by key"""
    keys = key.split('.')
    data = I18N_DATA.get(lang, I18N_DATA.get("zh-CN", {}))
    
    for k in keys:
        if isinstance(data, dict) and k in data:
            data = data[k]
        else:
            return key  # Return key if not found
    
    if isinstance(data, str):
        # Support simple string formatting
        try:
            return data.format(**kwargs)
        except (KeyError, ValueError):
            return data
    elif isinstance(data, list):
        # Return list as-is for components that expect lists
        return data
    return key


class QueueManager:
    """Task queue manager to ensure only one task executes at a time"""
    
    def __init__(self):
        self.current_task: Optional[str] = None
        self.task_queue: queue.Queue = queue.Queue()
        self.task_status: Dict[str, Dict] = {}
        self.lock = Lock()
    
    def add_task(self, task_id: str, user_info: Dict) -> int:
        """Add task to queue, return queue position"""
        with self.lock:
            self.task_status[task_id] = {
                "status": "queued",
                "created_at": datetime.now(),
                "user_info": user_info,
                "result": None,
                "error": None
            }
            self.task_queue.put(task_id)
            return self.task_queue.qsize()
    
    def get_next_task(self) -> Optional[str]:
        """Get next task to execute"""
        with self.lock:
            if self.current_task is None and not self.task_queue.empty():
                task_id = self.task_queue.get()
                self.current_task = task_id
                self.task_status[task_id]["status"] = "running"
                self.task_status[task_id]["started_at"] = datetime.now()
                return task_id
            return None
    
    def complete_task(self, task_id: str, result: Any = None, error: Any = None):
        """Mark task as completed"""
        with self.lock:
            if task_id in self.task_status:
                self.task_status[task_id]["status"] = "completed" if result else "failed"
                self.task_status[task_id]["completed_at"] = datetime.now()
                self.task_status[task_id]["result"] = result
                self.task_status[task_id]["error"] = error
            if self.current_task == task_id:
                self.current_task = None
    
    def get_queue_position(self, task_id: str) -> int:
        """Get task position in queue"""
        with self.lock:
            if task_id == self.current_task:
                return 0  # Currently executing
            
            queue_list = list(self.task_queue.queue)
            try:
                return queue_list.index(task_id) + 1
            except ValueError:
                return -1  # Task not in queue
    
    def get_task_status(self, task_id: str) -> Dict:
        """Get task status"""
        with self.lock:
            return self.task_status.get(task_id, {"status": "not_found"})


# Global queue manager
queue_manager = QueueManager()


def validate_llm_config(api_key: str, base_url: str, model: str, lang: str = "zh-CN") -> Tuple[bool, str]:
    """Validate LLM configuration"""
    if not api_key.strip():
        return False, get_text(lang, "messages.error_api_key_empty")
    
    if not base_url.strip():
        return False, get_text(lang, "messages.error_base_url_empty")
    
    if not model.strip():
        return False, get_text(lang, "messages.error_model_empty")
    
    # Simple URL format check
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        return False, get_text(lang, "messages.error_base_url_format")
    
    return True, get_text(lang, "messages.config_valid")


def create_config_dict(
    url: str,
    function_test_enabled: bool,
    function_test_type: str,
    business_objectives: str,
    ux_test_enabled: bool,
    performance_test_enabled: bool,
    security_test_enabled: bool,
    api_key: str,
    base_url: str,
    model: str,
    report_language: str = "zh-CN"
) -> Dict[str, Any]:
    """Create configuration dictionary"""
    
    final_business_objectives = business_objectives.strip()
    default_constraint = get_text(report_language, "config.default_business_objectives")
    
    if final_business_objectives:
        separator = ","
        final_business_objectives = f"{final_business_objectives}{separator}{default_constraint}"
    else:
        final_business_objectives = default_constraint
    
    config = {
        "target": {
            "url": url,
            "description": ""
        },
        "test_config": {
            "function_test": {
                "enabled": function_test_enabled,
                "type": function_test_type,
                "business_objectives": final_business_objectives
            },
            "ux_test": {
                "enabled": ux_test_enabled
            },
            "performance_test": {
                "enabled": performance_test_enabled
            },
            "security_test": {
                "enabled": security_test_enabled
            }
        },
        "llm_config": {
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
            "temperature": 0.1
        },
        "report": {
            "language": report_language
        },
        "browser_config": {
            "viewport": {"width": 1280, "height": 720},
            "headless": True,
            "language": "zh-CN",
            "cookies": [],
            "save_screenshots": False  # Always not save screenshots in Gradio demo
        }
    }
    
    return config


def build_test_configurations(config: Dict[str, Any]) -> list:
    """Build test configuration list based on config"""
    tests = []
    tconf = config.get("test_config", {})
    
    base_browser = {
        "viewport": config.get("browser_config", {}).get("viewport", {"width": 1280, "height": 720}),
        "headless": True,  # Force headless for web interface
    }
    
    # function test
    if tconf.get("function_test", {}).get("enabled"):
        if tconf["function_test"].get("type") == "ai":
            tests.append({
                "test_type": "ui_agent_langgraph",
                "enabled": True,
                "browser_config": base_browser,
                "test_specific_config": {
                    "cookies": [],
                    "business_objectives": tconf["function_test"].get("business_objectives", ""),
                },
            })
        else:
            tests += [
                {
                    "test_type": "basic_test",
                    "enabled": True,
                    "browser_config": base_browser,
                    "test_specific_config": {},
                },
            ]
    
    # ux test
    if tconf.get("ux_test", {}).get("enabled"):
        tests.append({
            "test_type": "ux_test",
            "enabled": True,
            "browser_config": base_browser,
            "test_specific_config": {},
        })
    
    # performance test
    if tconf.get("performance_test", {}).get("enabled"):
        tests.append({
            "test_type": "performance",
            "enabled": True,
            "browser_config": base_browser,
            "test_specific_config": {},
        })
    
    # security test
    if tconf.get("security_test", {}).get("enabled"):
        tests.append({
            "test_type": "security",
            "enabled": True,
            "browser_config": base_browser,
            "test_specific_config": {},
        })
    
    return tests


async def run_webqa_test(config: Dict[str, Any], lang: str = "zh-CN") -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Run WebQA test"""
    try:
        # Configure screenshot saving behavior
        from webqa_agent.actions.action_handler import ActionHandler
        save_screenshots = config.get("browser_config", {}).get("save_screenshots", False)
        ActionHandler.set_screenshot_config(save_screenshots=save_screenshots)

        # Validate LLM configuration
        llm_config = {
            "api": "openai",
            "model": config["llm_config"]["model"],
            "api_key": config["llm_config"]["api_key"],
            "base_url": config["llm_config"]["base_url"],
            "temperature": config["llm_config"]["temperature"],
        }
        
        # Build test configurations
        test_configurations = build_test_configurations(config)
        
        if not test_configurations:
            return None, None, get_text(lang, "messages.no_test_types_enabled")
        
        target_url = config["target"]["url"]
        max_concurrent_tests = 1
    
        # Execute tests
        parallel_mode = ParallelMode([], max_concurrent_tests=max_concurrent_tests)
        results, report_path, html_report_path, result_count = await parallel_mode.run(
            url=target_url,
            llm_config=llm_config,
            test_configurations=test_configurations,
            log_cfg=config.get("log", {"level": "info"}),
            report_cfg=config.get("report", {"language": lang})
        )
        
        return html_report_path, report_path, None
        
    except Exception as e:
        error_msg = f"{get_text(lang, 'messages.test_execution_failed')}: {str(e)}\n{traceback.format_exc()}"
        return None, None, error_msg


def submit_test(
    url: str,
    function_test_enabled: bool,
    function_test_type: str,
    business_objectives: str,
    ux_test_enabled: bool,
    performance_test_enabled: bool,
    security_test_enabled: bool,
    api_key: str,
    base_url: str,
    model: str,
    interface_language: str = "zh-CN"
) -> Tuple[str, str, bool]:
    """Submit test task, return (status message, task ID, success flag)"""
    
    # Basic validation
    if not url.strip():
        return get_text(interface_language, "messages.error_empty_url"), "", False
    
    # Validate at least one test is enabled
    if not any([function_test_enabled, ux_test_enabled, performance_test_enabled, security_test_enabled]):
        return get_text(interface_language, "messages.error_no_tests"), "", False
    
    # Validate LLM configuration
    valid, msg = validate_llm_config(api_key, base_url, model, interface_language)
    if not valid:
        return f"❌ {get_text(interface_language, 'messages.error')}: {msg}", "", False
    
    # Create configuration
    config = create_config_dict(
        url,
        function_test_enabled, function_test_type, business_objectives,
        ux_test_enabled, performance_test_enabled, security_test_enabled,
        api_key, base_url, model,
        report_language=interface_language
    )
    
    # Generate task ID
    task_id = str(uuid.uuid4())
    
    # Add to queue
    user_info = {"config": config, "submitted_at": datetime.now(), "interface_language": interface_language}
    position = queue_manager.add_task(task_id, user_info)
    
    status_msg = f"{get_text(interface_language, 'messages.task_submitted')}\n{get_text(interface_language, 'messages.task_id_label')}: {task_id}\n{get_text(interface_language, 'messages.queue_position')}: {position}"
    if position > 1:
        status_msg += f"\n{get_text(interface_language, 'messages.queue_waiting', count=position-1)}"
    
    # Record submission history
    submission_history.append({
        "task_id": task_id,
        "url": url,
        "tests": {
            "function": function_test_enabled,
            "function_type": function_test_type,
            "business_objectives": business_objectives,
            "ux": ux_test_enabled,
        },
        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    return status_msg, task_id, True


def check_task_status(task_id: str, interface_language: str = "zh-CN") -> Tuple[str, str, Any]:
    """Check task status"""
    if not task_id.strip():
        return (
            get_text(interface_language, "status.task_id_placeholder"),
            f"<div style='text-align: center; padding: 50px; color: #888;'>{get_text(interface_language, 'status.default_message')}</div>",
            gr.update(visible=False, value=None),
        )
    
    status = queue_manager.get_task_status(task_id)
    
    if status["status"] == "not_found":
        return (
            get_text(interface_language, "messages.task_not_found"),
            f"<div style='text-align: center; padding: 50px; color: #ff6b6b;'>{get_text(interface_language, 'messages.task_not_found_message')}</div>",
            gr.update(visible=False, value=None),
        )
    
    if status["status"] == "queued":
        position = queue_manager.get_queue_position(task_id)
        return (
            get_text(interface_language, "messages.task_queued", position=position),
            f"<div style='text-align: center; padding: 50px; color: #ffa500;'>{get_text(interface_language, 'messages.task_queued_message')}</div>",
            gr.update(visible=False, value=None),
        )
    
    if status["status"] == "running":
        return (
            get_text(interface_language, "messages.task_running"),
            f"<div style='text-align: center; padding: 50px; color: #4dabf7;'>{get_text(interface_language, 'messages.task_running_message')}</div>",
            gr.update(visible=False, value=None),
        )
    
    if status["status"] == "completed":
        result = status.get("result")
        if result and result[0]:  # html_report_path exists
            # Read HTML report content
            try:
                with open(result[0], 'r', encoding='utf-8') as f:
                    html_content = f.read()
                # Wrap report in iframe to isolate its styles and avoid affecting external layout
                # Inline rendering, remove inner scrolling and horizontal scrolling
                content = html_content
                m = re.search(r"<head[^>]*>", content, flags=re.I)
                inject_style = (
                    "<style>html,body{margin:0;padding:0;overflow-x:hidden;}"
                    "img,canvas,svg,video{max-width:100%;height:auto;}"
                    ".container,.wrapper,.content{max-width:100%;}"
                    "</style>"
                )
                if m:
                    insert_at = m.end()
                    content = content[:insert_at] + inject_style + content[insert_at:]
                else:
                    content = f"<head>{inject_style}</head>" + content
                escaped = html_lib.escape(content, quote=True)
                iframe_html = (
                    "<iframe style='width:100%;height:1000px;border:none;overflow:hidden;background:#fff;' "
                    f"srcdoc=\"{escaped}\"></iframe>"
                )
                return (
                    f"{get_text(interface_language, 'messages.task_completed')}\n{get_text(interface_language, 'messages.report_path')}: {result[0]}",
                    iframe_html,
                    gr.update(visible=True, value=result[0]),
                )
            except Exception as e:
                return (
                    f"{get_text(interface_language, 'messages.task_completed')}, but failed to read report: {str(e)}\n{get_text(interface_language, 'messages.report_path')}: {result[0]}",
                    f"<div style='text-align: center; padding: 50px; color: #ff6b6b;'><p>❌ Unable to read HTML report file</p><p>{get_text(interface_language, 'messages.report_path')}：{result[0]}</p><p>{get_text(interface_language, 'messages.error_info', error=str(e))}</p></div>",
                    gr.update(visible=True, value=result[0]),
                )
        else:
            return (
                get_text(interface_language, "messages.task_completed_no_report"),
                f"<div style='text-align: center; padding: 50px; color: #ffa500;'>{get_text(interface_language, 'messages.task_completed_no_report_message')}</div>",
                gr.update(visible=False, value=None),
            )
    
    if status["status"] == "failed":
        error = status.get("error", "Unknown error")
        return (
            get_text(interface_language, "messages.task_failed", error=error),
            f"<div style='text-align: center; padding: 50px; color: #ff6b6b;'><p>{get_text(interface_language, 'messages.task_failed_message')}</p><p>{get_text(interface_language, 'messages.error_info', error=error)}</p></div>",
            gr.update(visible=False, value=None),
        )
    
    return (
        get_text(interface_language, "messages.unknown_status"),
        f"<div style='text-align: center; padding: 50px; color: #888;'>{get_text(interface_language, 'messages.unknown_status')}</div>",
        gr.update(visible=False, value=None),
    )


async def process_queue():
    """Process tasks in queue"""
    while True:
        task_id = queue_manager.get_next_task()
        if task_id:
            try:
                task_status = queue_manager.get_task_status(task_id)
                config = task_status["user_info"]["config"]
                interface_language = task_status["user_info"].get("interface_language", "zh-CN")
                
                # Execute test
                html_report_path, report_path, error = await run_webqa_test(config, interface_language)
                
                if error:
                    queue_manager.complete_task(task_id, error=error)
                else:
                    queue_manager.complete_task(task_id, result=(html_report_path, report_path))
                    
            except Exception as e:
                queue_manager.complete_task(task_id, error=str(e))
        
        await asyncio.sleep(1)  # Avoid busy waiting


def create_gradio_interface(language: str = "zh-CN"):
    """Create Gradio interface with specified language"""
    
    # Custom CSS styles
    custom_css = """
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    /* Global font settings for better English typography */
    * {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue', sans-serif;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }
    
    /* Specific font for headers and titles */
    h1, h2, h3, h4, h5, h6 {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
        font-weight: 600;
        letter-spacing: -0.025em;
    }
    
    /* Button and input font improvements */
    button, input, textarea, select {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
        font-weight: 400;
    }
    
    #html-report { border: 1px solid #e1e5e9; border-radius: 8px; padding: 0; background: #fff; }
    #html-report iframe { width: 100%; height: 1800px; border: none; overflow: hidden; }
    
    .gradio-container { max-width: 1500px !important; margin: 0 auto !important; width: 100% !important; }
    
    /* Prevent layout shrinking */
    .tab-nav {
        position: sticky;
        top: 0;
        z-index: 100;
    }
    
    /* Improve form layout */
    .form-group {
        margin-bottom: 1rem;
    }
    
    /* Ensure task status area doesn't shrink */
    .task-status-container {
        min-height: 400px;
    }
    
    /* Remove password field hint styles */
    input[type="password"] {
        background-color: #fff !important;
    }
    
    /* Top GitHub CTA button */
    .gh-cta-wrap { text-align: right; padding-top: 16px; }
    .gh-cta {
        display: inline-block;
        padding: 10px 16px;
        border-radius: 8px;
        background: linear-gradient(90deg,#2563eb,#7c3aed); /* Blue-purple gradient, more eye-catching */
        color: #fff !important;
        text-decoration: none !important;
        font-weight: 600;
        font-size: 14px;
        box-shadow: 0 4px 12px rgba(0,0,0,.12);
        transition: transform .12s ease, box-shadow .12s ease;
    }
    .gh-cta:hover { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(0,0,0,.16); }

    /* Three-column compact grid and spacing optimization */
    .config-grid { gap: 16px; flex-wrap: wrap; }
    .config-card { background:#fff; border:1px solid #e5e7eb; border-radius:10px; padding:16px; flex: 1 1 calc(50% - 8px); min-width: 300px; }
    .config-card h3 { margin:0 0 12px; font-size:16px; border-bottom:1px solid #f1f5f9; padding-bottom:8px; }
    .config-card .gradio-checkbox, .config-card .gradio-radio, .config-card .gradio-textbox { margin-bottom:10px; }

    /* Unified content width container (for various Tabs) */
    .content-wrapper { max-width: 1500px; margin: 0 auto; width: 100%; overflow-x: auto; }
    
    /* Table width constraints, use stronger selectors to prevent container widening */
    .fixed-width-table,
    .fixed-width-table > div,
    .fixed-width-table .table-wrap,
    .fixed-width-table .overflow-x-auto,
    .content-wrapper .gradio-dataframe,
    .content-wrapper .gradio-dataframe > div,
    .content-wrapper .gradio-dataframe .table-wrap,
    .content-wrapper .gradio-dataframe .overflow-x-auto { 
        max-width: 100% !important; 
        width: 100% !important; /* Ensure it takes available width */
        overflow-x: auto !important; 
        box-sizing: border-box !important;
    }
    
    .fixed-width-table table,
    .content-wrapper .gradio-dataframe table { 
        width: 100% !important; 
        table-layout: auto !important; /* Allow table to size naturally or be forced by content */
        max-width: none !important; /* Remove max-width to allow content to dictate width */
    }
    
    /* Column width allocation */
    .fixed-width-table th:nth-child(1), 
    .fixed-width-table td:nth-child(1),
    .content-wrapper .gradio-dataframe th:nth-child(1), 
    .content-wrapper .gradio-dataframe td:nth-child(1) { 
        width: auto !important; /* Allow auto width for scrolling */
        max-width: none !important; /* Remove max-width constraint */
        min-width: 180px !important; 
    }
    .fixed-width-table th:nth-child(2), 
    .fixed-width-table td:nth-child(2),
    .content-wrapper .gradio-dataframe th:nth-child(2), 
    .content-wrapper .gradio-dataframe td:nth-child(2) { 
        width: auto !important; 
        max-width: none !important; 
        min-width: 280px !important; 
    }
    .fixed-width-table th:nth-child(3), 
    .fixed-width-table td:nth-child(3),
    .content-wrapper .gradio-dataframe th:nth-child(3), 
    .content-wrapper .gradio-dataframe td:nth-child(3) { 
        width: auto !important; 
        max-width: none !important; 
        min-width: 300px !important; 
    }
    .fixed-width-table th:nth-child(4), 
    .fixed-width-table td:nth-child(4),
    .content-wrapper .gradio-dataframe th:nth-child(4), 
    .content-wrapper .gradio-dataframe td:nth-child(4) { 
        width: auto !important; 
        max-width: none !important; 
        min-width: 70px !important; 
        text-align: center !important;
    }
    .fixed-width-table th:nth-child(5), 
    .fixed-width-table td:nth-child(5),
    .content-wrapper .gradio-dataframe th:nth-child(5), 
    .content-wrapper .gradio-dataframe td:nth-child(5) { 
        width: auto !important; 
        max-width: none !important; 
        min-width: 80px !important; 
        text-align: center !important;
    }
    .fixed-width-table th:nth-child(6), 
    .fixed-width-table td:nth-child(6),
    .content-wrapper .gradio-dataframe th:nth-child(6), 
    .content-wrapper .gradio-dataframe td:nth-child(6) { 
        width: auto !important; 
        max-width: none !important; 
        min-width: 200px !important; 
        text-align: left !important;
    }
    .fixed-width-table th:nth-child(7), 
    .fixed-width-table td:nth-child(7),
    .content-wrapper .gradio-dataframe th:nth-child(7), 
    .content-wrapper .gradio-dataframe td:nth-child(7) { 
        width: auto !important; 
        max-width: none !important; 
        min-width: 70px !important; 
        text-align: center !important;
    }
    
    .fixed-width-table th, 
    .fixed-width-table td,
    .content-wrapper .gradio-dataframe th, 
    .content-wrapper .gradio-dataframe td { 
        overflow: hidden !important; 
        text-overflow: ellipsis !important; 
        white-space: nowrap !important; 
        padding: 8px 6px !important;
        box-sizing: border-box !important;
        vertical-align: middle !important;
    }
    
    /* Table header style optimization */
    .fixed-width-table th,
    .content-wrapper .gradio-dataframe th {
        background-color: #f8fafc !important;
        font-weight: 600 !important;
        color: #374151 !important;
        border-bottom: 2px solid #e5e7eb !important;
        text-align: center !important;
    }
    
    /* Table row style optimization */
    .fixed-width-table tbody tr:nth-child(even),
    .content-wrapper .gradio-dataframe tbody tr:nth-child(even) {
        background-color: #f9fafb !important;
    }
    
    .fixed-width-table tbody tr:hover,
    .content-wrapper .gradio-dataframe tbody tr:hover {
        background-color: #f3f4f6 !important;
        transition: background-color 0.2s ease !important;
    }
    
    /* Table border optimization */
    .fixed-width-table table,
    .content-wrapper .gradio-dataframe table {
        border-collapse: collapse !important;
        border: 1px solid #e5e7eb !important;
        border-radius: 8px !important;
        overflow: hidden !important;
    }
    
    .fixed-width-table td,
    .content-wrapper .gradio-dataframe td {
        border-right: 1px solid #f1f5f9 !important;
        border-bottom: 1px solid #f1f5f9 !important;
    }
    
    .fixed-width-table td:last-child,
    .content-wrapper .gradio-dataframe td:last-child {
        border-right: none !important;
    }
    """
    
    with gr.Blocks(title="WebQA Agent", theme=gr.themes.Soft(), css=custom_css) as app:
        with gr.Row(elem_id="app-wrapper"):
            with gr.Column(scale=8):
                gr.Markdown(f"# {get_text(language, 'title')}")
                gr.Markdown(f"## {get_text(language, 'subtitle')}")
                gr.Markdown(get_text(language, "description"))
            with gr.Column(scale=2):
                gr.HTML(f"<div class='gh-cta-wrap'><a class='gh-cta' href='https://github.com/MigoXLab/webqa-agent' target='_blank' rel='noopener'>{get_text(language, 'github_cta')}</a></div>")
        
        with gr.Tabs():
            # Configuration tab
            with gr.TabItem(get_text(language, "tabs.config")):
                # Two-column layout: left (target config + LLM config stacked), right (test types)
                with gr.Row(elem_classes=["config-grid"]):
                    with gr.Column(elem_classes=["config-card"], min_width=300, scale=0):
                        gr.Markdown(f"### {get_text(language, 'config.target_config')}")
                        url = gr.Textbox(
                            label=get_text(language, "config.target_url"),
                            placeholder=get_text(language, "config.target_url_placeholder"),
                            # value="https://demo.chat-sdk.dev/",
                            info=get_text(language, "config.target_url_info")
                        )
                    
                        gr.Markdown(f"### {get_text(language, 'config.llm_config')}")
                        model = gr.Textbox(
                            label=get_text(language, "config.model_name"),
                            # value="gpt-4.1-mini",
                            placeholder="eg. gpt-4.1-mini",
                            info=get_text(language, "config.model_name_info")
                        )
                        api_key = gr.Textbox(
                            label=get_text(language, "config.api_key"),
                            value="",
                            info=get_text(language, "config.api_key_info"),
                            type="password"
                        )
                        base_url = gr.Textbox(
                            label=get_text(language, "config.base_url"),
                            value="",
                            info=get_text(language, "config.base_url_info")
                        )

                    with gr.Column(elem_classes=["config-card"], min_width=300, scale=0):
                        gr.Markdown(f"### {get_text(language, 'config.test_types')}")
                        function_test_enabled = gr.Checkbox(label=get_text(language, "config.function_test"), value=True)
                        
                        with gr.Group(visible=True) as function_test_group:
                            function_test_type = gr.Radio(
                                label=get_text(language, "config.function_test_type"),
                                choices=["default", "ai"],
                                value="ai",
                                info=get_text(language, "config.function_test_type_info")
                            )
                            business_objectives = gr.Textbox(
                                label=get_text(language, "config.business_objectives"),
                                placeholder="eg. "+get_text(language, "config.business_objectives_placeholder"),
                                info=get_text(language, "config.business_objectives_info")
                            )
                        
                        ux_test_enabled = gr.Checkbox(label=get_text(language, "config.ux_test"), value=False)
                        performance_test_enabled = gr.Checkbox(
                            label=get_text(language, "config.performance_test"), 
                            value=False, 
                            interactive=False,
                            info=get_text(language, "config.performance_test_info")
                        )
                        security_test_enabled = gr.Checkbox(
                            label=get_text(language, "config.security_test"), 
                            value=False, 
                            interactive=False,
                            info=get_text(language, "config.security_test_info")
                        )
                
                with gr.Row():
                    submit_btn = gr.Button(get_text(language, "config.submit_btn"), variant="primary", size="lg")
                
                # Result display
                with gr.Accordion(get_text(language, "config.submit_result"), open=False) as submit_result_accordion:
                    submit_status = gr.Textbox(
                        label=get_text(language, "status.task_status"),
                        interactive=False,
                        lines=5,
                        show_label=False
                    )
                    task_id_output = gr.Textbox(
                        label=get_text(language, "status.task_id"),
                        interactive=False,
                        visible=False
                    )
            
            # Status query tab
            with gr.TabItem(get_text(language, "tabs.status")):
                with gr.Column(elem_classes=["task-status-container"]):
                    gr.Markdown(f"### {get_text(language, 'status.query_title')}")
                    with gr.Row(variant="compact"):
                        with gr.Column(min_width=300):
                            task_id_input = gr.Textbox(
                                label=get_text(language, "status.task_id"),
                                placeholder=get_text(language, "status.task_id_placeholder"),
                                info=get_text(language, "status.task_id_info")
                            )
                        with gr.Column(min_width=100):
                            check_btn = gr.Button(get_text(language, "status.check_btn"), variant="secondary", size="lg")
                    
                    task_status_output = gr.Textbox(
                        label=get_text(language, "status.task_status"),
                        interactive=False,
                        lines=5
                    )
                    
                    # HTML report display + download (button above preview)
                    gr.Markdown(f"### {get_text(language, 'status.test_report')}")
                    download_file = gr.File(
                        label=get_text(language, "status.html_report"),
                        interactive=False,
                        visible=False,
                        file_types=[".html"],
                    )
                    html_output = gr.HTML(
                        label=get_text(language, "status.html_report"),
                        visible=True,
                        elem_id="html-report",
                        show_label=False,
                        value=f"<div style='text-align: center; padding: 50px; color: #888;'>{get_text(language, 'status.default_message')}</div>"
                    )

            # History records
            with gr.TabItem(get_text(language, "tabs.history")) as history_tab:
                with gr.Column(elem_classes=["content-wrapper"]):
                    gr.Markdown(f"### {get_text(language, 'history.title')}")
                history_table = gr.Dataframe(
                    headers=get_text(language, "history.headers"),
                    row_count=(0, "dynamic"),
                    interactive=False,
                    elem_classes=["fixed-width-table"]
                )
                refresh_history_btn = gr.Button(get_text(language, "history.refresh_btn"), variant="secondary", size="lg")
                
        
        # Event bindings
        def submit_and_expand(*args):
            """Submit task and expand results"""
            status_msg, task_id, success = submit_test(*args, interface_language=language)
            if success:
                return status_msg, task_id, gr.Accordion(open=True)
            else:
                return status_msg, task_id, gr.Accordion(open=True)
        
        # Auto expand results and refresh history once after submission
        submit_btn.click(
            fn=submit_and_expand,
            inputs=[
                url,
                function_test_enabled, function_test_type, business_objectives,
                ux_test_enabled, performance_test_enabled, security_test_enabled,
                api_key, base_url, model
            ],
            outputs=[submit_status, task_id_output, submit_result_accordion]
        )

        submit_btn.click(
            fn=lambda: get_history_rows(language),
            inputs=[],
            outputs=[history_table]
        )
        
        check_btn.click(
            fn=lambda task_id: check_task_status(task_id, language),
            inputs=[task_id_input],
            outputs=[task_status_output, html_output, download_file]
        )

        # Refresh history records
        def get_history_rows(lang):
            rows = []
            for item in reversed(submission_history[-100:]):
                business_objectives = item["tests"].get("business_objectives", "")
                function_type = item["tests"]["function_type"]
                
                if function_type == "ai" and business_objectives:
                    business_display = business_objectives[:30] + "..." if len(business_objectives) > 30 else business_objectives
                else:
                    business_display = "-"
                
                rows.append([
                    item["submitted_at"],
                    item["task_id"],
                    item["url"],
                    "✅" if item["tests"]["function"] else "-",
                    item["tests"]["function_type"],
                    business_display,
                    "✅" if item["tests"]["ux"] else "-"
                ])
            return rows

        # Bind refresh button in "Submission History" Tab
        refresh_history_btn.click(
            fn=lambda: get_history_rows(language),
            inputs=[],
            outputs=[history_table]
        )
        
        # Bind "Submission History" Tab selection event, auto refresh history records
        history_tab.select(
            fn=lambda: get_history_rows(language),
            inputs=[],
            outputs=[history_table]
        )
        
        # Clear report display when input changes
        task_id_input.change(
            fn=lambda x: ("", f"<div style='text-align: center; padding: 50px; color: #888;'>{get_text(language, 'status.input_change_message')}</div>"),
            inputs=[task_id_input],
            outputs=[task_status_output, html_output]
        )
    
    return app


if __name__ == "__main__":
    # Start queue processing
    import threading
    
    def run_queue_processor():
        """Run queue processor in background thread"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(process_queue())
    
    queue_thread = threading.Thread(target=run_queue_processor, daemon=True)
    queue_thread.start()
    
    # Create and launch Gradio application
    app = create_gradio_interface()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True
    )
