# WebQA Agent 配置与 CLI 使用说明

WebQA Agent 支持两种执行模式，分别针对不同的测试场景和工作流进行设计。

## 🤖 Gen 模式 (自动生成模式)

**适用场景：** AI 自动探索网页，解析业务目标（例如“测试搜索逻辑”），生成测试用例，并执行端到端测试流程。
该模式适用于探索式测试和全面的质量评估。

### 核心特性

**功能测试（AI Type）**：

1. **两阶段规划**：
   阶段一（filter_model）：基于视觉理解优先筛选页面元素，以提升规划与执行效率；
   阶段二（主模型 model）：对页面进行深入理解，生成完整、系统的测试用例。

2. **测试计划生成**：
   其中测试用例基于用例设计规范、页面内容以及自定义业务目标自动生成。
   当页面结构复杂且未提供明确测试目标时，WebQA-Agent 会自动规划更广泛的测试覆盖范围。

3. **测试计划反思与重生成**：
   测试计划会根据执行结果和覆盖情况在规划层面进行反思，并动态重新生成。

4. **测试步骤动态调整（Dynamic Step Generation）：**

   在测试执行过程中，当新的 UI 元素出现时，系统会自动生成额外的测试步骤，无需手动干预即可显著提升测试覆盖率。

   **工作原理：**

   1. 每次操作后，系统执行 DOM 差异分析以检测新元素
   2. 当出现 ≥ `min_elements_threshold` 个新元素时，触发基于 LLM 的步骤生成
   3. LLM 分析新元素并生成最多 `max_dynamic_steps` 个相关测试步骤
   4. 根据测试计划的连贯性，步骤会被插入或替换剩余步骤

   **配置方式：**

   ```yaml
   test_config:
     function_test:
       type: "ai"
       dynamic_step_generation:
         enabled: true                 # 主开关（默认：true）
         max_dynamic_steps: 8          # 每次生成的最大步骤数（默认：8，范围：3-15）
         min_elements_threshold: 2     # 触发生成的最小新元素数（默认：2，范围：1-5）
   ```

   **参数说明：**

   | 参数                     | 默认值 | 用途           | 调优指南                                                        |
   | ------------------------ | ------ | -------------- | --------------------------------------------------------------- |
   | `enabled`                | `true` | 启用/禁用功能  | 对于简单静态页面或有严格时间限制时禁用                          |
   | `max_dynamic_steps`      | `8`    | 生成步骤的上限 | 复杂流程（电商、仪表板）增加到 10-12，简单 UI 减少到 5          |
   | `min_elements_threshold` | `2`    | 灵敏度控制     | 使用 1 以获得最大覆盖率（触发更频繁），使用 3+ 用于性能关键场景 |

   **实际场景示例：**

   - **下拉选择：** 用户点击下拉框 → 出现 6 个选项元素 → 生成 3-4 个步骤测试每个选项
   - **模态表单：** 用户点击"设置" → 出现包含 5 个表单字段的模态框 → 生成 5-7 个步骤填写和验证字段
   - **加载动画（已过滤）：** 用户点击"加载" → 出现单个加载动画元素 → 跳过（低于阈值 2）

   **性能影响：**

   - 每次生成增加 5-15 秒的测试执行时间
   - 典型测试包含 3 次生成：总共增加 +15-45 秒
   - Token 使用：每次生成约 4500-5500 tokens

   **何时调整：**

   | 场景            | 推荐设置                | 理由                     |
   | --------------- | ----------------------- | ------------------------ |
   | 电商产品浏览    | `max: 10, threshold: 2` | 复杂的分类/筛选交互      |
   | SaaS 管理仪表板 | `max: 12, threshold: 1` | 频繁的嵌套菜单，关键功能 |
   | 内容/博客网站   | `max: 5, threshold: 3`  | 静态内容，减少噪音       |
   | 高速冒烟测试    | `max: 5, threshold: 4`  | 优先考虑速度而非覆盖率   |
   | 移动应用测试    | `max: 7, threshold: 2`  | 紧凑 UI，模态框较多      |

   **策略说明：**

   - **插入（Insert）：** 在当前步骤后添加动态步骤（保留测试计划结构）
   - **替换（Replace）：** 用动态步骤替换剩余步骤（当新元素提供通往测试目标的替代路径时使用）

### 配置结构

Gen 模式配置文件需包含 `test_config` 字段，用于定义需要执行的测试类型。

1. 开启 功能测试AI模式 和 用户体验测试

