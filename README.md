# WebQA Agent

<!-- badges -->
<p align="left">
  <a href="https://github.com/MigoXLab/webqa-agent/blob/main/LICENSE"><img src="https://img.shields.io/github/license/MigoXLab/webqa-agent" alt="License"></a>
  <a href="https://github.com/MigoXLab/webqa-agent/stargazers"><img src="https://img.shields.io/github/stars/MigoXLab/webqa-agent" alt="GitHub stars"></a>
  <a href="https://github.com/MigoXLab/webqa-agent/network/members"><img src="https://img.shields.io/github/forks/MigoXLab/webqa-agent" alt="GitHub forks"></a>
  <a href="https://github.com/MigoXLab/webqa-agent/issues"><img src="https://img.shields.io/github/issues/MigoXLab/webqa-agent" alt="GitHub issues"></a>
  <a href="https://deepwiki.com/MigoXLab/webqa-agent"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"></a>
</p>

[English](README.md) · [简体中文](README_zh-CN.md) 

**WebQA Agent** is an autonomous web agent that audits performance, functionality, and UX for any web product.

## 🚀 Core Features

### 🧭 Overview

<p>
  <img src="docs/images/webqa.svg" alt="WebQA Agent Business Features Diagram" />
</p>

### 📋 Feature Highlights

- **🤖 AI-Powered Testing**: WebQA Agent autonomously conducts website testing, from page crawling and test case generation to execution, achieving end-to-end functional test automation.
- **📊 Multi-Dimensional Test**: Covers core testing scenarios, including functionality, performance, user experience, and security, evaluating page load speed, design details, and links for comprehensive system quality assurance.
- **🎯 Precise Diagnostics**: Performs deep testing in real browser environments and provides actionable optimization recommendations.
- **📈 Visual Reports**: Generates detailed HTML test reports with a multi-dimensional visual presentation of results for easy analysis and tracking.

## 📌 Test Cases

<p align="center">
  <img src="https://github.com/user-attachments/assets/b75f18bf-8b92-498e-b5e1-7c4dc5cd33f5" alt="AI Functional Testing" width="45%"/>
  &nbsp;
  <img src="https://github.com/user-attachments/assets/560cd99d-1213-47b9-82dc-52d3f2d1c1e7" alt="Other Tests" width="45%"/>
</p>

<p align="center">
  <b>Left: AI Functional Testing</b>　|　<b>Right: Multiple Test Scenarios Coverage</b>
</p>

## Installation & Configuration

### 🚀 One-Click Docker Setup

Before starting, ensure Docker is installed. If not, please refer to the official installation guide: [Docker Installation Guide](https://docs.docker.com/get-started/get-docker/).

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

Install Python >= 3.10 and run the following commands:

```bash
pip install -r requirements.txt
playwright install
```

Performance Testing - Lighthouse Installation (Optional)

```bash
# Requires Node.js >= 18.0.0
npm install
```

Security Testing - Nuclei Installation (Optional)

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
python webqa-agent.py
```

## Online Demo

Experience online: [WebQA-Agent on ModelScope](https://modelscope.cn/studios/mmmmei22/WebQA-Agent/summary)

## Usage

### Test Configuration

`webqa-agent` uses YAML configuration for test parameters:

```yaml
target:
  url: https://example.com/                       # Website URL to test
  description: example description

test_config:                                      # Test configuration
  function_test:                                  # Functional testing
    enabled: True
    type: ai                                      # default or ai
    business_objectives: example business objectives  # Recommended to include test scope, e.g., test search functionality
  ux_test:                                        # User experience testing
    enabled: True
  performance_test:                               # Performance testing
    enabled: False
  security_test:                                  # Security testing
    enabled: False

llm_config:                                       # Vision model configuration, currently supports OpenAI SDK compatible format only
  model: gpt-4.1                                  # Recommended
  api_key: your_api_key
  base_url: https://api.example.com/v1

browser_config:
  viewport: {"width": 1280, "height": 720}
  headless: False                                 # Automatically overridden to True in Docker environment
  language: zh-CN
  cookies: []
```

Please note the following important considerations when configuring and running tests:

#### 1. Functional Testing Notes

- **AI Mode**: When specifying the number of test cases to generate in the configuration file, the system may re-plan based on based on actual testing conditions. This may result in the final number of executed test cases differing from the initial configuration to ensure testing accuracy and effectiveness.

- **Default Mode**: The `default` mode of functional testing primarily verifies whether UI element clicks execute successfully, including basic interactive functions like button clicks and link navigation.

#### 2. User Experience Testing Notes

UX (User Experience) testing focuses on evaluating website interaction design, usability, and user-friendliness. The model output in the test results provides suggestions for improvement suggestions based on user experience best practices to guide development and design teams in optimization.

## View Results

Test results will be generated in the `reports` directory. Open the HTML report within the generated folder to view results.

## Roadmap

1. Continuous optimization of AI functional testing: Improve coverage and accuracy
2. Functional traversal and page validation: Verify business logic correctness and data integrity
3. Interaction and visualization: Test case visualization and local service real-time reasoning process display
4. Capability expansion: Multi-model integration and more evaluation dimensions

## Acknowledgements

- [natbot](https://github.com/nat/natbot): Drive a browser with GPT-3
- [Midscene.js](https://github.com/web-infra-dev/midscene/): AI Operator for Web, Android, Automation & Testing
- [browser-use](https://github.com/browser-use/browser-use/): AI Agent for Browser control

## Open Source License

This project is licensed under the [Apache 2.0 License](LICENSE).