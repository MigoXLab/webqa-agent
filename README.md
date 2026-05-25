<!-- SEO Meta Information and Structured Data -->

<div itemscope itemtype="https://schema.org/SoftwareApplication" align="center" xmlns="http://www.w3.org/1999/html">
  <meta itemprop="name" content="WebQA Agent: Autonomous Web Testing & Quality Assurance">
  <meta itemprop="description" content="AI-powered autonomous web browser agent that audits performance, functionality, UX, and security for comprehensive website testing and quality assurance">
  <meta itemprop="applicationCategory" content="Web Testing Software">
  <meta itemprop="operatingSystem" content="Cross-platform">
  <meta itemprop="programmingLanguage" content="Python">
  <meta itemprop="url" content="https://github.com/MigoXLab/webqa-agent">
  <meta itemprop="softwareVersion" content="latest">
  <meta itemprop="license" content="Apache-2.0">
  <meta itemprop="keywords" content="vibecoding, web evaluation, autonomous, web testing, automation, AI testing, browser automation, quality assurance, performance testing, UX testing, security testing, functional testing">

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
  Join us on 🎮<a href="https://discord.gg/fG5QAxYyNr">Discord</a> | 💬<a href="https://aicarrier.feishu.cn/docx/NRNXdIirXoSQEHxhaqjchUfenzd">WeChat</a>
</p>

<p align="center"><a href="README.md">English</a> · <a href="README_zh-CN.md">简体中文</a></p>

<p align="center">
  If you like WebQA Agent, please give us a ⭐ on GitHub!
  <br/>
  <a href="https://github.com/MigoXLab/webqa-agent/stargazers" target="_blank">
    <img src="docs/images/star.gif" alt="Click Star" width="900">
  </a>
</p>

<p align="center">🤖 <strong>WebQA Agent</strong> is a fully automated web testing agent with multimodal page understanding — no test scripts required. <strong>Powered by ⚡ WebQA Flash mode</strong> — just describe your business goal in one sentence and the agent drives the browser to complete the test in seconds. ✨ Use it via GUI / CLI directly, or integrate seamlessly with Cursor, Claude Code, and OpenClaw via MCP / Skill.</p>
</div>

<!-- Additional SEO Keywords and Context
vibecoding, vibe coding, web evaluation, autonomous exploration, web testing automation, browser testing tool, AI-powered QA, automated web testing, website performance analysis, functional testing automation, user experience testing, UX, security vulnerability scanning, browser testing, web application testing, quality assurance automation, automated UI testing, web accessibility testing, performance monitoring, website audit tool, vibecoding testing, web development
-->

## 📑 Table of Contents

