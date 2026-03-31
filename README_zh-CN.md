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

<p align="center">
  <img src="docs/images/logo-title.svg" alt="WebQA Agent" height="80" />
</p>

<!-- badges -->

<p align="center">
  <a href="https://github.com/MigoXLab/webqa-agent/blob/main/LICENSE"><img src="https://img.shields.io/github/license/MigoXLab/webqa-agent" alt="License"></a>
  <a href="https://github.com/MigoXLab/webqa-agent/stargazers"><img src="https://img.shields.io/github/stars/MigoXLab/webqa-agent" alt="GitHub stars"></a>
  <a href="https://github.com/MigoXLab/webqa-agent/network/members"><img src="https://img.shields.io/github/forks/MigoXLab/webqa-agent" alt="GitHub forks"></a>
  <a href="https://github.com/MigoXLab/webqa-agent/issues"><img src="https://img.shields.io/github/issues/MigoXLab/webqa-agent" alt="GitHub issues"></a>
  <a href="https://deepwiki.com/MigoXLab/webqa-agent"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"></a>
</p>

<p align="center">
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

<p align="center">🤖 <strong>WebQA Agent</strong> 是全自动网页评估测试 Agent，具备多模态网页理解、智能生成测试用例、精准执行的核心能力，一键完成性能、功能与交互体验的全面测试评估 ✨ 支持 GUI/CLI 直接使用，且支持 OpenClaw Skill 调用</p>
</div>

<!-- Additional SEO Keywords and Context
Vibecoding, Vibe coding, 网页测试自动化, 浏览器测试工具, AI驱动质量保障, 自动化网页测试, 网站性能分析, 功能测试自动化, 用户体验测试, 安全漏洞扫描, 浏览器测试, 网页应用测试, 自动化UI测试, 网页可访问性测试, 性能监控, 网站审计工具, 智能测试用例生成, 端到端测试, 回归测试, 兼容性测试, Vibecoding测试, 网页开发
-->

## 📑 目录

