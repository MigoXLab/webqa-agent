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

<p align="center" itemprop="description">🤖 <strong>WebQA Agent</strong> is an autonomous web browser agent that audits performance, functionality & UX for engineers and vibe-coding creators. ✨</p>

</div>

<!-- Additional SEO Keywords and Context
vibecoding, vibe coding, web evaluation, autonomous exploration, web testing automation, browser testing tool, AI-powered QA, automated web testing, website performance analysis, functional testing automation, user experience testing, UX, security vulnerability scanning, browser testing, web application testing, quality assurance automation, automated UI testing, web accessibility testing, performance monitoring, website audit tool, vibecoding testing, web development
-->

## 🚀 Core Features

### 🧭 Overview

<p>
  <img src="docs/images/webqa.svg" alt="WebQA Agent Business Features Diagram" />
</p>

### 📋 Feature Highlights

- **🤖 AI-Powered Testing**: Performs autonomous website testing with intelligent planning and reflection—explores pages, plans actions, and executes end-to-end flows without manual scripting. Features 2-stage architecture (lightweight filtering + comprehensive planning) and dynamic test generation for newly appeared UI elements.
- **📊 Multi-Dimensional Observation**: Covers functionality, performance, user experience, and basic security; evaluates load speed, design details, and links to surface issues. Uses multi-modal analysis (screenshots + DOM structure + text content) and DOM diff detection to discover new test opportunities.
- **🎯 Actionable Recommendations**: Runs in real browsers with smart element prioritization and automatic viewport management. Provides concrete suggestions for improvement with adaptive recovery mechanisms for robust test execution.
- **📈 Visual Reports**: Generates detailed HTML test reports with clear, multi-dimensional views for analysis and tracking.

## 📹 Examples

