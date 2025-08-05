# WebQA Agent

**WebQA Agent** 是全自动网页评估测试 Agent，一键诊断性能、功能与交互体验

## 🚀 核心特性

- **🤖 AI智能测试**：集成OPENAI模型，实现智能化的功能测试和用户体验评估，从页面抓取到测试执行，全程无需人工干预
- **📊 多维度评估**：涵盖功能测试、性能测试、用户体验测试和安全测试
- **🎯 精准诊断**：基于真实浏览器环境的深度测试，提供可操作的优化建议
- **📈 可视化报告**：生成详细的HTML测试报告，支持多种测试结果展示

## 安装与配置

### Docker 快速启动 (推荐)

```bash
# 1. 克隆项目
git clone <repository-url>
cd webqa-agent

# 2. 配置项目 
cp config/config.yaml.example config/config.yaml
# 编辑 config/config.yaml 配置文件

# 3. 启动服务
./start.sh --build      # 初次构建镜像，或者重新构建并启动 (代码/配置更新后)
./start.sh --local      # 使用已有webqa-agent镜像快速启动
```

### 源码安装
```bash
git clone
cd webqa-agent
```

安装 Python >= 3.10, 运行以下命令：

```bash
pip install -r requirements.txt
playwright install

```

Lighthouse 安装
```bash
# Lighthouse node.js>=18.0.0 
npm init -y && npm install lighthouse chrome-launcher

```

Nuclei 安装

下载地址: https://github.com/projectdiscovery/nuclei/releases/

```bash
# macOS 安装
brew install nuclei

# 其他系统请从上述下载地址获取对应架构的版本

# 安装后更新模板并验证
nuclei -ut -v          # 更新nuclei模板
nuclei -version        # 验证安装成功

```

## 使用说明

### 项目配置

`webqa-agent` 通过 YAML 配置项目的运行参数：
```yaml
target:
  url: https://example.com/ # 需要测试的网站URL
  description: 测试搜索功能

test_config: # 测试项配置
  function_test:
    enabled: True
    type: ai  # default or ai
  ux_test: 
    enabled: False
  performance_test:
    enabled: False
  security_test:
    enabled: False

llm_config: # 视觉模型配置，当前仅支持 OpenAI sdk格式兼容
  model: gpt-4.1-mini  # 推荐使用
  api_key: your_api_key 
  base_url: https://api.example.com/v1 

browser_config:
  viewport: {"width": 1280, "height": 720}
  headless: False
  language: zh-CN
  cookies: ***

```

### 运行测试

可以通过以下命令运行：

```bash
python webqa-agent.py
```

## 查看结果

在 reports 目录生成一个测试报告文件夹，可以查看执行 **HTML测试报告**
