# WebQA Agent Config和CLI说明

WebQA Agent 支持两种执行模式，分别针对不同的测试场景和工作流进行设计。

## 🤖 AI 模式 (AI 驱动测试生成和执行)

**适用场景：** 自动化测试生成、探索性测试、全面的质量保证（QA）。

### 核心特性

- **AI 驱动的测试生成**：根据业务目标自动生成测试用例。
- **多种测试类型**：
  - 功能测试（默认或 AI 驱动）
  - 用户体验 (UX) 测试
  - 性能测试（需安装 Lighthouse）
  - 安全测试（需安装 Nuclei）
- **动态步骤生成**：AI 可以动态发现并测试页面功能。
- **并行执行**：支持并发运行多种测试类型。

### 配置结构

**配置需包含 `test_config` 字段**

```yaml
target:
  url: https://example.com
  max_concurrent_tests: 2

test_config:
  function_test:
    enabled: true
    type: ai
    business_objectives: "生成 3 个功能测试用例"
  ux_test:
    enabled: true
  performance_test:
    enabled: false
  security_test:
    enabled: false

llm_config:
  api: openai
  model: gpt-4o-mini
  api_key: your_api_key_here

browser_config:
  viewport: {"width": 1280, "height": 720}
  headless: false
```

### 使用方法

#### init - 创建AI模式配置

```bash
# 在当前目录创建 config.yaml
webqa-agent init

# 指定输出路径
webqa-agent init -o myconfig.yaml

# 覆盖已存在的文件
webqa-agent init --force
```

#### run - 执行AI模式测试

```bash
# 自动发现配置文件（./config.yaml 或 ./config/config.yaml）
webqa-agent run

# 指定配置文件
webqa-agent run -c /path/to/config.yaml
```

#### ui - 可视化界面

WebQA Agent 提供了基于 Gradio 的可视化界面：

```bash
# 安装 Gradio
uv add "gradio>=5.44.0"

# 启动 Web UI（默认英文）
webqa-agent ui
# 访问地址：http://localhost:7860

# 启动中文界面
webqa-agent ui -l zh-CN

# 可选：自定义 host/port 且不自动打开浏览器
webqa-agent ui --host 0.0.0.0 --port 9000 --no-browser
```

______________________________________________________________________

## 📋 Case 模式 (YAML 定义测试用例)

**适用场景：** 回归测试、特定业务路径验证、需要精确控制的脚本化测试流。

### 核心特性

- **高度自定义的测试步骤**：支持通过 YAML 灵活定义测试用例，精准控制每一步的执行逻辑与预期结果。
- **多模态 AI 驱动的底层动作**：支持浏览器操作，如 `Click` (点击)、`Input` (输入)、`Clear` (清空)、`Drag` (拖拽)、`KeyboardPress` (键盘按键)、`Scroll` (滚动)、`Mouse move/wheel` (鼠标移动与滚轮)、`Sleep` (等待)、`GoToPage` (跳转)、`GoBack` (后退)、`GetNewPage` (处理新开页)、`Upload` (文件上传)。
- **多模态 AI 验证能力**：视觉内容确认、URL 与路径校验、组合图片和页面元素验证等
- **全链路自动监控**：在执行过程中实时捕获浏览器的 `Console` 日志和 `Network` 请求状态，自动将控制台报错（Error）或网络请求失败（如 4xx/5xx）作为判定 Case 失败的重要依据。

### 配置结构

**配置需包含 `cases` 字段**
**针对已知的浏览器console和network问题，自定义忽略规则**

```yaml
target:
  url: https://example.com
  max_concurrent_tests: 2

llm_config:
  api: openai
  model: gpt-4o-mini
  api_key: your_api_key_here

browser_config:
  viewport: {"width": 1280, "height": 720}
  headless: false

ignore_rules:
  network:
    - pattern: ".*\\.google-analytics\\.com.*"
      type: "domain"
  console:
    - pattern: "Failed to load resource.*favicon"
      match_type: "regex"
    - pattern: "Warning:"
      match_type: "contains"

cases:
  - name: 图片上传
    steps:
      - action: 上传图标是输入框内的图片图标，位于百度搜索按钮旁边，用于上传文件
        args:
          file_path: ./tests/data/test.jpeg
      - action: 等待图像上传
      - verify: 验证输入字段是否显示张开的手掌/手图标图像
      - action: 输入“图片中有多少根手指？”在搜索输入框中，然后按Enter键，等待2秒
```

### 使用方法

#### init - 创建Case模式配置

```bash
# 初始化 Case 模式配置
webqa-agent init -m case

```

#### run - 执行Case模式测试

```bash
# 编辑 config_case.yaml 定义测试用例

# 运行单个测试文件
webqa-agent run  -m case -c /path/to/config_case.yaml

```

#### run - 执行Case模式测试（运行包含多个 YAML 的文件夹）

假设文件夹结构如下：

```text
config/case_folder/
├── login_tests.yaml
├── search_tests.yaml
└── checkout_tests.yaml
```

每个 YAML 文件都可以独立配置：支持为不同文件指定不同的 `target.url`、设置不同的 `browser_config`（如调整视口尺寸）以及配置不同的 `ignore_rules`（针对特定场景的忽略规则）。

Case模式下自动加载并汇总所有文件中的 `cases` 进行统一执行, 并使用 4 个并行 Worker 进行测试。

```bash
# 自动加载并执行文件夹下的所有 YAML 文件
webqa-agent run -m case -c config/case_folder -w 4
```

______________________________________________________________________

## 🤔 我应该使用哪种模式？

### 在以下情况下使用 **AI 模式**：

- ✅ 利用 AI 进行探索性测试页面
- ✅ 需要进行全面的测试（功能、UX、性能、安全）
- ✅ 无具体测试需求，或测试需求较为宽泛（如“测试搜索功能”）。

### 在以下情况下使用 **Case 模式**：

- ✅ 需要可重复的回归测试
- ✅ 希望精准控制每一个测试步骤
- ✅ 从传统的测试脚本迁移，使用自然语言编写自动化脚本

______________________________________________________________________