- **🤖 Conversational UI**: [Autonomously plans goals and interacts across a dynamic chat interface](https://pub-2c31c87660254d7bba9707e2b56fc15b.r2.dev/%E6%99%BA%E8%83%BDCase%E7%94%9F%E6%88%90.mp4)
- **🎨 Creative Page**: [Explores page structure, identifies elements](https://pub-2c31c87660254d7bba9707e2b56fc15b.r2.dev/vibecoding.mp4)

Try Demo: [🤗Hugging Face](https://huggingface.co/spaces/mmmay0722/WebQA-Agent) · [🚀ModelScope](https://modelscope.cn/studios/mmmmei22/WebQA-Agent/summary)

## Quick Start

### 🏎️ Recommended [uv](https://github.com/astral-sh/uv) (Python>=3.11):

```bash
# 1) Create a project and install the package
uv init my-webqa && cd my-webqa
uv add webqa-agent
uv sync

# 2) Install browser (required)
uv run playwright install chromium

# 3) Create a config file (auto-generated template)
uv run webqa-agent init            # creates config.yaml

# 4) Edit config.yaml
#    - target.url: your site
#    - llm_config.api_key: your OpenAI key (or set OPENAI_API_KEY)
#  For detailed configuration information, please refer to the "Usage > Test Configuration"

# 5) Run
uv run webqa-agent run
```

### 🐳 Docker (one-liner)

Before starting, ensure Docker is installed. If not, please refer to the official installation guide: [Docker Installation Guide](https://docs.docker.com/get-started/get-docker/).

Recommended versions: Docker >= 24.0, Docker Compose >= 2.32.

```bash
mkdir -p config \
  && curl -fsSL https://raw.githubusercontent.com/MigoXLab/webqa-agent/main/config/config.yaml.example -o config/config.yaml

# Edit config.yaml
# Set target.url, llm_config.api_key and other parameters

curl -fsSL https://raw.githubusercontent.com/MigoXLab/webqa-agent/main/start.sh | bash
```

### 🛠️ From source
```bash
git clone https://github.com/MigoXLab/webqa-agent.git
cd webqa-agent
uv sync
uv run playwright install chromium
cp ./config/config.yaml.example ./config/config.yaml
# Edit config.yaml
# Set target.url, llm_config.api_key and other parameters
uv run webqa-agent run -c ./config/config.yaml
```

### Optional Dependencies
Performance (Lighthouse): `npm install lighthouse chrome-launcher` (Node.js ≥18)

Security (Nuclei):
```bash
brew install nuclei      # macOS
nuclei -ut               # update templates
# Linux/Win: download from https://github.com/projectdiscovery/nuclei/releases
```

## ⚙️ Usage

### Test Configuration

```yaml
target:
  url: https://example.com              # Website URL to test
  description: Website QA testing
  # max_concurrent_tests: 2             # Optional, default 2

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

llm_config:
  model: gpt-4.1-2025-04-14             # Vision model configuration, currently supports OpenAI SDK compatible format only
  filter_model: gpt-4o-mini             # Lightweight model for element filtering
  api_key: your_api_key                 # Or use OPENAI_API_KEY env var
  base_url: https://api.openai.com/v1   # Or use OPENAI_BASE_URL env var
  temperature: 0.1

browser_config:
  viewport: {"width": 1280, "height": 720}
  headless: False                       # Auto True in Docker
  language: en-US
  cookies: []
  save_screenshots: False

report:
  language: en-US                       # zh-CN or en-US

log:
  level: info                           # debug, info, warning, error
```

### Notes for Running Tests

- **Functional Testing (AI mode)**: Two-stage planning. Stage 1 (`filter_model`) prioritizes elements for efficient analysis; Stage 2 (primary model) generates comprehensive test cases. The agent may reflect and re-plan based on page state and coverage, so executed case count can differ from the initial request. When `dynamic_step_generation` is enabled, new UI elements (e.g., dropdowns, modals) detected via DOM diff will trigger additional generated steps.
- **Functional Testing (default mode)**: Focuses on whether UI interactions (clicks, navigations) complete successfully.
- **User Experience Testing**: Multi-modal analysis (screenshots + DOM structure + text) to assess visual quality, detect typos/grammar issues, and validate layout rendering. Model outputs include best-practice suggestions for optimization.


### 📖 CLI Reference

#### init - Create Configuration

```bash
# Create config.yaml in current directory
webqa-agent init

# Create at custom path
webqa-agent init -o myconfig.yaml

# Overwrite existing file
webqa-agent init --force
```

#### run - Execute Tests

```bash
# Auto-discover config (./config.yaml or ./config/config.yaml)
webqa-agent run

# Specify config file
webqa-agent run -c /path/to/config.yaml
```

#### ui - Web Interface

WebQA Agent provides a visual interface powered by Gradio:

```bash
# Install Gradio
uv add "gradio>=5.44.0"

# Launch Web UI (English by default)
webqa-agent ui
# Access at http://localhost:7860

# Launch with Chinese interface
webqa-agent ui -l zh-CN

# Optional: custom host/port and no auto-open browser
webqa-agent ui --host 0.0.0.0 --port 9000
```


### 🧠 Recommended Models

| Model                             | Recommendation              |
|-----------------------------------|-----------------------------|
| **gpt-4.1-2025-04-14**            | High accuracy and reliability |
| **gpt-4.1-mini-2025-04-14**       | Economical and practical |
| **qwen3-vl-235b-a22b-instruct**   | Open-source model, preferred for on-premise |
| **doubao-seed-1-6-vision-250815** | Good web understanding, supports visual recognition |


### 📊 View Results

Test reports are generated in the `reports/` directory. Open the HTML file to view detailed results.

## 🗺️ Roadmap

1. Continuous optimization of AI functional testing: Improve coverage and accuracy
2. Functional traversal and page validation: Verify business logic correctness
3. Interaction and visualization: Real-time reasoning process display
4. Capability expansion: Multi-model integration and more evaluation dimensions

## 🙏 Acknowledgements

- [natbot](https://github.com/nat/natbot): Drive a browser with GPT-3
- [Midscene.js](https://github.com/web-infra-dev/midscene/): AI Operator for Web, Android, Automation & Testing
- [browser-use](https://github.com/browser-use/browser-use/): AI Agent for Browser control

## 📄 License

This project is licensed under the [Apache 2.0 License](LICENSE).