<h1 align="center">WebQA Agent</h1>

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

## 🚀 核心特性

### 🧭 功能介绍

<p>
  <img src="docs/images/webqa.svg" alt="WebQA Agent 业务功能图" />
</p>

### 📋 特性概览

- **🤖 AI智能测试**：WebQA-Agent能够自主进行网站测试，从页面抓取、用例生成与执行，实现端到端功能测试自动化
- **📊 多维度评估**：覆盖功能、性能、用户体验、安全等核心测试场景，评估页面加载速度、设计细节和链接，全面保障系统质量
- **🎯 精准诊断**：基于真实浏览器环境的深度测试，提供可操作的优化建议
- **📈 可视化报告**：生成详细的HTML测试报告，多维度、可视化展示测试结果，便于分析与追踪


## 安装与配置

### 🚀 Docker一键启动

在开始之前，请确保已安装 Docker。如未安装，请参考官方安装指南：[Docker 安装指南](https://docs.docker.com/get-started/get-docker/)。

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

性能测试 - Lighthouse 安装（可选）

```bash
# 需要 Node.js >= 18.0.0 package.json
npm install

```

安全测试 - Nuclei 安装（可选）

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

## 在线演示

🚀 **在线体验 WebQA Agent:**
- **Hugging Face Spaces**: [WebQA-Agent on Hugging Face](https://huggingface.co/spaces/mmmay0722/WebQA-Agent)
- **ModelScope Studio**: [WebQA-Agent on ModelScope](https://modelscope.cn/studios/mmmmei22/WebQA-Agent/summary)

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
  performance_test:                               # 性能测试
    enabled: False
  security_test:                                  # 安全测试
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

UX（用户体验）测试专注于评估网站的交互设计、可用性和用户友好程度。测试结果中包含的模型输出内容是基于用户体验最佳实践提供的改进建议，供开发和设计团队参考优化。

## 查看结果

在 `reports` 目录会生成本次测试的文件夹，打开其中的 HTML 报告即可查看结果。

## RoadMap

1. AI功能测试持续优化：提升覆盖率与准确性
2. 功能遍历与页面校验：校验业务逻辑正确性与数据完整性
3. 交互与可视化：用例可视化与本地服务实时展示推理过程
4. 能力扩展：多模型接入与更多评估维度集成

## 致谢

- [natbot](https://github.com/nat/natbot): 通过GPT-3驱动浏览器
- [Midscene.js](https://github.com/web-infra-dev/midscene/)：Web、Android、自动化和测试的AI Operator
- [browser-use](https://github.com/browser-use/browser-use/)：用于浏览器控制的AI Agent

## 开源许可证

该项目采用 [Apache 2.0 开源许可证](LICENSE)。