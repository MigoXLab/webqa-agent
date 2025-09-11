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
  加入我们 🎮<a href="https://discord.gg/K5TtkVcx">Discord</a> | 💬<a href="https://aicarrier.feishu.cn/docx/NRNXdIirXoSQEHxhaqjchUfenzd">微信群</a>
</p>

<p align="center"><a href="README.md">English</a> · <a href="README_zh-CN.md">简体中文</a></p>

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

- **🤖 AI 自主测试**：WebQA-Agent能够自主进行网站测试，无需手写脚本，自动探索页面、规划动作并执行端到端流程
- **📊 多维度观测**：覆盖功能、性能、用户体验、安全等核心场景，评估页面加载速度、设计细节和链接，全面保障系统质量
- **🎯 可执行建议**：基于真实浏览器运行，输出具体的优化与改进建议
- **📈 可视化报告**：生成详细的HTML测试报告，多维度、可视化展示执行结果，便于分析与追踪

## 📹 示例演示

- **🤖 对话界面演示**: [AI 自主生成目标与步骤，在动态聊天页面中理解上下文并操作](https://pub-2c31c87660254d7bba9707e2b56fc15b.r2.dev/%E6%99%BA%E8%83%BDCase%E7%94%9F%E6%88%90.mp4)

- **🎨 静态页面演示**: [AI 自主探索页面结构、识别元素](https://pub-2c31c87660254d7bba9707e2b56fc15b.r2.dev/vibecoding.mp4)

体验Demo： [🤗Hugging Face](https://huggingface.co/spaces/mmmay0722/WebQA-Agent) · [🚀ModelScope](https://modelscope.cn/studios/mmmmei22/WebQA-Agent/summary)

## 安装与配置

### 🚀 Docker一键启动

在开始之前，请确保已安装 Docker。如未安装，请参考官方安装指南：[Docker 安装指南](https://docs.docker.com/get-started/get-docker/)。

推荐版本：
- Docker >= 24.0
- Docker Compose >= 2.32

```bash
# 1. 下载配置文件模板
mkdir -p config && curl -fsSL https://raw.githubusercontent.com/MigoXLab/webqa-agent/main/config/config.yaml.example -o config/config.yaml

# 2. 编辑配置文件
# 设置 target.url、llm_config.api_key 等参数

# 3. 一键启动
curl -fsSL https://raw.githubusercontent.com/MigoXLab/webqa-agent/main/start.sh | bash
```

### 源码安装

```bash
git clone https://github.com/MigoXLab/webqa-agent.git
cd webqa-agent
```

安装 Python >= 3.10，运行以下命令：

```bash
pip install -r requirements.txt
playwright install

```

性能分析 - Lighthouse 安装（可选）

```bash
# 需要 Node.js >= 18.0.0 package.json
npm install

```

安全扫描 - Nuclei 安装（可选）

下载地址： [Nuclei Releases](https://github.com/projectdiscovery/nuclei/releases/)

```bash
# MacOS
brew install nuclei

# 其他系统请从上述下载地址获取对应架构的版本

# 安装后更新模板并验证
nuclei -ut -v          # 更新 Nuclei 模板
nuclei -version        # 验证安装成功

```

参考“使用说明 > 测试配置”进行 `config/config.yaml` 配置后，运行下方命令。

```bash
python webqa-agent.py
```

## 使用说明

### 测试配置

`webqa-agent` 通过 YAML 配置测试运行参数：

```yaml
target:
  url: https://example.com/                       # 需要测试的网站URL
  description: example description

test_config:                                      # 测试项配置
  function_test:                                  # 功能测试
    enabled: True
    type: ai                                      # default or ai
    business_objectives: example business objectives  # 建议加入测试范围，如：测试搜索功能
  ux_test:                                        # 用户体验测试
    enabled: True
  performance_test:                               # 性能分析
    enabled: False
  security_test:                                  # 安全扫描
    enabled: False

llm_config:                                       # 视觉模型配置，当前仅支持 OpenAI SDK 兼容格式
  model: gpt-4.1                                  # 推荐使用
  api_key: your_api_key
  base_url: https://api.example.com/v1

browser_config:
  viewport: {"width": 1280, "height": 720}
  headless: False                                 # Docker环境会自动覆盖为True
  language: zh-CN
  cookies: []
```

在配置和运行测试时，请注意以下重要事项：

#### 1. 功能测试说明

- **AI模式**：当在配置文件中指定生成测试用例的数量时，系统可能会根据实际测试情况进行代理重新规划和调整。这可能导致最终执行的测试用例数量与初始设定存在一定出入，以确保测试的准确性和有效性。

- **Default模式**：功能测试的 `default` 模式主要验证UI元素的点击行为是否成功执行，包括按钮点击、链接跳转等基本交互功能。

#### 2. 用户体验测试说明

UX（用户体验）评估关注网页可用性与友好性。结果中的模型输出基于最佳实践给出改进建议，便于设计与开发参考。

## 查看结果

在 `reports` 目录会生成本次测试的文件夹，打开其中的 HTML 报告即可查看结果。

## RoadMap

1. AI智能功能功能测试持续优化：提升覆盖率与准确性
2. 功能遍历与页面校验：校验业务逻辑正确性与数据完整性
3. 交互与可视化：测试项可视化与本地服务实时展示推理过程
4. 能力扩展：多模型接入与更多评估维度集成

## 致谢

- [natbot](https://github.com/nat/natbot): 通过GPT-3驱动浏览器
- [Midscene.js](https://github.com/web-infra-dev/midscene/)：Web、Android、自动化和测试的AI Operator
- [browser-use](https://github.com/browser-use/browser-use/)：用于浏览器控制的AI Agent

## 开源许可证

该项目采用 [Apache 2.0 开源许可证](LICENSE)。