```yaml
target:
  url: https://example.com              # 需要测试的网站 URL
  description: 网站质量保证测试
  max_concurrent_tests: 2               # 可选，默认并发数 2

test_config:
  function_test:                        # 功能测试
    enabled: True
    type: ai                            # 'default' 或 'ai'
    business_objectives: 测试搜索功能，生成3个测试用例
    dynamic_step_generation:
      enabled: True                     # 启用动态步骤生成
      max_dynamic_steps: 8              # 每次发现最多生成 8 个步骤
      min_elements_threshold: 2         # 至少需要 2 个新元素才触发
  ux_test:                              # 用户体验测试
    enabled: True
  performance_test:                     # 性能分析（需要 Lighthouse）
    enabled: False
  security_test:                        # 安全扫描（需要 Nuclei）
    enabled: False
```

1. 开启 功能测试default遍历模式、用户体验测试、性能测试、安全测试

```yaml
target:
  url: https://example.com              # 需要测试的网站 URL
  description: 网站质量保证测试
  max_concurrent_tests: 4               # 可选，默认并发数 2

test_config:
  function_test:                        # 功能测试
    enabled: True
    type: default                       # 'default' 或 'ai'
  ux_test:                              # 用户体验测试
    enabled: True
  performance_test:                     # 性能分析（需要 Lighthouse）
    enabled: True
  security_test:                        # 安全扫描（需要 Nuclei）
    enabled: True
```

## 📋 Run 模式 (用例执行模式)

**适用场景：** 通过 YAML 文件精确定义测试用例的每一步操作，AI 会按照指令执行，适合需要可重复、可追溯的测试场景。

### 核心特性

1. **自定义的测试步骤**：通过 YAML 灵活定义测试用例，精准控制每一步的执行逻辑与预期结果

2. **多模态 驱动的浏览器底层动作**：支持丰富的浏览器操作，包括：

   - `Click`, `Hover`, `Input`, `Clear`
   - `KeyboardPress`
   - `Scroll`
   - `MouseMove`, `MouseWheel`, `Drag`
   - `Sleep`
   - `Upload`
   - `GoToPage`, `GoBack`

3. **多模态验证能力**：支持多种验证方式，包括视觉内容确认、URL 与路径校验、组合图片和页面元素验证等

4. **全链路自动监控**：在执行过程中实时捕获浏览器的 `Console` 日志和 `Network` 请求状态，自动将控制台报错（Error）或网络请求失败（如 4xx/5xx）作为判定测试用例失败的重要依据

### 配置结构

Run 模式配置文件需包含 `cases` 字段，用于定义具体的测试用例。同时支持配置 `ignore_rules` 来忽略已知的浏览器 console 和 network 问题。

```yaml
target:
  url: https://example.com              # 目标网站 URL
  max_concurrent_tests: 2               # 最大并发测试数

browser_config:                         # 浏览器配置
  viewport: {"width": 1280, "height": 720}
  cookies: /path/to/cookie.json         # 读取cookie数据
  # cookies: []
  headless: false

ignore_rules:                           # 忽略规则配置（可选）
  network:                              # 网络请求忽略规则
    - pattern: ".*\\.google-analytics\\.com.*"
      type: "domain"
  console:                              # 控制台日志忽略规则
    - pattern: "Failed to load resource.*favicon"
      match_type: "regex"
    - pattern: "Warning:"
      match_type: "contains"

cases:                                  # 测试用例列表
  - name: 图片上传                       # 用例名称
    steps:                              # 测试步骤
      - action: 上传图标是输入框内的图片图标，位于百度搜索按钮旁边，用于上传文件
        args:
          file_path: ./tests/data/test.jpeg
      - action: 等待图像上传
      - verify: 验证输入字段是否显示张开的手掌/手图标图像
      - action: 输入"图片中有多少根手指？"在搜索输入框中，然后按Enter键，等待2秒
```

### 🤔 应该如何编写 Run 模式的测试用例

由于大模型常常会"幻想"，编写过程中提供详细描述是非常有用的技巧，可以显著提升执行稳定性和成功率。

#### 1. 详细的描述信息

**示例对比：**

| ❌ 错误示例        | ✅ 正确示例                                                                              |
| ------------------ | ---------------------------------------------------------------------------------------- |
| 点击下拉框         | 点击表单项A下方的下拉框                                                                  |
| 第一个文件解析成功 | 列表第一个文件，展示文件名称、文件大小，解析状态为解析成功，模型为“xxx” ，则表示测试通过 |

#### 2. 让模型"看到"页面内容

| ❌ 错误示例           | ✅ 正确示例                                 |
| --------------------- | ------------------------------------------- |
| 浏览器有两个 tab 开着 | "XXX"标题是蓝色的                           |
| 校验页面有内容“xxx”   | 用鼠标滚轮滚动1000px，校验页面内容包含“xxx” |

#### 3. 一个指令只能"看到"一个页面

如果有新的弹窗、新的表单，需要增加新的步骤。

**❌ 错误示例：**

```
点击"创建"按钮，输入“xxx”名称，点击确认
```

**✅ 正确示例：** 将任务分解为多个步骤的 AI 调用

