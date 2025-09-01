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

# 导入项目模块
from webqa_agent.executor import ParallelMode

# 简单的提交历史（仅当前会话内存保存）
submission_history: list = []


class QueueManager:
    """任务队列管理器，确保同时只有一个任务在执行"""
    
    def __init__(self):
        self.current_task: Optional[str] = None
        self.task_queue: queue.Queue = queue.Queue()
        self.task_status: Dict[str, Dict] = {}
        self.lock = Lock()
    
    def add_task(self, task_id: str, user_info: Dict) -> int:
        """添加任务到队列，返回队列位置"""
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
        """获取下一个待执行的任务"""
        with self.lock:
            if self.current_task is None and not self.task_queue.empty():
                task_id = self.task_queue.get()
                self.current_task = task_id
                self.task_status[task_id]["status"] = "running"
                self.task_status[task_id]["started_at"] = datetime.now()
                return task_id
            return None
    
    def complete_task(self, task_id: str, result: Any = None, error: Any = None):
        """标记任务完成"""
        with self.lock:
            if task_id in self.task_status:
                self.task_status[task_id]["status"] = "completed" if result else "failed"
                self.task_status[task_id]["completed_at"] = datetime.now()
                self.task_status[task_id]["result"] = result
                self.task_status[task_id]["error"] = error
            if self.current_task == task_id:
                self.current_task = None
    
    def get_queue_position(self, task_id: str) -> int:
        """获取任务在队列中的位置"""
        with self.lock:
            if task_id == self.current_task:
                return 0  # 当前正在执行
            
            queue_list = list(self.task_queue.queue)
            try:
                return queue_list.index(task_id) + 1
            except ValueError:
                return -1  # 任务不在队列中
    
    def get_task_status(self, task_id: str) -> Dict:
        """获取任务状态"""
        with self.lock:
            return self.task_status.get(task_id, {"status": "not_found"})


# 全局队列管理器
queue_manager = QueueManager()


def validate_llm_config(api_key: str, base_url: str, model: str) -> Tuple[bool, str]:
    """验证LLM配置"""
    if not api_key.strip():
        return False, "API Key不能为空"
    
    if not base_url.strip():
        return False, "Base URL不能为空"
    
    if not model.strip():
        return False, "模型名称不能为空"
    
    # 简单的URL格式检查
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        return False, "Base URL格式不正确，应以http://或https://开头"
    
    return True, "配置验证通过"


