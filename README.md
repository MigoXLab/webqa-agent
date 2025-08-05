# WebQA Agent

## 安装与配置

### pip 安装 (WIP)

```bash
pip install webqa-agent
npm init -y && npm install lighthouse chrome-launcher
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

# Lighthouse
npm init -y && npm install lighthouse chrome-launcher

# nuclei
brew install nuclei
nuclei -ut -v
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

llm_config: # 模型配置，当前仅支持 OpenAI 调用
  model: gpt-4o-mini
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
webqa-agent --config config.yaml
```

## 查看结果

在 results 目录生成一个测试报告文件夹，可以查看执行 **HTML测试报告**
