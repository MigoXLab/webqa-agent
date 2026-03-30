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

<p align="center">🤖 <strong>WebQA Agent</strong> is a fully automated web testing agent that understands the web like a human — generating test cases, evaluating functionality, performance, and UX end-to-end. ✨ Available as GUI/CLI for direct use, or as an OpenClaw skill. </p>
</div>

<!-- Additional SEO Keywords and Context
vibecoding, vibe coding, web evaluation, autonomous exploration, web testing automation, browser testing tool, AI-powered QA, automated web testing, website performance analysis, functional testing automation, user experience testing, UX, security vulnerability scanning, browser testing, web application testing, quality assurance automation, automated UI testing, web accessibility testing, performance monitoring, website audit tool, vibecoding testing, web development
-->

## 📑 Table of Contents

- [Core Features](#core-features)
- [Examples](#examples)
- [Quick Start](#quick-start)
- [CLI Usage](#cli-usage)
- [Extending WebQA Agent Tools](#extending-webqa-agent-tools)
- [Deployment](#deployment)
- [RoadMap](#roadmap)
- [Acknowledgements](#acknowledgements)
- [License](#license)

## 🚀 Core Features

<a id="core-features"></a>

### 📋 Feature Overview

**WebQA-Agent** provides two testing modes to support different scenarios **🤖 Generate Mode** and **📋 Run Mode**.

| Capability        | 🤖 **Generate Mode**                                                                           | 📋 **Run Mode**                                                                           |
| :---------------- | :--------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------- |
| **Core Features** | AI-driven discovery -> Dynamic generation -> Precise execution                                 | Execute based on instructions and expected verification                                   |
| **Use Cases**     | New feature, comprehensive quality assurance                                                   | Repeatable and regression testing scenarios                                               |
| **User Input**    | **Minimal**: Only URL or a one-sentence business goal                                          | **Structured**: Simple natural language step descriptions                                 |
| **Advantages**    | Reflection-based planning, adaptive to UI changes; Configurable functional / performance / security / UX evaluation for comprehensive QA | Stable and predictable results; No selector maintenance; Real-time Console and Network monitoring |

**Usage & Deployment**: Supports CLI execution (see [CLI Usage](#cli-usage)); also supports full-stack deployment (Local / Docker / K8s) with a web interface for visual management. See [Deployment](#deployment).

### 🛠️ Tool System

**Default Tools** (Always Enabled):

- **UI Actions**: Browser interactions (click, type, navigate)
- **UI Assertions**: State verification
- **UX Verification**: Text typo checking, layout analysis

**Custom Tools** (Optional, Configuration-Enabled):

- **Performance**: Lighthouse-based performance testing
- **Security**: Nuclei vulnerability scanning
- **Link Detection**: Dynamic link discovery

Enable custom tools in `config.yaml`:

```yaml
test_config:
  custom_tools:
    enabled:
      - lighthouse
      - nuclei
```

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

Choose between **🛠️ CLI Quick Start** or **🖥️ Full-stack Deployment (Web Dashboard)**.

### 🛠️ CLI Quick Start (Recommended for Developers)

Recommended using [uv](https://github.com/astral-sh/uv) (Python>=3.11):

```bash
# 1) Create project and install
uv init my-webqa && cd my-webqa
uv add webqa-agent

# 2) Install browser (Required)
uv run playwright install chromium

# 3) Generate Mode
uv run webqa-agent init -m gen  # Init config, edit config.yaml with URL & API Key
uv run webqa-agent gen          # Start AI-driven testing

# 4) Run Mode
uv run webqa-agent init -m run  # Init config, write natural language cases
uv run webqa-agent run          # Start execution
```

> See [CLI Usage](#cli-usage) for more CLI details.

### 🖥️ Full-stack Deployment (Recommended for Teams)

For visual dashboard, test management, and history, start with Docker Compose:

```bash
git clone https://github.com/MigoXLab/webqa-agent.git
cd webqa-agent/deploy/docker-compose
cp .env.example .env
# Edit .env: fill in your LLM API Key
./start.sh
```

> Access via `http://localhost:3000`. For other deployment methods, see [Deployment](#deployment).

<a id="usage"></a>

## ⚙️ CLI Usage

<a id="cli-usage"></a>

### CLI Parameter Details

WebQA Agent provides a concise command-line interface for initialization, autonomous exploration, case execution, and launching the Web UI.

| Command | Description                                              | Common Arguments                                                                      |
| :------ | :------------------------------------------------------- | :------------------------------------------------------------------------------------ |
| `init`  | Initialize configuration file                            | `-m <gen/run>`: Specify mode; `-o <path>`: Output path; `--force`: Overwrite existing |
| `gen`   | **Generate Mode**: AI-driven test generation & execution | `-c <path>`: Config path; `-w <n>`: Parallel workers                                  |
| `run`   | **Run Mode**: Execute YAML-defined test cases            | `-c <path/dir>`: Config file or folder; `-w <n>`: Parallel workers                    |

**Examples:**

```bash
# Initialize Run mode configuration
webqa-agent init -m run

# Run all cases in a directory with 4 parallel workers
webqa-agent run -c ./my_cases -w 4
```

______________________________________________________________________

### Generate Mode - Configuration

#### 🔧 Optional Dependencies (Custom Tools)

- Performance testing (Lighthouse): `npm install lighthouse chrome-launcher` (requires Node.js ≥18)
- Security testing (Nuclei):

```bash
  brew install nuclei      # macOS
  nuclei -ut               # Update templates
  # Linux/Windows: https://github.com/projectdiscovery/nuclei/releases
```

#### 📄 Configuration Details

The configuration file must include the `test_config` field to define test types.

- **Business Objectives**: Specifies business goals to steer AI test focus and coverage.
- **Custom Tools**: Optional tools like Performance (Lighthouse), Security (Nuclei), button checks, and link detection.
- **Dynamic Step Generation**: Automatically generates additional test steps when new UI elements are detected during execution.
- **Filter Model**: Configures a lightweight model for pre-filtering page elements to improve planning efficiency.

For more details, please refer to [docs/MODES&CLI.md](docs/MODES&CLI.md)

```yaml
target:
  url: https://example.com              # Website URL to test
  description: Website QA testing

test_config:
  business_objectives: Test search functionality, generate 3 test cases
  custom_tools:                         # Optional: Enable custom testing tools (by step_type)
    enabled:
      # - lighthouse                    # Lighthouse performance testing
                                        # Requires: npm install lighthouse chrome-launcher (local, recommended)
                                        # or: npm install -g lighthouse chrome-launcher (global)
      # - nuclei                        # Nuclei security scanning
                                        # Requires: go install -v github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest
                                        # or download from: https://github.com/projectdiscovery/nuclei/releases
      # - traverse_clickable_elements   # Clickable element traversal testing
      # - detect_dynamic_links          # Dynamic link discovery and validation

llm_config:                             # LLM configuration, supports OpenAI, Anthropic Claude, Google Gemini, and OpenAI-compatible models (e.g., Doubao, Qwen)
  model: gpt-5.4                        # Primary model
  filter_model: gpt-5-mini              # Lightweight model for element filtering (optional)
  api_key: your_api_key                 # Or set via environment variable (OPENAI_API_KEY)
  base_url: https://api.openai.com/v1   # Optional, API endpoint. For OpenAI-compatible models (Doubao, Qwen, etc.), set to their API endpoint

browser_config:
  headless: False                       # Auto True in Docker
  language: en-US

report:
  language: en-US                       # zh-CN or en-US
```

### Run Mode - Configuration

Run Mode configuration must include the `cases` field.

- **Multi-modal Interaction**: Use `action` to describe visible text, images, or relative positions on the page. Supported browser actions include click, hover, input, clear, keyboard input, scrolling, mouse movement, file upload, drag-and-drop, and wait; page actions include navigation, back.
- **Multi-modal Verification**: Use `verify` to ensure the agent stays on track, validating visual content, URLs, paths, and combined image–element conditions.
- **End-to-End Monitoring**: Monitoring `Console` logs and `Network` request status, and supporting configuration of `ignore_rules` to ignore known errors.

For more details and test case writing specifications, please refer to [docs/MODES&CLI.md](docs/MODES&CLI.md)

```yaml
target:
  url: https://example.com              # Target website URL

llm_config:                             # LLM configuration
  api: openai
  model: gpt-5-mini
  api_key: your_api_key_here
  base_url: https://api.openai.com/v1

browser_config:
  viewport: {"width": 1280, "height": 720}
  headless: False                       # Auto True in Docker
  language: en-US
  # cookies: /path/to/cookie.json

ignore_rules:                           # Ignore rules configuration (optional)
  network:                              # Network request ignore rules
    - pattern: ".*\\.google-analytics\\.com.*"
      type: "domain"
  console:                              # Console log ignore rules
    - pattern: "Failed to load resource.*favicon"
      match_type: "regex"
    - pattern: "Warning:"
      match_type: "contains"

cases:                                  # Test case list
  - name: Image Upload                  # Test case name
    steps:                              # Test steps
      - action: Upload icon is the image icon in the input box, located next to the Baidu search button, used for uploading files
        args:
          file_path: ./tests/data/test.jpeg
      - action: Wait for image upload
      - verify: Verify that the input field displays an open palm/hand icon image
      - action: Enter "How many fingers are in the image?" in the search input box, then press Enter, wait 2 seconds
```

### 📊 View Results

Test reports are generated in the `reports/` directory. Open the HTML file to view detailed results.

<a id="extending-webqa-agent-tools"></a>

## 🛠️ Extending WebQA Agent Tools

WebQA Agent supports **custom tool development** for domain-specific testing capabilities.

| Document                                                       | Description                                                             |
| -------------------------------------------------------------- | ----------------------------------------------------------------------- |
| **[Custom Tool Development](docs/CUSTOM_TOOL_DEVELOPMENT.md)** | Quick reference for creating custom tools                               |
| **[LLM Context Document](docs/CUSTOM_TOOL_DEVELOPMENT_AI.md)** | Comprehensive guide for AI-assisted development, useful for vibe coding |

We welcome contributions! Check out [existing tools](webqa_agent/tools/custom/) for examples.

<a id="deployment"></a>

## 🖥️ Deployment

For teams that need a **persistent web dashboard** with test management, scheduled tasks, and execution history, deploy the full-stack platform:

| Method            | Use Case                    | Guide                                                  |
| ----------------- | --------------------------- | ------------------------------------------------------ |
| Local Development | Personal dev & debugging    | [deploy/README.md](deploy/README.md#local-development) |
| Docker Compose    | Single-machine / Team trial | [deploy/README.md](deploy/README.md#docker-compose)    |
| Kubernetes        | Production cluster          | [deploy/k8s/README.md](deploy/k8s/README.md)           |

> **💡 Extending Internal Logic:** WebQA Agent supports extending internal logic based on your team's infrastructure (such as integrating internal SSO, OSS object storage, internal LLMs, etc.). You are free to customize and develop it to fit your needs. [deploy/README.md](deploy/README.md#custom-extensions)

> **Note:** The web dashboard platform is currently only available in Chinese.

<a id="roadmap"></a>

## 🗺️ RoadMap

1. Interaction & Visualization: Real-time display of reasoning processes
2. Generate Mode Expansion: Integration of additional evaluation dimensions
3. Tool Agent Context Integration: More comprehensive and precise execution

<a id="acknowledgements"></a>

## 🙏 Acknowledgements

- [natbot](https://github.com/nat/natbot): Drive a browser with GPT-3
- [Midscene.js](https://github.com/web-infra-dev/midscene/): AI Operator for Web, Android, Automation & Testing
- [browser-use](https://github.com/browser-use/browser-use/): AI Agent for Browser control

## 📄 License

<a id="license"></a>

This project is licensed under the [Apache 2.0 License](LICENSE).