def create_config_dict(
    url: str,
    # description: str,
    # max_concurrent_tests: int,
    function_test_enabled: bool,
    function_test_type: str,
    business_objectives: str,
    ux_test_enabled: bool,
    performance_test_enabled: bool,
    security_test_enabled: bool,
    api_key: str,
    base_url: str,
    model: str
    # viewport_width: int,
    # viewport_height: int,
    # headless: bool,
    # language: str
) -> Dict[str, Any]:
    """创建配置字典"""
    config = {
        "target": {
            "url": url,
            "description": ""
            # "max_concurrent_tests": max_concurrent_tests
        },
        "test_config": {
            "function_test": {
                "enabled": function_test_enabled,
                "type": function_test_type,
                "business_objectives": business_objectives
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
        "browser_config": {
            "viewport": {"width": 1280, "height": 720},
            "headless": True,
            "language": "zh-CN",
            "cookies": []
        }
    }
    
    return config


def build_test_configurations(config: Dict[str, Any]) -> list:
    """根据配置构建测试配置列表"""
    tests = []
    tconf = config.get("test_config", {})
    
    base_browser = {
        "viewport": config.get("browser_config", {}).get("viewport", {"width": 1280, "height": 720}),
        "headless": True,  # Web界面强制headless
    }
    
    # function test
    if tconf.get("function_test", {}).get("enabled"):
        if tconf["function_test"].get("type") == "ai":
            tests.append({
                "test_type": "ui_agent_langgraph",
                "test_name": "智能功能测试",
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


async def run_webqa_test(config: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """运行WebQA测试"""
    try:
        # 验证LLM配置
        llm_config = {
            "api": "openai",
            "model": config["llm_config"]["model"],
            "api_key": config["llm_config"]["api_key"],
            "base_url": config["llm_config"]["base_url"],
            "temperature": config["llm_config"]["temperature"],
        }
        
        # 构建测试配置
        test_configurations = build_test_configurations(config)
        
        if not test_configurations:
            return None, None, "错误：未启用任何测试类型"
        
        target_url = config["target"]["url"]
        # max_concurrent_tests = config["target"].get("max_concurrent_tests", 2)
        max_concurrent_tests = 1
        
        # 执行测试
        parallel_mode = ParallelMode([], max_concurrent_tests=max_concurrent_tests)
        results, report_path, html_report_path, result_count = await parallel_mode.run(
            url=target_url,
            llm_config=llm_config,
            test_configurations=test_configurations,
            log_cfg=config.get("log", {"level": "info"})
        )
        
        return html_report_path, report_path, None
        
    except Exception as e:
        error_msg = f"测试执行失败: {str(e)}\n{traceback.format_exc()}"
        return None, None, error_msg


def submit_test(
    url: str,
    # description: str,
    # max_concurrent_tests: int,
    function_test_enabled: bool,
    function_test_type: str,
    business_objectives: str,
    ux_test_enabled: bool,
    performance_test_enabled: bool,
    security_test_enabled: bool,
    api_key: str,
    base_url: str,
    model: str
    # viewport_width: int,
    # viewport_height: int,
    # headless: bool,
    # language: str
) -> Tuple[str, str, bool]:
    """提交测试任务，返回(状态消息, 任务ID, 是否成功)"""
    
    # 基本验证
    if not url.strip():
        return "❌ 错误：目标URL不能为空", "", False
    
    # 验证至少启用一个测试
    if not any([function_test_enabled, ux_test_enabled, performance_test_enabled, security_test_enabled]):
        return "❌ 错误：至少需要启用一个测试类型", "", False
    
    # 如果启用功能测试但没有设置业务目标
    if function_test_enabled and function_test_type == "ai" and not business_objectives.strip():
        return "❌ 错误：AI功能测试需要设置业务目标", "", False
    
    # 验证LLM配置
    valid, msg = validate_llm_config(api_key, base_url, model)
    if not valid:
        return f"❌ 错误：{msg}", "", False
    
    # 创建配置
    config = create_config_dict(
        url,
        function_test_enabled, function_test_type, business_objectives,
        ux_test_enabled, performance_test_enabled, security_test_enabled,
        api_key, base_url, model
    )
    
    # 生成任务ID
    task_id = str(uuid.uuid4())
    
    # 添加到队列
    user_info = {"config": config, "submitted_at": datetime.now()}
    position = queue_manager.add_task(task_id, user_info)
    
    status_msg = f"✅ 任务已提交！\n任务ID: {task_id}\n当前队列位置: {position}"
    if position > 1:
        status_msg += f"\n⏳ 请耐心等待，前面还有 {position-1} 个任务在排队"
    
    # 记录历史提交
    submission_history.append({
        "task_id": task_id,
        "url": url,
        "tests": {
            "function": function_test_enabled,
            "function_type": function_test_type,
            "ux": ux_test_enabled,
        },
        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    return status_msg, task_id, True


def check_task_status(task_id: str) -> Tuple[str, str, Any]:
    """检查任务状态"""
    if not task_id.strip():
        return (
            "请输入任务ID",
            "<div style='text-align: center; padding: 50px; color: #888;'>📄 请先输入任务ID并查询状态</div>",
            gr.update(visible=False, value=None),
        )
    
    status = queue_manager.get_task_status(task_id)
    
    if status["status"] == "not_found":
        return (
            "❌ 任务不存在",
            "<div style='text-align: center; padding: 50px; color: #ff6b6b;'>❌ 任务不存在，请检查任务ID是否正确</div>",
            gr.update(visible=False, value=None),
        )
    
    if status["status"] == "queued":
        position = queue_manager.get_queue_position(task_id)
        return (
            f"⏳ 任务排队中，当前位置: {position}",
            "<div style='text-align: center; padding: 50px; color: #ffa500;'>⏳ 任务正在排队中，请稍后再查询</div>",
            gr.update(visible=False, value=None),
        )
    
    if status["status"] == "running":
        return (
            "🚀 任务正在执行中，请稍候...",
            "<div style='text-align: center; padding: 50px; color: #4dabf7;'>🚀 任务正在执行中，请稍后再查询结果</div>",
            gr.update(visible=False, value=None),
        )
    
    if status["status"] == "completed":
        result = status.get("result")
        if result and result[0]:  # html_report_path存在
            # 读取HTML报告内容
            try:
                with open(result[0], 'r', encoding='utf-8') as f:
                    html_content = f.read()
                # 将报告包裹在 iframe 中以隔离其样式，避免影响外部布局
                # 内联渲染，移除内层滚动和水平滚动
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
                    f"✅ 任务执行完成！\n报告路径: {result[0]}",
                    iframe_html,
                    gr.update(visible=True, value=result[0]),
                )
            except Exception as e:
                return (
                    f"✅ 任务执行完成，但读取报告失败: {str(e)}\n报告路径: {result[0]}",
                    f"<div style='text-align: center; padding: 50px; color: #ff6b6b;'><p>❌ 无法读取HTML报告文件</p><p>报告路径：{result[0]}</p><p>错误信息：{str(e)}</p></div>",
                    gr.update(visible=True, value=result[0]),
                )
        else:
            return (
                "✅ 任务执行完成，但未生成HTML报告",
                "<div style='text-align: center; padding: 50px; color: #ffa500;'>⚠️ 测试执行完成，但未生成HTML报告</div>",
                gr.update(visible=False, value=None),
            )
    
    if status["status"] == "failed":
        error = status.get("error", "未知错误")
        return (
            f"❌ 任务执行失败: {error}",
            f"<div style='text-align: center; padding: 50px; color: #ff6b6b;'><p>❌ 任务执行失败</p><p>错误信息：{error}</p></div>",
            gr.update(visible=False, value=None),
        )
    
    return (
        "❓ 未知状态",
        "<div style='text-align: center; padding: 50px; color: #888;'>❓ 未知状态</div>",
        gr.update(visible=False, value=None),
    )


async def process_queue():
    """处理队列中的任务"""
    while True:
        task_id = queue_manager.get_next_task()
        if task_id:
            try:
                task_status = queue_manager.get_task_status(task_id)
                config = task_status["user_info"]["config"]
                
                # 执行测试
                html_report_path, report_path, error = await run_webqa_test(config)
                
                if error:
                    queue_manager.complete_task(task_id, error=error)
                else:
                    queue_manager.complete_task(task_id, result=(html_report_path, report_path))
                    
            except Exception as e:
                queue_manager.complete_task(task_id, error=str(e))
        
        await asyncio.sleep(1)  # 避免忙等待


def create_gradio_interface():
    """创建Gradio界面"""
    
    # 自定义CSS样式
    custom_css = """
    #html-report { border: 1px solid #e1e5e9; border-radius: 8px; padding: 0; background: #fff; }
    #html-report iframe { width: 100%; height: 1800px; border: none; overflow: hidden; }
    
    .gradio-container { max-width: 1500px !important; margin: 0 auto !important; width: 100% !important; }
    
    /* 防止布局缩小 */
    .tab-nav {
        position: sticky;
        top: 0;
        z-index: 100;
    }
    
    /* 改善表单布局 */
    .form-group {
        margin-bottom: 1rem;
    }
    
    /* 确保任务状态区域不缩小 */
    .task-status-container {
        min-height: 400px;
    }
    
    /* 去除密码字段的提示样式 */
    input[type="password"] {
        background-color: #fff !important;
    }
    
    /* 顶部 GitHub 引流按钮 */
    .gh-cta-wrap { text-align: right; padding-top: 16px; }
    .gh-cta {
        display: inline-block;
        padding: 10px 16px;
        border-radius: 8px;
        background: linear-gradient(90deg,#2563eb,#7c3aed); /* 蓝紫渐变，更醒目 */
        color: #fff !important;
        text-decoration: none !important;
        font-weight: 600;
        font-size: 14px;
        box-shadow: 0 4px 12px rgba(0,0,0,.12);
        transition: transform .12s ease, box-shadow .12s ease;
    }
    .gh-cta:hover { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(0,0,0,.16); }

    /* 三列紧凑栅格与间距优化 */
    .config-grid { gap: 16px; flex-wrap: wrap; }
    .config-card { background:#fff; border:1px solid #e5e7eb; border-radius:10px; padding:16px; flex: 1 1 calc(50% - 8px); min-width: 300px; }
    .config-card h3 { margin:0 0 12px; font-size:16px; border-bottom:1px solid #f1f5f9; padding-bottom:8px; }
    .config-card .gradio-checkbox, .config-card .gradio-radio, .config-card .gradio-textbox { margin-bottom:10px; }

    /* 统一内容宽度容器（用于各个Tab） */
    .content-wrapper { max-width: 1500px; margin: 0 auto; width: 100%; overflow-x: auto; }
    
    /* 表格宽度限制，使用更强的选择器防止拉宽容器 */
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
    
    /* 各列宽度分配 */
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
    
    /* 表头样式优化 */
    .fixed-width-table th,
    .content-wrapper .gradio-dataframe th {
        background-color: #f8fafc !important;
        font-weight: 600 !important;
        color: #374151 !important;
        border-bottom: 2px solid #e5e7eb !important;
        text-align: center !important;
    }
    
    /* 表格行样式优化 */
    .fixed-width-table tbody tr:nth-child(even),
    .content-wrapper .gradio-dataframe tbody tr:nth-child(even) {
        background-color: #f9fafb !important;
    }
    
    .fixed-width-table tbody tr:hover,
    .content-wrapper .gradio-dataframe tbody tr:hover {
        background-color: #f3f4f6 !important;
        transition: background-color 0.2s ease !important;
    }
    
    /* 表格边框优化 */
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
                gr.Markdown("# 🤖 WebQA Agent")
                gr.Markdown("## 全自动网页评估测试 Agent，一键诊断功能与交互体验")
                gr.Markdown("配置参数并运行网站质量检测测试。系统支持排队机制，确保稳定运行。")
            with gr.Column(scale=2):
                gr.HTML("<div class='gh-cta-wrap'><a class='gh-cta' href='https://github.com/MigoXLab/webqa-agent' target='_blank' rel='noopener'>🌟 在 GitHub 上为我们 Star</a></div>")
        
        with gr.Tabs():
            # 配置标签页
            with gr.TabItem("📝 测试配置"):
                # 两列布局：左侧（目标配置 + LLM配置叠放），右侧（测试类型）
                with gr.Row(elem_classes=["config-grid"]):
                    with gr.Column(elem_classes=["config-card"], min_width=300, scale=0):
                        gr.Markdown("### 🎯 目标配置")
                        url = gr.Textbox(
                            label="目标URL",
                            placeholder="https://example.com",
                            value="https://demo.chat-sdk.dev/",
                            info="要测试的网站URL"
                        )
                    
                        gr.Markdown("### 🤖 LLM配置")
                        model = gr.Textbox(
                            label="模型名称",
                            value="gpt-4.1-mini",
                            info="使用的语言模型 (OPENAI SDK 兼容格式)"
                        )
                        api_key = gr.Textbox(
                            label="API Key",
                            value="",
                            info="LLM服务的API密钥",
                            type="password"
                        )
                        base_url = gr.Textbox(
                            label="Base URL",
                            value="",
                            info="LLM服务的基础URL"
                        )

                    with gr.Column(elem_classes=["config-card"], min_width=300, scale=0):
                        gr.Markdown("### 🧪 测试类型")
                        function_test_enabled = gr.Checkbox(label="功能测试", value=True)
                        
                        with gr.Group(visible=True) as function_test_group:
                            function_test_type = gr.Radio(
                                label="功能测试类型",
                                choices=["default", "ai"],
                                value="ai",
                                info="default: 遍历测试 | ai: 智能测试"
                            )
                            business_objectives = gr.Textbox(
                                label="功能测试业务目标",
                                placeholder="测试对话功能，生成2个用例",
                                # value="生成两个测试用例",
                                info="ai: 智能测试的具体目标，可以修改以定义不同的测试场景"
                            )
                        
                        ux_test_enabled = gr.Checkbox(label="用户体验测试", value=False)
                        performance_test_enabled = gr.Checkbox(
                            label="性能测试", 
                            value=False, 
                            interactive=False,
                            info="目前在 ModelScope 版本不可用；请前往 GitHub 体验"
                        )
                        security_test_enabled = gr.Checkbox(
                            label="安全测试", 
                            value=False, 
                            interactive=False,
                            info="目前在 ModelScope 版本不可用；请前往 GitHub 体验"
                        )
                
                with gr.Row():
                    submit_btn = gr.Button("🚀 提交测试", variant="primary", size="lg")
                
                # 结果显示
                with gr.Accordion("📄 任务提交结果", open=False) as submit_result_accordion:
                    submit_status = gr.Textbox(
                        label="提交状态",
                        interactive=False,
                        lines=5,
                        show_label=False
                    )
                    task_id_output = gr.Textbox(
                        label="任务ID",
                        interactive=False,
                        visible=False
                    )
            
            # 状态查询标签页
            with gr.TabItem("📊 任务状态"):
                with gr.Column(elem_classes=["task-status-container"]):
                    gr.Markdown("### 查询任务执行状态")
                    with gr.Row(variant="compact"):
                        with gr.Column(min_width=300):
                            task_id_input = gr.Textbox(
                                label="任务ID",
                                placeholder="输入任务ID查询状态",
                                info="从测试配置页面获取的任务ID"
                            )
                        with gr.Column(min_width=100):
                            check_btn = gr.Button("🔍 查询状态", variant="secondary", size="lg")
                    
                    task_status_output = gr.Textbox(
                        label="任务状态",
                        interactive=False,
                        lines=5
                    )
                    
                    # HTML报告显示 + 下载（按钮在预览上方）
                    gr.Markdown("### 📋 测试报告")
                    download_file = gr.File(
                        label="HTML报告",
                        interactive=False,
                        visible=False,
                        file_types=[".html"],
                    )
                    html_output = gr.HTML(
                        label="HTML报告",
                        visible=True,
                        elem_id="html-report",
                        show_label=False,
                        value="<div style='text-align: center; padding: 50px; color: #888;'>📄 请先查询任务状态，成功后将在此显示测试报告</div>"
                    )

            # 历史记录
            with gr.TabItem("🗂️ 提交历史") as history_tab:
                with gr.Column(elem_classes=["content-wrapper"]):
                    gr.Markdown("### 提交记录")
                history_table = gr.Dataframe(
                    headers=["提交时间", "任务ID", "URL", "功能测试", "类型", "UX测试"],
                    row_count=(0, "dynamic"),
                    interactive=False,
                    elem_classes=["fixed-width-table"]
                )
                refresh_history_btn = gr.Button("🔄 刷新历史记录", variant="secondary", size="lg")
                
        
        # 事件绑定
        def submit_and_expand(*args):
            """提交任务并展开结果"""
            status_msg, task_id, success = submit_test(*args)
            if success:
                return status_msg, task_id, gr.Accordion(open=True)
            else:
                return status_msg, task_id, gr.Accordion(open=True)
        
        # 提交后自动展开结果并刷新一次历史表
        submit_btn.click(
            fn=submit_and_expand,
            inputs=[
                url,
                function_test_enabled, function_test_type, business_objectives,
                ux_test_enabled, performance_test_enabled, security_test_enabled,
                api_key, base_url, model
                # viewport_width, viewport_height, headless, language
            ],
            outputs=[submit_status, task_id_output, submit_result_accordion]
        )

        submit_btn.click(
            fn=lambda: get_history_rows(),
            inputs=[],
            outputs=[history_table]
        )
        
        check_btn.click(
            fn=check_task_status,
            inputs=[task_id_input],
            outputs=[task_status_output, html_output, download_file]
        )

        # 刷新历史记录
        def get_history_rows():
            rows = []
            for item in reversed(submission_history[-100:]):
                rows.append([
                    item["submitted_at"],
                    item["task_id"],
                    item["url"],
                    "✅" if item["tests"]["function"] else "-",
                    item["tests"]["function_type"],
                    "✅" if item["tests"]["ux"] else "-"
                ])
            return rows

        # 绑定“提交历史”Tab内的刷新按钮
        refresh_history_btn.click(
            fn=lambda: get_history_rows(),
            inputs=[],
            outputs=[history_table]
        )
        
        # 绑定“提交历史”Tab选中事件，自动刷新历史记录
        history_tab.select(
            fn=lambda: get_history_rows(),
            inputs=[],
            outputs=[history_table]
        )
        
        # 清空报告显示当输入改变时
        task_id_input.change(
            fn=lambda x: ("", "<div style='text-align: center; padding: 50px; color: #888;'>📄 请点击查询状态按钮获取最新状态</div>"),
            inputs=[task_id_input],
            outputs=[task_status_output, html_output]
        )
    
    return app


if __name__ == "__main__":
    # 启动队列处理
    import threading
    
    def run_queue_processor():
        """在后台线程中运行队列处理器"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(process_queue())
    
    queue_thread = threading.Thread(target=run_queue_processor, daemon=True)
    queue_thread.start()
    
    # 创建并启动Gradio应用
    app = create_gradio_interface()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True
    )
