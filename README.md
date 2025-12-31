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
  Try Demo 🤗<a href="https://huggingface.co/spaces/mmmay0722/WebQA-Agent">HuggingFace</a> | 🚀<a href="https://modelscope.cn/studios/mmmmei22/WebQA-Agent/summary">ModelScope</a><br>
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

<p align="center">🤖 <strong>WebQA Agent</strong> is a fully automated web testing agent for multi-modal understanding, test generation, and end-to-end evaluation of functionality, performance, and UX. ✨</p>
</div>

<!-- Additional SEO Keywords and Context
vibecoding, vibe coding, web evaluation, autonomous exploration, web testing automation, browser testing tool, AI-powered QA, automated web testing, website performance analysis, functional testing automation, user experience testing, UX, security vulnerability scanning, browser testing, web application testing, quality assurance automation, automated UI testing, web accessibility testing, performance monitoring, website audit tool, vibecoding testing, web development
-->

## 📑 Table of Contents

- [Core Features](#-core-features)
- [Examples](#-examples)
- [Quick Start](#-quick-start)
- [Usage](#usage)
- [Extending WebQA Agent Tools](#extending-webqa-agent-tools)
- [RoadMap](#roadmap)
- [Acknowledgements](#acknowledgements)
- [License](#-license)

## 🚀 Core Features

### 📋 Feature Overview

**WebQA-Agent** provides two testing modes to support different scenarios **🤖 Generate Mode** and **📋 Run Mode**.

| Capability        | 🤖 **Generate Mode**                                                                           | 📋 **Run Mode**                                                                           |
| :---------------- | :--------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------- |
| **Core Features** | AI-driven discovery -> Dynamic generation -> Precise execution                                 | Execute based on instructions and expected verification                                   |
| **Use Cases**     | New feature, comprehensive quality assurance                                                   | Repeatable and regression testing scenarios                                               |
| **User Input**    | **Minimal**: Only URL or a one-sentence business goal                                          | **Structured**: Simple natural language step descriptions                                 |
| **Advantages**    | Reflection-based planning, adaptive to UI changes; Configurable functional / performance / security / UX evaluation for comprehensive QA | Stable and predictable results; No selector maintenance; Real-time Console and Network monitoring |

### 🧭 Architecture

<p>
  <img src="docs/images/webqa2.svg" alt="WebQA Agent Architecture" />
</p>

## 📹 Examples

- **🤖 Conversational UI**: [Autonomously plans goals and interacts across a dynamic chat interface](https://pub-2c31c87660254d7bba9707e2b56fc15b.r2.dev/%E6%99%BA%E8%83%BDCase%E7%94%9F%E6%88%90.mp4)
- **🎨 Creative Page**: [Explores page structure, identifies elements](https://pub-2c31c87660254d7bba9707e2b56fc15b.r2.dev/vibecoding.mp4)

Try Demo: [🤗Hugging Face](https://huggingface.co/spaces/mmmay0722/WebQA-Agent) · [🚀ModelScope](https://modelscope.cn/studios/mmmmei22/WebQA-Agent/summary)

## 🚀 Quick Start

### 🏎️ Recommended [uv](https://github.com/astral-sh/uv) (Python>=3.11):

```bash
# 1) Create project and install package
uv init my-webqa && cd my-webqa
uv add webqa-agent

# 2) Install browser (required)
uv run playwright install chromium

# 3) Generate Mode
# Initialize Gen mode configuration (config.yaml)
uv run webqa-agent init -m gen
# Edit config.yaml: target.url, llm_config.api_key
# Configure test_config
# For more details, see "Usage > Generate Mode - Configuration" below
uv run webqa-agent gen      # Run Generate Mode
uv run webqa-agent gen -c /path/to/config.yaml -w 4      # Generate Mode with specified config and 4 parallel workers

# 4) Run Mode
# Initialize Run mode configuration (config_run.yaml)
uv run webqa-agent init -m run
# Edit config.yaml: target.url, llm_config.api_key
# Write natural language test cases
# For more details, see "Usage > Run Mode - Configuration" below
uv run webqa-agent run     # Run Run Mode
uv run webqa-agent run -c /path/to/config_run.yaml -w 4     # Run Mode with specified config and 4 parallel workers
```

### 🔧 Generate Mode - Optional Dependencies

Performance testing (Lighthouse): `npm install lighthouse chrome-launcher` (requires Node.js ≥18)

Security testing (Nuclei):

```bash
brew install nuclei      # macOS
nuclei -ut               # Update templates
# Linux/Windows: https://github.com/projectdiscovery/nuclei/releases
```

### 🐳 Generate Mode - Docker One-liner Start

Please ensure Docker is installed (recommended Docker >= 24.0, Docker Compose >= 2.32). Official guide: [Docker Installation](https://docs.docker.com/get-started/get-docker/)

```bash
mkdir -p config \
  && curl -fsSL https://raw.githubusercontent.com/MigoXLab/webqa-agent/main/config/config.yaml.example -o config/config.yaml

# Edit config.yaml: set target.url, llm_config.api_key, etc.

curl -fsSL https://raw.githubusercontent.com/MigoXLab/webqa-agent/main/start.sh | bash
```

<a id="usage"></a>

## ⚙️ Usage

### Generate Mode - Configuration

The configuration file must include the `test_config` field to define test types.

- **Functional Testing (AI type)**: Validates correctness of page functionality. Optional configurations:
  1. business_objectives: Specifies business goals to steer test focus and coverage.
  2. dynamic_step_generation: Enables automatic generation of additional steps when new UI elements are detected during execution.
  3. filter_model: Configures a lightweight model for pre-filtering page elements to improve planning efficiency.
- **Functional Testing (default type)**: Does not rely on LLMs; focuses only on interaction success (clicks, navigation, etc.).
- **User Experience Testing**: Evaluates visual quality, typography/grammar, layout rendering, and provides optimization suggestions based on best practices.
- **Performance Testing**: Based on Lighthouse; evaluates performance, SEO, and related metrics.
- **Security Testing**: Based on Nuclei, scans web security vulnerabilities and potential risks.

For more details, please refer to [docs/MODES&CLI.md](docs/MODES&CLI.md)

```yaml
target:
  url: https://example.com              # Website URL to test
  description: Website QA testing
  max_concurrent_tests: 2               # Optional, default 2

test_config:
  function_test:                        # Functional testing
    enabled: True
    type: ai                            # 'default' or 'ai'
    business_objectives: Test search functionality, generate 3 test cases
    dynamic_step_generation:
      enabled: True                     # Enable dynamic step generation
      max_dynamic_steps: 10
      min_elements_threshold: 1
  ux_test:                              # User experience testing
    enabled: True
  performance_test:                     # Performance analysis (requires Lighthouse)
    enabled: False
  security_test:                        # Security scanning (requires Nuclei)
    enabled: False

llm_config:                             # LLM configuration, supports OpenAI, Anthropic Claude, Google Gemini, and OpenAI-compatible models (e.g., Doubao, Qwen)
  model: gpt-4.1-2025-04-14             # Primary model
  filter_model: gpt-4o-mini             # Lightweight model for element filtering (optional)
  api_key: your_api_key                 # Or set via environment variable (OPENAI_API_KEY)
  base_url: https://api.openai.com/v1   # Optional, API endpoint. For OpenAI-compatible models (Doubao, Qwen, etc.), set to their API endpoint
  temperature: 0.1                      # Optional, model temperature
  # For detailed configuration examples (OpenAI, Claude, Gemini) and reasoning settings,
  # see config/config.yaml.example

browser_config:
  viewport: {"width": 1280, "height": 720}
  headless: False                       # Auto True in Docker
  language: en-US

report:
  language: en-US                       # zh-CN or en-US

log:
  level: info                           # debug, info, warning, error
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
  max_concurrent_tests: 2               # Maximum concurrent test count

llm_config:                             # LLM configuration
  api: openai
  model: gpt-4o-mini
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

We welcome contributions! Check out [existing tools](webqa_agent/testers/case_gen/tools/custom/) for examples.

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

This project is licensed under the [Apache 2.0 License](LICENSE).