- [核心特性](#核心特性)
- [示例演示](#示例演示)
- [快速开始](#快速开始)
- [CLI 使用说明](#cli-使用说明)
- [扩展 WebQA Agent 工具](#扩展-webqa-agent-工具)
- [全栈部署](#全栈部署)
- [RoadMap](#roadmap)
- [致谢](#致谢)
- [开源许可证](#开源许可证)

## 🚀 核心特性

<a id="核心特性"></a>

### 📋 功能介绍

**WebQA-Agent** 提供两种测试模式，满足不同场景需求: **🤖 自动探索模式**和 **📋 执行模式**

| 能力         | 🤖 **自动探索模式 (Generate模式)**                                         | 📋 **执行模式 (Run模式)**                                             |
| :----------- | :------------------------------------------------------------------------- | :-------------------------------------------------------------------- |
| **核心特性** | AI 自主探索 -> 动态生成 -> 精确执行                                        | 依据指令执行和预期验证                                                |
| **适用场景** | 新功能探索、全面质量保障                                                   | 适合可重复、可回归的测试场景                                          |
| **用户输入** | **极简**：只需 URL 或一句话业务目标                                        | **结构化**：简单的自然语言步骤描述                                    |
| **优势**     | 具备反思能力，自适应 UI 变化；配置功能/性能/安全/UX 评估，提供全面质量保障 | 结果稳定可预期，摆脱繁琐的Selector维护；实时监控 Console/Network 状态 |

**使用与部署**：支持 CLI 命令行运行，可参考 [CLI 使用说明](#cli-使用说明)；同时支持以完整前后端形态部署（Local / Docker / K8s），通过 Web 界面进行可视化管理。详见 [全栈部署](#全栈部署)。

### 🛠️ 工具系统

**默认工具**（始终启用）：

- **UI 操作**: 浏览器交互（点击、输入、导航）
- **UI 断言**: 状态验证
- **UX 验证**: 文本错误检查、布局分析

**自定义工具**（可选，通过配置启用）：

- **性能测试**: 基于 Lighthouse 的性能测试
- **安全测试**: Nuclei 漏洞扫描
- **链接检测**: 动态链接发现

在 `config.yaml` 中启用自定义工具：

```yaml
test_config:
  custom_tools:
    enabled:
      - lighthouse
      - nuclei
```

### 🧭 架构图

<p>
  <img src="docs/images/webqa2.svg" alt="WebQA Agent 架构图" />
</p>

## 📹 示例演示

<a id="示例演示"></a>

<p align="left">
  🎬 <a href="https://pub-2c31c87660254d7bba9707e2b56fc15b.r2.dev/gen-baidu.mp4" target="_blank">查看演示：百度网站一键测试</a>
</p>

## 🚀 快速开始

<a id="快速开始"></a>

您可以根据需求选择 **🛠️ 命令行快速上手** 或 **🖥️ 全栈部署 (Web 管理平台)**。

### 🛠️ 命令行快速上手 (推荐开发者使用)

推荐使用 [uv](https://github.com/astral-sh/uv) (Python>=3.11) 安装:

```bash
# 1) 创建项目并安装包
uv init my-webqa && cd my-webqa
uv add webqa-agent

# 2) 安装浏览器（必需）
uv run playwright install chromium

# 3) 自动探索模式 (Generate)
uv run webqa-agent init -m gen  # 初始化配置，编辑 config.yaml 填入 URL 和 API Key
uv run webqa-agent gen          # 启动 AI 自动测试

# 4) 执行模式 (Run)
uv run webqa-agent init -m run  # 初始化配置，编写自然语言测试用例
uv run webqa-agent run          # 启动测试执行
```

> 详见 [CLI 使用说明](#cli-使用说明) 获取更多 CLI 参数。

### 🖥️ 全栈部署 (推荐团队使用)

如果您需要可视化界面、测试管理和执行历史，请使用 Docker Compose 一键启动：

```bash
git clone https://github.com/MigoXLab/webqa-agent.git
cd webqa-agent/deploy/docker-compose
cp .env.example .env
# 编辑 .env 文件，填入您的 LLM API Key
./start.sh
```

> 启动后访问 `http://localhost`。其他部署方式请查看 [全栈部署](#全栈部署)。

<a id="使用说明"></a>

## ⚙️ CLI 使用说明

<a id="cli-使用说明"></a>

### CLI 参数说明

WebQA Agent 提供简洁的命令行工具，支持初始化、自动探索、用例执行及 Web UI 启动。

| 命令   | 说明                                    | 常用参数                                                             |
| :----- | :-------------------------------------- | :------------------------------------------------------------------- |
| `init` | 初始化配置文件                          | `-m <gen/run>`: 指定模式；`-o <path>`: 输出路径；`--force`: 强制覆盖 |
| `gen`  | **自动探索模式**：AI 自动生成并执行用例 | `-c <path>`: 指定配置文件；`-w <n>`: 并发 Worker 数                  |
| `run`  | **执行模式**：运行 YAML 定义的测试用例  | `-c <path/dir>`: 指定文件或文件夹；`-w <n>`: 并发 Worker 数          |

**示例：**

```bash
# 初始化 Run 模式配置
webqa-agent init -m run

# 以 4 并发运行指定目录下的所有测试用例
webqa-agent run -c ./my_cases -w 4
```

______________________________________________________________________

### Generate 模式 - 配置介绍

#### 🔧 可选依赖项 (自定义工具)

- 性能测试（Lighthouse）：`npm install lighthouse chrome-launcher`（需 Node.js ≥18）
- 安全测试（Nuclei）：

```bash
  brew install nuclei      # macOS
  nuclei -ut               # 更新模板
  # Linux/Windows: https://github.com/projectdiscovery/nuclei/releases
```

#### 📄 配置文件说明

配置文件需包含 `test_config` 字段，用于定义需要执行的测试类型。

- **业务目标**: 指定测试的业务目标，以指导 AI 规划测试重点和覆盖范围。
- **自定义工具**: 可选启用性能（Lighthouse）、安全（Nuclei）、按钮检查、链接检测等工具。
- **动态步骤生成**: 启用后，在执行过程中检测到新的 UI 元素时，会自动生成额外的测试步骤。
- **过滤模型**: 配置一个轻量级模型，用于预过滤页面元素，从而提高规划效率。

更多教程，请参考 [docs/MODES&CLI_zh-CN.md](docs/MODES&CLI_zh-CN.md)

```yaml
target:
  url: https://example.com              # 需要测试的网站 URL
  description: 网站质量保证测试

test_config:
  business_objectives: 测试搜索功能，生成3个测试用例
  custom_tools:                         # 可选：启用自定义测试工具（通过 step_type）
    enabled:
      # - lighthouse                    # Lighthouse 性能测试
                                        # 需要：npm install lighthouse chrome-launcher（本地，推荐）
                                        # 或：npm install -g lighthouse chrome-launcher（全局）
      # - nuclei                        # Nuclei 安全扫描
                                        # 需要：go install -v github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest
                                        # 或从以下地址下载：https://github.com/projectdiscovery/nuclei/releases
      # - traverse_clickable_elements   # 可点击元素遍历测试
      # - detect_dynamic_links          # 动态链接发现和验证

llm_config:                             # LLM 配置，支持 OpenAI、Anthropic Claude、Google Gemini 以及 OpenAI 兼容格式模型（如豆包、通义千问等）
  model: gpt-5.4                        # 主模型
  filter_model: gpt-5-mini              # 轻量级模型用于元素过滤（可选）
  api_key: your_api_key                 # 或通过环境变量设置 (OPENAI_API_KEY)
  base_url: https://api.openai.com/v1   # 可选，API 端点。对于 OpenAI 兼容格式模型（豆包、通义千问等），设置为对应的 API 端点

browser_config:
  headless: False                       # Docker 环境自动设为 True
  language: en-US

report:
  language: en-US                       # zh-CN 或 en-US
```

### Run 模式 - 配置介绍

Run 模式配置文件需包含 `cases` 字段，用于定义具体的测试用例。

- **多模态 AI 交互式能力**：使用 `action` 描述页面上可见的文字、图片或相对位置。支持浏览器操作：点击、悬停、输入、清空、键盘按键、页面滚动、鼠标移动和滚轮滚动、文件上传、拖拽、等待等；以及页面操作：跳转url、页面后退。
- **多模态 AI 验证能力**：使用 `verify`，确保 Agent 没“跑偏”。校验页面符合预期：视觉内容确认、URL 与路径校验、组合图片和页面元素验证等。
- **全链路自动监控**：获取浏览器的 `Console` 日志和 `Network` 请求状态，同时支持配置 `ignore_rules` 来忽略已知的浏览器 console 和 network 错误。

更多教程和测试用例编写规范，请参考 [docs/MODES&CLI_zh-CN.md](docs/MODES&CLI_zh-CN.md)

```yaml
target:
  url: https://example.com              # 目标网站 URL

llm_config:                             # LLM 配置
  api: openai
  model: gpt-5-mini
  api_key: your_api_key_here
  base_url: https://api.openai.com/v1

browser_config:
  viewport: {"width": 1280, "height": 720}
  headless: False                       # Docker 环境自动设为 True
  language: en-US
  # cookies: /path/to/cookie.json

ignore_rules:                           # 忽略规则配置（可选）
  network:                              # 网络请求忽略规则
    - pattern: ".*\\.google-analytics\\.com.*"
      type: "domain"
  console:                              # 控制台日志忽略规则
    - pattern: "Failed to load resource.*favicon"
      match_type: "regex"
    - pattern: "Warning:"
      match_type: "contains"

cases:                                  # 测试用例列表
  - name: 图片上传                       # 用例名称
    steps:                              # 测试步骤
      - action: 上传图标是输入框内的图片图标，位于百度搜索按钮旁边，用于上传文件
        args:
          file_path: ./tests/data/test.jpeg
      - action: 等待图像上传
      - verify: 验证输入字段是否显示张开的手掌/手图标图像
      - action: 输入"图片中有多少根手指？"在搜索输入框中，然后按Enter键，等待2秒
```

### 📊 查看结果

测试报告生成在 `reports/` 目录下，打开 HTML 文件即可查看详细结果。

<a id="扩展-webqa-agent-工具"></a>

## 🛠️ 扩展 WebQA Agent 工具

WebQA Agent 支持**自定义工具开发**，满足特定领域的测试需求。

| 文档                                                        | 描述                                  |
| ----------------------------------------------------------- | ------------------------------------- |
| **[自定义工具开发](docs/CUSTOM_TOOL_DEVELOPMENT_zh-CN.md)** | 自定义工具开发快速参考                |
| **[LLM 上下文文档](docs/CUSTOM_TOOL_DEVELOPMENT_AI.md)**    | AI 辅助开发的完整指南，可用于氛围编程 |

欢迎贡献！查看[现有工具示例](webqa_agent/tools/custom/)获取参考。

<a id="全栈部署"></a>

## 🖥️ 全栈部署

如果团队需要一个**持续使用的 Web 管理平台**（测试管理、定时任务、执行历史），可以部署完整的前后端服务。我们支持三种部署方式：

| 方式           | 适用场景            | 参考文档                                                        |
| -------------- | ------------------- | --------------------------------------------------------------- |
| 本地开发       | 个人开发调试        | [deploy/README_zh-CN.md](deploy/README_zh-CN.md#本地开发)       |
| Docker Compose | 单机部署 / 团队试用 | [deploy/README_zh-CN.md](deploy/README_zh-CN.md#docker-compose) |
| Kubernetes     | 生产集群            | [deploy/k8s/README.md](deploy/k8s/README.md)                    |

> **💡 扩展内部逻辑：** WebQA Agent 支持根据团队基础设施扩展内部逻辑（如接入内部的 SSO 单点登录、OSS 对象存储、内部大模型等），您可以自由进行定制和二次开发。[deploy/README_zh-CN.md](deploy/README_zh-CN.md#自定义扩展)

> **注意：** 当前 Web 管理平台仅提供中文界面。

<a id="roadmap"></a>

## 🗺️ RoadMap

1. **交互与可视化**：实时展示推理过程
2. Gen模式能力扩展：更多评估维度集成
3. Tool Agent上下文接入，更全面更精确的执行

<a id="致谢"></a>

## 🙏 致谢

- [natbot](https://github.com/nat/natbot): 通过GPT-3驱动浏览器
- [Midscene.js](https://github.com/web-infra-dev/midscene/)：Web、Android、自动化和测试的AI Operator
- [browser-use](https://github.com/browser-use/browser-use/)：用于浏览器控制的AI Agent

## 📄 开源许可证

该项目采用 [Apache 2.0 开源许可证](LICENSE)