- [Core Features](#core-features)
- [Examples](#examples)
- [Quick Start](#quick-start)
- [CLI Usage](#cli-usage)
- [Deployment](#deployment)
- [RoadMap](#roadmap)
- [Acknowledgements](#acknowledgements)
- [License](#license)

## 🚀 Core Features

<a id="core-features"></a>

### 📋 Product Overview

**WebQA Agent** offers three testing forms—from lightweight exploration to deep regression:

| Capability       | ⚡ **WebQA Flash** (Default · Recommended)                                   | 🤖 **Standard Generate**                                   | 📋 **Run Mode**                                    |
| :--------------- | :--------------------------------------------------------------------------- | :--------------------------------------------------------- | :------------------------------------------------- |
| **Positioning**  | Lightweight exploration engine; natural-language goals in seconds            | AI discovery → dynamic generation → precise execution      | Execute YAML instructions with expected verification |
| **Use Cases**    | Quick smoke tests, IDE inline runs, platform Flash exploration, MCP/Skill NL tests | New feature exploration, full QA; **Focused** / **Explore** planning | Repeatable and regression testing                  |
| **User Input**   | One-sentence goal (or concurrent goal list)                                  | URL + optional objectives; platform picks **Focused** when goals are filled, **Explore** when empty | Structured natural-language steps                  |
| **Entry Points** | CLI `gen` + `engine: flash`, web dashboard, MCP `run_test`, Skill            | CLI `gen` + `engine: standard`, web dashboard              | CLI `run`, web dashboard                           |

**Usage & Deployment**: CLI (see [CLI Usage](#cli-usage)); full-stack deployment (Local / Docker / K8s) with Flash reports, API Key management, and one-click parameter backfill. See [Deployment](#deployment).

For a detailed comparison and configuration guides for standard modes, see **[docs/MODES&CLI.md](docs/MODES&CLI.md)**.

### ⚡ Flash Key Advantages

- **Second-scale execution, instant feedback**: No heavy offline planning, no lengthy test setup. Built on the lightweight Chrome DevTools MCP, the agent receives natural-language goals in real time and immediately drives the browser to interact and assert.
- **Zero selector maintenance**: Say goodbye to CSS selectors and XPath. Multimodal AI identifies page elements directly — when the UI is redesigned or styles change, the agent looks and clicks like a human would.
- **Native IDE & agent integration**: Ships with a standard MCP server. Issue test commands in natural language directly from **Cursor** or **Claude Code**, letting your AI coding assistant run the automation for you.

### 🧭 Architecture

<p>
  <img src="docs/images/webqa2.svg" alt="WebQA Agent Architecture" />
</p>

## 📹 Examples

<a id="examples"></a>

<p align="left">
  🎬 <a href="https://pub-2c31c87660254d7bba9707e2b56fc15b.r2.dev/gen-baidu.mp4" target="_blank">Watch Demo: One-click testing of Baidu.com</a>
</p>

## 🚀 Quick Start

<a id="quick-start"></a>

Choose between **🛠️ CLI Quick Start (Flash Mode)** or **🖥️ Full-stack Deployment (Web Dashboard)**.

### 🛠️ CLI Quick Start

Recommended: install via [uv](https://github.com/astral-sh/uv) (Python>=3.11). Flash mode drives the browser through [chrome-devtools-mcp](https://github.com/ChromeDevTools/chrome-devtools-mcp).

```bash
# 1) Create project and install
uv init my-webqa && cd my-webqa
uv add webqa-agent

# 2) Install Chrome browser & Chrome MCP pre-requisites
npm install -g chrome-devtools-mcp@latest  # Required for Flash mode

# 3) Initialize and Run (defaults to Flash mode)
uv run webqa-agent init      # Generates config.yaml (edit with your target URL & LLM API Key)
uv run webqa-agent gen       # Start testing
```

```yaml
target:
  url: https://example.com
  max_concurrent_tests: 2
test_config:
  business_objectives:
    - >
      Search for "laptop", click the first result and confirm the detail page loads,
      then go back and switch to the "Images" tab and verify the content is related.
    - Apply a price filter and verify all displayed results fall within the selected range
```

**Built-in skills** (loaded on demand, no extra config needed): `plan`, `ui-audit`, `recovery`, `nuclei-scan`, `button-check`. See [docs/MODES&CLI.md](docs/MODES&CLI.md#built-in-skills) for details.

### 🖥️ Full-stack Deployment (Recommended for Teams)

For visual dashboard, test management, and history, start with Docker Compose:

```bash
git clone https://github.com/MigoXLab/webqa-agent.git
cd webqa-agent/deploy/docker-compose
cp .env.example .env
# Edit .env: fill in your LLM API Key
./start.sh
```

> Access via `http://localhost`. For other deployment methods, see [Deployment](#deployment).

## ⚙️ CLI Usage

<a id="cli-usage"></a>

### CLI Parameter Details

WebQA Agent provides a concise command-line interface for initialization, autonomous exploration, case execution, and launching the Web UI.

| Command | Description                                        | Common Arguments                                                                                                   |
| :------ | :------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------- |
| `init`  | Initialize configuration file                      | `-m <gen/run>`: Specify mode; `-o <path>`: Output path; `--force`: Overwrite existing                              |
| `gen`   | **Generate/Flash Mode**: Autonomous test execution | `-c <path>`: Config path; `-w <n>`: Parallel workers; defaults to Flash engine (local Chrome via Chrome MCP)       |
| `run`   | **Run Mode**: Execute YAML-defined test cases      | `-c <path/dir>`: Config file or folder; `-w <n>`: Parallel workers; requires Standard engine (Playwright executor) |

For details on Standard Gen and Run modes, see **[docs/MODES&CLI.md](docs/MODES&CLI.md)**.

### 📊 View Results

Test reports are generated in the `reports/` directory. Open the HTML file to view detailed results.

______________________________________________________________________

### 🔌 MCP & Skill Integration

#### WebQA MCP Server

Expose browser testing to **Cursor**, **Claude Code**, and other IDEs via MCP. After install you get the `webqa-mcp-server` command.

**1. Install**

```bash
git clone https://github.com/MigoXLab/webqa-agent.git
cd webqa-agent
pip install -e .
which webqa-mcp-server
```

**2. API Key**

WebQA platform → **API Keys** → create key (shown once).

**3. IDE config (Cursor example)**

Settings → MCP → Add Server:

```json
{
  "mcpServers": {
    "webqa": {
      "command": "/absolute/path/to/webqa-mcp-server",
      "env": {
        "WEBQA_API_URL": "https://your-webqa-platform.com",
        "WEBQA_API_KEY": "wqa_xxxxxxxx..."
      }
    }
  }
}
```

Full tool reference: **[docs/MCP_SERVER.md](docs/MCP_SERVER.md)**.

#### WebQA Skill

The `skills/webqa/` package works with **OpenClaw** and **Claude Code** for natural-language browser tests without scripts.

- **Claude Code**: Add `skills/webqa` to your project Skills path or copy to `.claude/skills/webqa`.
- **OpenClaw**: Register `skills/webqa` per your OpenClaw Skill layout.

Key references: `skills/webqa/SKILL.md`, `skills/webqa/references/mini-agent.md`, `skills/webqa/references/setup.md`.

<a id="deployment"></a>

## 🖥️ Deployment

For teams that need a **persistent web dashboard** with test management, scheduled tasks, and execution history, deploy the full-stack platform.

**Platform highlights**:

- **Flash exploration**: End-to-end integration with screenshots and step-level report detail
- **API Key management**: Create MCP API keys for Cursor / Claude Code

Deployment options:

| Method            | Use Case                    | Guide                                                  |
| ----------------- | --------------------------- | ------------------------------------------------------ |
| Local Development | Personal dev & debugging    | [deploy/README.md](deploy/README.md#local-development) |
| Docker Compose    | Single-machine / Team trial | [deploy/README.md](deploy/README.md#docker-compose)    |
| Kubernetes        | Production cluster          | [deploy/k8s/README.md](deploy/k8s/README.md)           |

> **💡 Extending Internal Logic:** WebQA Agent supports extending internal logic based on your team's infrastructure (such as integrating internal SSO, OSS object storage, internal LLMs, etc.). You are free to customize and develop it to fit your needs. [deploy/README.md](deploy/README.md#custom-extensions)

> **Note:** The web dashboard platform is currently only available in Chinese.

<a id="roadmap"></a>

## 🗺️ RoadMap

1. **Interaction & Visualization**: Display the agent's reasoning chain and decision rationale in real time during test execution, so users can immediately understand why the AI took a particular path and adjust their business-goal descriptions and prompts accordingly (currently only post-hoc replay in the report).
2. **Flash multi-step cases**: Extend "one-sentence goal → single case chain" into a structured execution model with **precondition / steps / assertions**, enabling regression testing, failure localization, and cross-run reuse for complex scenarios (currently runs user input as a single case chain).
3. **Explore mode enhancement**: Persist the agent's broad-discovery findings (under no-PRD scenarios) into a structured, reusable test case library, closing the loop from discovery to regression instead of leaving one-off exploration reports (currently broad discovery, results not persisted).

<a id="acknowledgements"></a>

## 🙏 Acknowledgements

- [natbot](https://github.com/nat/natbot): Drive a browser with GPT-3
- [Midscene.js](https://github.com/web-infra-dev/midscene/): AI Operator for Web, Android, Automation & Testing
- [browser-use](https://github.com/browser-use/browser-use/): AI Agent for Browser control
- [cc-mini](https://github.com/e10nMa2k/cc-mini): Ultra-light Python harness for agentic Claude Code workflows; provides the core engine, MCP client, skill registry, and cookie-management layer that powers WebQA Agent's Flash execution mode

## 📄 License

<a id="license"></a>

This project is licensed under the [Apache 2.0 License](LICENSE).
