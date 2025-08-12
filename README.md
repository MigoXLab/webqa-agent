# WebQA Agent

**WebQA Agent** 是全自动网页评估测试 Agent，一键诊断性能、安全、功能与交互体验

## 🚀 核心特性

### 🧭 功能介绍

<p>
  <img src="docs/images/webqa.svg" alt="WebQA Agent 业务功能图" />
</p>

### 📋 核心特性概览

- **🤖 AI智能测试**：兼容 OpenAI SDK 的模型，实现智能化的功能测试和用户体验评估，从页面抓取到测试执行，全程无需人工干预
- **📊 多维度评估**：涵盖功能测试、性能测试、用户体验测试和安全测试
- **🎯 精准诊断**：基于真实浏览器环境的深度测试，提供可操作的优化建议
- **📈 可视化报告**：生成详细的HTML测试报告，支持多种测试结果展示

## 安装与配置

### 🚀 Docker一键启动（推荐）

在开始之前，请确保已安装 Docker。如未安装，请参考官方安装指南：[Docker 安装指南](https://docs.docker.com/get-started/get-docker/)。

```bash
# 1. 下载配置文件模板
curl -fsSL https://raw.githubusercontent.com/MigoXLab/webqa-agent/main/config/config.yaml.example -o config.yaml

# 2. 编辑配置文件
# 设置 target.url、llm_config.api_key 等参数

# 3. 一键启动
curl -fsSL https://raw.githubusercontent.com/MigoXLab/webqa-agent/main/start.sh | bash
```

### 源码安装

```bash
git clone
cd webqa-agent
```

安装 Python >= 3.10，运行以下命令：

```bash
pip install -r requirements.txt
playwright install

```

Lighthouse 安装

```bash
# 需要 Node.js >= 18.0.0 package.json
npm install

```

Nuclei 安装

下载地址： [Nuclei Releases](https://github.com/projectdiscovery/nuclei/releases/)

```bash
# MacOS
brew install nuclei

# 其他系统请从上述下载地址获取对应架构的版本

# 安装后更新模板并验证
nuclei -ut -v          # 更新 Nuclei 模板
nuclei -version        # 验证安装成功

```

参考“使用说明 > 项目配置”进行 `config/config.yaml` 配置后，运行下方命令。

```bash
python webqa-agent.py
```

## 使用说明

### 项目配置

`webqa-agent` 通过 YAML 配置项目的运行参数：

```yaml
target:
  url: https://example.com/                       # 需要测试的网站URL
  description: example description

test_config:                                      # 测试项配置
  function_test:                                  # 功能测试
    enabled: True
    type: ai                                      # default or ai
    business_objectives: example business objectives  # 建议加入测试范围和数量描述，如：测试搜索功能，生成x个用例
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

- **Default模式**：功能测试的 `default` 模式主要验证UI元素的点击行为是否成功执行，包括按钮点击、链接跳转等基本交互功能。。

#### 2. 用户体验测试说明

UX（用户体验）测试专注于评估网站的交互设计、可用性和用户友好程度。测试结果中包含的模型输出内容是基于用户体验最佳实践提供的改进建议，供开发和设计团队参考优化。

## 查看结果

在 `reports` 目录会生成本次测试的文件夹，打开其中的 HTML 报告即可查看结果。

## RoadMap

### 功能与覆盖
- AI功能测试持续优化：不断迭代优化测试用例生成效果，提高覆盖率与准确性；支持更多的浏览器操作
- 功能遍历测试优化：实现页面自动遍历，检查页面内容变化，验证业务逻辑正确性与数据完整性
- 用户体验测试优化：自动识别并标注问题区域，辅助定位交互与可用性缺陷，提供改进线索

### 交互优化
- 测试用例可视化：以思维导图形式展示测试用例
- 本地服务（localhost）：在本地页面直接运行评估，并实时展示模型的思考过程与推理链路

### 能力扩展
- 多模型接入：支持接入多种模型，增强测试能力并适配不同场景的评估需求
- 扩展评估项：逐步集成更多测试维度（如业务安全测试等），统一纳入报告体系

## 开源许可证

该项目采用 [Apache 2.0 开源许可证](LICENSE)。