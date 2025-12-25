<!-- SEO Meta Information and Structured Data -->
<div itemscope itemtype="https://schema.org/SoftwareApplication" align="center" xmlns="http://www.w3.org/1999/html">
  <meta itemprop="name" content="WebQA Agent: 全自动网页测试与质量保证工具">
  <meta itemprop="description" content="AI驱动的自主网页浏览器代理，提供性能、功能、用户体验和安全性的全面网站测试与质量保证服务">
  <meta itemprop="applicationCategory" content="网页测试软件">
  <meta itemprop="operatingSystem" content="跨平台">
  <meta itemprop="programmingLanguage" content="Python">
  <meta itemprop="url" content="https://github.com/MigoXLab/webqa-agent">
  <meta itemprop="softwareVersion" content="latest">
  <meta itemprop="license" content="Apache-2.0">
  <meta itemprop="keywords" content="Vibecoding, 网页评估, 自主探索, 自动化, AI, 浏览器自动化, 网页质量保障, 网页性能, 用户体验, 安全检查, 网页功能, 功能测试"/>

<h1 align="center" itemprop="name">WebQA Agent</h1>

<!-- badges -->
<p align="center">
  <a href="https://github.com/MigoXLab/webqa-agent/blob/main/LICENSE"><img src="https://img.shields.io/github/license/MigoXLab/webqa-agent" alt="License"></a>
  <a href="https://github.com/MigoXLab/webqa-agent/stargazers"><img src="https://img.shields.io/github/stars/MigoXLab/webqa-agent" alt="GitHub stars"></a>
  <a href="https://github.com/MigoXLab/webqa-agent/network/members"><img src="https://img.shields.io/github/forks/MigoXLab/webqa-agent" alt="GitHub forks"></a>
  <a href="https://github.com/MigoXLab/webqa-agent/issues"><img src="https://img.shields.io/github/issues/MigoXLab/webqa-agent" alt="GitHub issues"></a>
  <a href="https://deepwiki.com/MigoXLab/webqa-agent"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"></a>
</p>

<p align="center">
  体验Demo 🤗<a href="https://huggingface.co/spaces/mmmay0722/WebQA-Agent">HuggingFace</a> | 🚀<a href="https://modelscope.cn/studios/mmmmei22/WebQA-Agent/summary">ModelScope</a><br>
  加入我们 🎮<a href="https://discord.gg/fG5QAxYyNr">Discord</a> | 💬<a href="https://aicarrier.feishu.cn/docx/NRNXdIirXoSQEHxhaqjchUfenzd">微信群</a>
</p>

<p align="center"><a href="README.md">English</a> · <a href="README_zh-CN.md">简体中文</a></p>

<p align="center">
  如果觉得有帮助，欢迎在 GitHub 上点个 ⭐ 支持！
  <br/>
  <a href="https://github.com/MigoXLab/webqa-agent/stargazers" target="_blank">
    <img src="docs/images/star.gif" alt="Click Star" width="900">
  </a>
</p>

<p align="center">🤖 <strong>WebQA Agent</strong> 是全自动网页评估测试 Agent，一键完成性能、功能与交互体验的测试评估 ✨</p>
</div>

<!-- Additional SEO Keywords and Context
Vibecoding, Vibe coding, 网页测试自动化, 浏览器测试工具, AI驱动质量保障, 自动化网页测试, 网站性能分析, 功能测试自动化, 用户体验测试, 安全漏洞扫描, 浏览器测试, 网页应用测试, 自动化UI测试, 网页可访问性测试, 性能监控, 网站审计工具, 智能测试用例生成, 端到端测试, 回归测试, 兼容性测试, Vibecoding测试, 网页开发
-->

## 🚀 核心特性

### 🧭 功能介绍

<p>
  <img src="docs/images/webqa.svg" alt="WebQA Agent 业务功能图" />
</p>

### 📋 特性概览

