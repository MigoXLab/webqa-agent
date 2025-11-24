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

## Installation & Configuration

### 🚀 One-Click Docker Setup

Before starting, ensure Docker is installed. If not, please refer to the official installation guide: [Docker Installation Guide](https://docs.docker.com/get-started/get-docker/).

Recommended versions: Docker >= 24.0, Docker Compose >= 2.32.

```bash
# 1. Download configuration template
mkdir -p config && curl -fsSL https://raw.githubusercontent.com/MigoXLab/webqa-agent/main/config/config.yaml.example -o config/config.yaml

# 2. Edit configuration file
# Set target.url, llm_config.api_key and other parameters

# 3. One-click start
curl -fsSL https://raw.githubusercontent.com/MigoXLab/webqa-agent/main/start.sh | bash
```

### Source Installation

```bash
git clone https://github.com/MigoXLab/webqa-agent.git
cd webqa-agent
```

1. Recommended: Install dependencies with [uv](https://github.com/astral-sh/uv) (Python>=3.11):

```bash
uv sync
```

2. Install Chromium browser:

```bash
uv run playwright install chromium
```

Performance Analysis - Lighthouse (Optional)

```bash
# Requires Node.js >= 18.0.0
npm install
```

Security Scanning - Nuclei (Optional)

Download from: [Nuclei Releases](https://github.com/projectdiscovery/nuclei/releases/)

```bash
# MacOS
brew install nuclei

# For other systems, download the appropriate version from the link above

# Update templates and verify installation
nuclei -ut -v          # Update Nuclei templates
nuclei -version        # Verify successful installation
```

After configuring `config/config.yaml` (refer to "Usage > Test Configuration"), run:

```bash
uv run python webqa-agent.py
```

### 🖥️ Visual Web Interface

WebQA Agent provides a user-friendly visual interface powered by Gradio.

```bash
# Install Gradio
uv add "gradio>5.44.0"
# Launch the Web UI
uv run python app.py

# Launch with Chinese interface
GRADIO_LANGUAGE=zh-CN uv run python app.py
```

Access the interface at http://localhost:7860.

## Usage

### Test Configuration

`webqa-agent` uses YAML configuration for test parameters:

```yaml
target:
  url: https://example.com/                       # Website URL to test
  description: example description
  # max_concurrent_tests: 2                       # Optional, default parallel 2

test_config:                                      # Test configuration
  function_test:                                  # Functional testing
    enabled: True
    type: ai                                      # default or ai
    business_objectives: example business objectives  # Recommended to include test scope, e.g., test search functionality
    dynamic_step_generation:                      # Optional, configuration for dynamic steps generation
      enabled: True                               # Optional, default False, recommended to set True to enable dynamic step generation
      max_dynamic_steps: 10                       # Optional, default 5, this example uses 10
      min_elements_threshold: 1                   # Optional, default 2, this example uses 1 for higher sensitivity
  ux_test:                                        # User experience testing
    enabled: True
  performance_test:                               # Performance analysis
    enabled: False
  security_test:                                  # Security scanning
    enabled: False

llm_config:                                       # Vision model configuration, currently supports OpenAI SDK compatible format only
  model: gpt-4.1-2025-04-14                       # Primary model for Stage 2 test planning (Recommended)
  filter_model: gpt-4o-mini                       # Lightweight model for Stage 1 element filtering (cost-effective)
  api_key: your_api_key
  base_url: https://api.example.com/v1
  temperature: 0.1                                # Optional, default 0.1
  # top_p: 0.9                                    # Optional, if not set, this parameter will not be passed
  # max_tokens: 8192                              # Optional, maximum output tokens (supports generating more test cases)

browser_config:
  viewport: {"width": 1280, "height": 720}
  headless: False                                 # Automatically overridden to True in Docker environment
  language: zh-CN
  cookies: []
  save_screenshots: False                         # Whether to save screenshots to local disk (default: False)

report:
  language: en-US                                 # zh-CN, en-US

log:
  level: info
```

Please note the following important considerations when configuring and running tests:

#### 1. Functional Testing Notes

- **AI Mode**: Uses a 2-stage planning architecture where Stage 1 (filter_model) prioritizes elements for efficient analysis, and Stage 2 (primary model) generates comprehensive test cases. The system may reflect and re-plan based on actual page conditions and test coverage, which may result in the final number of executed test cases differing from the initial configuration to ensure effectiveness. When `dynamic_step_generation` is enabled, the system automatically generates additional test steps for newly appeared UI elements (e.g., dropdowns, modals) detected through DOM diff analysis.

- **Default Mode**: The `default` mode focuses on whether UI interactions (e.g., clicks and navigations) complete successfully.

#### 2. User Experience Testing Notes

UX (User Experience) testing focuses on usability and user-friendliness. Uses multi-modal analysis combining screenshots, DOM structure, and text content to evaluate visual quality, detect typos/grammar issues, and validate layout rendering. The model output in the results provides suggestions based on best practices to guide optimization.

### 🧠 Recommended Models

The following models have been adapted and verified, and are recommended:

| Model                             | Recommendation              |
|-----------------------------------|-----------------------------|
| **gpt-4.1-2025-04-14**            | High accuracy and reliability |
| **gpt-4.1-mini-2025-04-14**       | Economical and practical |
| **qwen3-vl-235b-a22b-instruct**   | Open-source model, preferred for on-premise |
| **doubao-seed-1-6-vision-250815** | Good web understanding, supports visual recognition |


### View Results

Test results will be generated in the `reports` directory. Open the HTML report within the generated folder to view results.

## Roadmap

1. Continuous optimization of AI functional testing: Improve coverage and accuracy
2. Functional traversal and page validation: Verify business logic correctness and data integrity
3. Interaction and visualization: Test item visualization and local service real-time reasoning process display
4. Capability expansion: Multi-model integration and more evaluation dimensions

## Acknowledgements

- [natbot](https://github.com/nat/natbot): Drive a browser with GPT-3
- [Midscene.js](https://github.com/web-infra-dev/midscene/): AI Operator for Web, Android, Automation & Testing
- [browser-use](https://github.com/browser-use/browser-use/): AI Agent for Browser control

## Open Source License

This project is licensed under the [Apache 2.0 License](LICENSE).