```
点击"创建"按钮
输入包含"测试"前缀加5位随机英文字母的名称，点击"提交"按钮
点击"确认"按钮
```

#### 4. 如何 Debug？理解 AI 交互出错的原因

1. **查看报告文件**：判断是规划步骤还是定位步骤中出错
2. 检查前置步骤：有时可能是上几步环节导致假阳，也可以查看前几步执行信息
3. 规划步骤出错：当看到步骤不符预期（多步骤或少步骤），说明规划步骤中出错，可以尝试给出更好的业务理解描述
4. 定位步骤出错：当看到定位结果不符预期（元素错误或坐标偏移），可以给出详细描述信息
5. 试试更换视觉能力更强的模型

______________________________________________________________________

### 执行编写示例

**基础操作：**

```yaml
- action: 点击 "提交" 按钮
- action: 在"用户名"输入框中输入 "test_user" #如果有多个输入框时，需要更详细的内容提示大模型
- action: 清空搜索框内容    # clear
- action: 按下 "Enter" 键  # 键盘按键
- action: 等待 5s      # sleep
```

**元素识别：**

```yaml
# icon等无明确文字的元素：尽可能描述图标在页面上的位置信息，可通过其他有明确文字的元素帮助大模型理解
- action: 点击输入框下方从左至右第2个图标，最左边的图标有文案"**"
- action: 上传icon为输入框下方的图片icon，上传文件 "test.jpg"

#多个相同元素时
- action: 在页面中间对话区域，点击第一个卡片
```

**滚动/鼠标操作：**

```yaml
- action: 滚动到页面底部  # 前端页面支持window整页滚动
- action: 鼠标移动到"历史记录"列表上方，鼠标滚轮向下滚动 800px  # 组合鼠标移动进行滚动操作（推荐）
- action: 鼠标移动到“xx”节点  #  复杂绘图/Canvas场景下，依赖大模型判断的坐标或语义移动
```

**页面操作：**

```yaml
- action: 点击导航栏的“xx”，获取新打开的页面
- action: 跳转至 https://example.com/docs
- action: 返回上一页
```

### 验证编写示例

**视觉内容确认：**

```yaml
- verify: 验证输入框中显示"[预期内容]"
- verify: 点击"[按钮名称]"后，验证弹窗消失
- verify: 验证列表第一个项目，展示[字段1]、[字段2]，状态为[预期状态]
```

**URL 与路径验证：**

```yaml
- verify: 验证页面跳转，URL包含 "/[路径]"
```

**数据/记录验证：**

```yaml
- verify: 验证出现名称包含"[关键字]"前缀的记录
- verify: 验证列表[首行/特定行]出现了名称包含"[关键字]"的记录
```

**组合验证：**

```yaml
- verify: 验证流式输出正常，页面无异常报错信息，则表示测试通过
- verify: 验证当前输出完成，且[元素位置]的文本内容为"[预期文本]"，颜色为[预期颜色]、状态为[预期状态]
```

## CLI 使用

1. 初始化

```bash
# 在当前目录创建 config.yaml（默认 Gen 模式）
webqa-agent init

# 指定输出路径和文件名
webqa-agent init -o myconfig.yaml

# 强制覆盖已存在的配置文件
webqa-agent init --force

# 创建 Run 模式配置文件（默认生成 config_run.yaml）
webqa-agent init --mode run

```

1. 执行测试

```bash
# Gen 模式测试，自动发现配置文件（优先查找 ./config.yaml 或 ./config/config.yaml）
webqa-agent gen

# Gen 模式指定配置文件路径，使用 4 个并行 Worker 执行测试
webqa-agent gen -c /path/to/config.yaml -w 4

# Run 模式指定配置文件路径，使用 4 个并行 Worker 执行测试
webqa-agent run -c /path/to/config_run.yaml -w 4

```

Run 模式支持批量执行文件夹中的多个 YAML 配置文件。

**特性说明：**

- 每个 YAML 文件都可以独立配置，支持为不同文件指定不同的 `target.url`
- 可以为不同文件设置不同的 `browser_config`（如调整视口尺寸）和 `ignore_rules`（针对特定场景的忽略规则）
- Run 模式会自动加载并汇总所有文件中的 `cases` 进行统一执行

```bash
# 指定执行文件夹，使用 4 个并行 Worker 执行测试
webqa-agent run -c config/case_folder -w 4
```

1. UI - 可视化界面

Gen模式 提供gradio托管

```bash
# 安装 Gradio（如果尚未安装）
uv add "gradio>=5.44.0"

# 启动 Web UI（默认英文界面）
webqa-agent ui
# 访问地址：http://localhost:7860

# 启动中文界面
webqa-agent ui -l zh-CN

# 自定义 host 和 port，且不自动打开浏览器
webqa-agent ui --host 0.0.0.0 --port 9000 --no-browser
```