- **🤖 AI 自主测试**：WebQA-Agent具备智能规划与反思能力，能够自主进行网站测试，无需手写脚本，自动探索页面、规划动作并执行端到端流程。采用两阶段架构（轻量级过滤+全面规划），并支持动态生成针对新出现UI元素的测试步骤
- **📊 多维度观测**：覆盖功能、性能、用户体验、安全等核心场景，评估页面加载速度、设计细节和链接，全面保障系统质量。采用多模态分析（截图+DOM结构+文本内容）和DOM差异检测，发现新的测试机会
- **🎯 可执行建议**：基于真实浏览器运行，具备智能元素优先级排序和自动视口管理能力，输出具体的优化与改进建议，并提供自适应恢复机制确保测试稳健执行
- **📈 可视化报告**：生成详细的HTML测试报告，多维度、可视化展示执行结果，便于分析与追踪

## 📹 示例演示

- **🤖 对话界面**: [AI 自主生成目标与步骤，在动态聊天页面中理解上下文并执行](https://pub-2c31c87660254d7bba9707e2b56fc15b.r2.dev/%E6%99%BA%E8%83%BDCase%E7%94%9F%E6%88%90.mp4)
- **🎨 静态页面**: [AI 自主探索页面结构、识别元素](https://pub-2c31c87660254d7bba9707e2b56fc15b.r2.dev/vibecoding.mp4)

体验Demo： [🤗Hugging Face](https://huggingface.co/spaces/mmmay0722/WebQA-Agent) · [🚀ModelScope](https://modelscope.cn/studios/mmmmei22/WebQA-Agent/summary)

## 🚀 快速开始

### 🏎️ 推荐：uv 本地安装
```bash
# 1) 创建项目并安装包
uv init my-webqa && cd my-webqa
uv add webqa-agent

# 2) 安装浏览器（必需）
uv run playwright install chromium

# 3) 生成配置模板
uv run webqa-agent init            # 创建 config.yaml

# 4) 编辑 config.yaml
#    - target.url: 你要测试的网站
#    - llm_config.api_key: 你的 OpenAI 密钥（或设 OPENAI_API_KEY）
#    更多配置说明见下方“使用说明 > 测试配置”

# 5) 运行
uv run webqa-agent run
```

### 🐳 Docker 一键启动

在开始之前，请确保已安装 Docker（推荐 Docker >= 24.0，Docker Compose >= 2.32）。官方指南：[Docker 安装](https://docs.docker.com/get-started/get-docker/)

```bash
mkdir -p config \
  && curl -fsSL https://raw.githubusercontent.com/MigoXLab/webqa-agent/main/config/config.yaml.example -o config/config.yaml

# 编辑 config.yaml：设置 target.url、llm_config.api_key 等

curl -fsSL https://raw.githubusercontent.com/MigoXLab/webqa-agent/main/start.sh | bash
```

### 🛠️ 源码安装
```bash
git clone https://github.com/MigoXLab/webqa-agent.git
cd webqa-agent
uv sync
uv run playwright install chromium
cp ./config/config.yaml.example ./config/config.yaml
# 编辑 config.yaml：设置 target.url、llm_config.api_key 等
uv run webqa-agent run -c ./config/config.yaml
```

### 🔧 可选依赖
性能测试（Lighthouse）：`npm install lighthouse chrome-launcher`（需 Node.js ≥18）

安全测试（Nuclei）：
```bash
brew install nuclei      # macOS
nuclei -ut               # 更新模板
# Linux/Windows: https://github.com/projectdiscovery/nuclei/releases
```

## ⚙️ 使用说明

### 测试配置

```yaml
target:
  url: https://example.com              # 需要测试的网站 URL
  description: 网站质量保证测试
  # max_concurrent_tests: 2             # 可选，默认并发数 2

test_config:
  function_test:                        # 功能测试
    enabled: True
    type: ai                            # 'default' 或 'ai'
    business_objectives: 测试搜索功能，生成3个测试用例
    dynamic_step_generation:
      enabled: True                     # 启用动态步骤生成
      max_dynamic_steps: 10
      min_elements_threshold: 1
  ux_test:                              # 用户体验测试
    enabled: True
  performance_test:                     # 性能分析（需要 Lighthouse）
    enabled: False
  security_test:                        # 安全扫描（需要 Nuclei）
    enabled: False

llm_config:
  model: gpt-4.1-2025-04-14             # 视觉模型配置，当前仅支持 OpenAI SDK 兼容格式
  filter_model: gpt-4o-mini             # 轻量级模型用于元素过滤
  api_key: your_api_key                 # 或使用 OPENAI_API_KEY 环境变量
  base_url: https://api.openai.com/v1   # 或使用 OPENAI_BASE_URL 环境变量
  temperature: 0.1

browser_config:
  viewport: {"width": 1280, "height": 720}
  headless: False                       # Docker 环境自动设为 True
  language: en-US
  cookies: []
  save_screenshots: False

report:
  language: en-US                       # zh-CN 或 en-US

log:
  level: info                           # debug, info, warning, error
```

### 执行说明

- **功能测试（AI 模式）**：两阶段规划。Stage 1（`filter_model`）优先筛选元素提升效率，Stage 2（主模型）生成完整用例。根据页面状态与覆盖率会自适应反思/重规划，实际执行用例数可能与初始不同。开启 `dynamic_step_generation` 时，DOM diff 发现的新元素（如下拉、弹窗）会自动生成额外步骤。
- **功能测试（default 模式）**：聚焦交互是否成功（点击、跳转等）。
- **用户体验测试**：多模态（截图 + DOM + 文本）评估视觉质量、排版/语法、布局渲染，并给出基于最佳实践的优化建议。

### 📖 CLI 命令参考

#### init - 创建配置

```bash
# 在当前目录创建 config.yaml
webqa-agent init

# 指定输出路径
webqa-agent init -o myconfig.yaml

# 覆盖已存在的文件
webqa-agent init --force
```

#### run - 执行测试

```bash
# 自动发现配置文件（./config.yaml 或 ./config/config.yaml）
webqa-agent run

# 指定配置文件
webqa-agent run -c /path/to/config.yaml
```

#### ui - 可视化界面

WebQA Agent 提供了基于 Gradio 的可视化界面：

```bash
# 安装 Gradio
uv add "gradio>=5.44.0"

# 启动 Web UI（默认英文）
webqa-agent ui
# 访问地址：http://localhost:7860

# 启动中文界面
webqa-agent ui -l zh-CN

# 可选：自定义 host/port 且不自动打开浏览器
webqa-agent ui --host 0.0.0.0 --port 9000 --no-browser
```

### 🧠 推荐模型

| 模型 | 说明 |
|------|------|
| **gpt-4.1-2025-04-14** | 准确性与可靠性较高 |
| **gpt-4.1-mini-2025-04-14** | 经济实用 |
| **qwen3-vl-235b-a22b-instruct** | 开源模型，私有部署首选 |
| **doubao-seed-1-6-vision-250815** | 网页理解较优异，支持视觉 |

### 📊 查看结果

测试报告生成在 `reports/` 目录下，打开 HTML 文件即可查看详细结果。

## 🗺️ RoadMap

1. AI智能功能功能测试持续优化：提升覆盖率与准确性
2. 功能遍历与页面校验：校验业务逻辑正确性与数据完整性
3. 交互与可视化：实时展示推理过程
4. 能力扩展：多模型接入与更多评估维度集成

## 🙏 致谢

- [natbot](https://github.com/nat/natbot): 通过GPT-3驱动浏览器
- [Midscene.js](https://github.com/web-infra-dev/midscene/)：Web、Android、自动化和测试的AI Operator
- [browser-use](https://github.com/browser-use/browser-use/)：用于浏览器控制的AI Agent

## 📄 开源许可证

该项目采用 [Apache 2.0 开源许可证](LICENSE)