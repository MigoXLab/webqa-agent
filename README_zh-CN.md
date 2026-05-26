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

<p align="center">🤖 <strong>WebQA Agent</strong> 是全自动网页评估测试 Agent，具备多模态网页理解能力，无需编写任何测试脚本。<strong>主打 ⚡ WebQA Flash 模式</strong>——只需一句话业务目标，秒级自动驱动浏览器完成测试；✨ 支持 GUI / CLI 直接使用，并通过 MCP / Skill 无缝接入 Cursor、Claude Code 与 OpenClaw 等 IDE 与智能体框架。</p>
</div>

<!-- Additional SEO Keywords and Context
Vibecoding, Vibe coding, 网页测试自动化, 浏览器测试工具, AI驱动质量保障, 自动化网页测试, 网站性能分析, 功能测试自动化, 用户体验测试, 安全漏洞扫描, 浏览器测试, 网页应用测试, 自动化UI测试, 网页可访问性测试, 性能监控, 网站审计工具, 智能测试用例生成, 端到端测试, 回归测试, 兼容性测试, Vibecoding测试, 网页开发
-->

## 📑 目录

- [核心特性](#核心特性)
- [示例演示](#示例演示)
- [快速开始](#快速开始)
- [CLI 使用说明](#cli-使用说明)
- [全栈部署](#全栈部署)
- [RoadMap](#roadmap)
- [致谢](#致谢)
- [开源许可证](#开源许可证)

## 🚀 核心特性

<a id="核心特性"></a>

### 📋 功能介绍

**WebQA Agent** 覆盖从轻量探索到深度回归的全链路 QA：

| 能力         | ⚡ **WebQA Flash**（默认推荐）                                | 🤖 **标准 Generate 模式**                                                    | 📋 **Run 模式**              |
| :----------- | :------------------------------------------------------------ | :--------------------------------------------------------------------------- | :--------------------------- |
| **定位**     | 轻量级探索引擎，秒级执行自然语言测试目标                      | AI 自主探索 → 动态生成 → 精确执行                                            | 依据 YAML 指令执行和预期验证 |
| **适用场景** | 快速冒烟、IDE 内联调、平台 Flash 探索、MCP/Skill 自然语言测试 | 新功能探索、全面质量保障、Focused/Explore 深度规划                           | 可重复、可回归的测试场景     |
| **用户输入** | 一句话业务目标（或目标列表并发）                              | URL + 可选业务目标；平台在填写目标时使用 **Focused**，留空时使用 **Explore** | 结构化自然语言步骤           |
| **入口**     | CLI `gen` + `engine: flash`、Web 平台、MCP `run_test`、Skill  | CLI `gen` + `engine: standard`、Web 平台                                     | CLI `run`、Web 平台          |

**使用与部署**：支持 CLI 命令行（见 [CLI 使用说明](#cli-使用说明)）；支持全栈部署（Local / Docker / K8s）进行可视化管理，含 Flash 探索报告、API Key 管理、一键参数回填。详见 [全栈部署](#全栈部署)。

### ⚡ Flash 核心优势

- **秒级执行，极速反馈**：无需笨重的离线规划与漫长的测试准备。基于轻量级 Chrome DevTools MCP，实时接收自然语言目标，即时驱动浏览器进行交互与断言。
- **零 Selector 维护成本**：彻底告别 CSS 选择器与 XPath。AI 多模态智能识别页面元素——界面改版、样式变更，AI 会像人类一样自己看、自己点击。
- **原生 IDE 与智能体协同**：提供标准 MCP Server，直接在 **Cursor**、**Claude Code** 中用自然语言下达测试指令，让 AI 编码助手帮你跑自动化测试。

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

### 🛠️ 命令行快速上手

推荐使用 [uv](https://github.com/astral-sh/uv) (Python>=3.11) 安装；Flash 模式底层通过 [chrome-devtools-mcp](https://github.com/ChromeDevTools/chrome-devtools-mcp) 驱动浏览器。

```bash
# 1) 创建项目并安装包
uv init my-webqa && cd my-webqa
uv add webqa-agent

# 2) 安装 chrome browser & Chrome MCP 前置依赖
npm install -g chrome-devtools-mcp@latest  # Flash 模式必需

# 3) 初始化并运行 (默认即启用 Flash 模式)
uv run webqa-agent init      # 初始化配置 config.yaml (编辑填入 URL 和 LLM API Key)
uv run webqa-agent gen       # 启动测试
```

```yaml
# 多条目标——并发执行（同步设置 max_concurrent_tests）
target:
  url: https://example.com
  max_concurrent_tests: 2
test_config:
  business_objectives:
    - >
      在搜索框输入"笔记本电脑"，点击第一条结果确认详情页正常打开，
      返回后切换到"图片"子频道，验证内容与搜索词相关且页面无报错。
    - 使用价格筛选功能，验证过滤后的结果均符合所选价格区间
```

**内置 Skill**（按需加载，无需额外配置）：`plan`、`ui-audit`、`recovery`、`nuclei-scan`、`button-check`。详见 [docs/MODES&CLI_zh-CN.md](docs/MODES&CLI_zh-CN.md)。

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

## ⚙️ CLI 使用说明

<a id="cli-使用说明"></a>

### CLI 参数说明

WebQA Agent 提供简洁的命令行工具，支持初始化、自动探索、用例执行及 Web UI 启动。

| 命令   | 说明                                   | 常用参数                                                                                                     |
| :----- | :------------------------------------- | :----------------------------------------------------------------------------------------------------------- |
| `init` | 初始化配置文件                         | `-m <gen/run>`: 指定模式；`-o <path>`: 输出路径；`--force`: 强制覆盖                                         |
| `gen`  | **探索/Flash 模式**：AI 自动执行用例   | `-c <path>`: 指定配置文件；`-w <n>`: 并发 Worker 数；默认启用 Flash 引擎（本地 Chrome 通过 Chrome MCP 执行） |
| `run`  | **执行模式**：运行 YAML 定义的测试用例 | `-c <path/dir>`: 指定文件或文件夹；`-w <n>`: 并发 Worker 数；需要 Standard 引擎（Playwright 执行器）         |

关于标准探索模式 (Standard Gen) 与执行模式 (Run) 的详细配置说明，请参考 **[docs/MODES&CLI_zh-CN.md](docs/MODES&CLI_zh-CN.md)**。

### 📊 查看结果

测试报告生成在 `reports/` 目录下，打开 HTML 文件即可查看详细结果。

______________________________________________________________________

### 🔌 MCP 与 Skill 集成

#### WebQA MCP Server

通过 MCP 协议将浏览器测试能力暴露给 **Cursor**、**Claude Code** 等 IDE。安装后即可使用 `webqa-mcp-server` 命令。

**1. 安装**

```bash
git clone https://github.com/MigoXLab/webqa-agent.git
cd webqa-agent
pip install -e .
which webqa-mcp-server   # 获取绝对路径
```

**2. 获取 API Key**

进入 WebQA 平台 → **API Keys** → 创建密钥（仅显示一次）。

**3. IDE 中添加 Server**（以 Cursor 为例：Settings → MCP → Add Server）：

```json
{
  "mcpServers": {
    "webqa": {
      "command": "/您的绝对路径/webqa-mcp-server",
      "env": {
        "WEBQA_API_URL": "https://your-webqa-platform.com",
        "WEBQA_API_KEY": "wqa_xxxxxxxx..."
      }
    }
  }
}
```

完整工具说明参考：**[docs/MCP_SERVER.md](docs/MCP_SERVER.md)**。

#### WebQA Skill

`skills/webqa/` 提供即插即用的 Skill 包，配合 **OpenClaw** 与 **Claude Code** 实现无脚本的自然语言测试。

- **Claude Code**：将 `skills/webqa` 加入项目的 Skills 路径，或复制到 `.claude/skills/webqa`。
- **OpenClaw**：按 OpenClaw Skill 规范注册 `skills/webqa`。

参考文档：`skills/webqa/SKILL.md`、`skills/webqa/references/mini-agent.md`、`skills/webqa/references/setup.md`。

<a id="全栈部署"></a>

## 🖥️ 全栈部署

如果团队需要一个**持续使用的 Web 管理平台**（测试管理、定时任务、执行历史），可以部署完整的前后端服务。

**平台能力**：

- **Flash 探索**：前后端打通，报告含截图与逐步执行详情
- **API Key 管理**：申请与管理 MCP API Key，供 Cursor / Claude Code 接入

我们支持三种部署方式：

| 方式           | 适用场景            | 参考文档                                                        |
| -------------- | ------------------- | --------------------------------------------------------------- |
| 本地开发       | 个人开发调试        | [deploy/README_zh-CN.md](deploy/README_zh-CN.md#本地开发)       |
| Docker Compose | 单机部署 / 团队试用 | [deploy/README_zh-CN.md](deploy/README_zh-CN.md#docker-compose) |
| Kubernetes     | 生产集群            | [deploy/k8s/README.md](deploy/k8s/README.md)                    |

> **💡 扩展内部逻辑：** WebQA Agent 支持根据团队基础设施扩展内部逻辑（如接入内部的 SSO 单点登录、OSS 对象存储、内部大模型等），您可以自由进行定制和二次开发。[deploy/README_zh-CN.md](deploy/README_zh-CN.md#自定义扩展)

> **注意：** 当前 Web 管理平台仅提供中文界面。

<a id="roadmap"></a>

## 🗺️ RoadMap

1. **交互与可视化**：在测试执行过程中实时展示 Agent 的推理链与决策依据，便于用户即时理解 AI 为何选择某条路径，并据此优化业务目标描述与 prompt（当前仅支持报告侧事后回溯）。
2. **Flash 多步骤 case**：将「一句话业务目标 → 单一 case 链路」扩展为支持「前置条件 / 步骤 / 断言」的结构化执行模型，便于复杂场景的回归测试、失败定位与跨执行复用（当前以用户输入作为单一 case 链路）。
3. **Explore 模式增强**：将 Agent 在无 PRD 场景下广覆盖发现的结果沉淀为结构化、可复用的测试用例库，让「发现 → 回归」形成闭环，而非一次性的探索报告（当前由 Agent 广覆盖发现，结果不入库）。

<a id="致谢"></a>

## 🙏 致谢

- [natbot](https://github.com/nat/natbot): 通过GPT-3驱动浏览器
- [Midscene.js](https://github.com/web-infra-dev/midscene/)：Web、Android、自动化和测试的AI Operator
- [browser-use](https://github.com/browser-use/browser-use/)：用于浏览器控制的AI Agent
- [cc-mini](https://github.com/e10nMa2k/cc-mini)：面向 Claude Code Agent 工作流的超轻量 Python 框架；为 WebQA Agent 的 Flash 执行模式提供核心引擎、MCP 客户端、技能注册表和 Cookie 管理层

<a id="开源许可证"></a>

## 📄 开源许可证

该项目采用 [Apache 2.0 开源许可证](LICENSE)。
