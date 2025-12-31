# 自定义工具开发

创建 WebQA Agent 自定义工具的快速参考指南。

## 快速开始

最小工作示例:

```python
from typing import Any, Type
from pydantic import BaseModel, Field
from webqa_agent.testers.case_gen.tools.base import (
    WebQABaseTool,
    WebQAToolMetadata,
)
from webqa_agent.testers.case_gen.tools.registry import register_tool

class HelloToolSchema(BaseModel):
    message: str = Field(description="要显示的消息")

@register_tool  # 使用装饰器自动注册工具
class HelloTool(WebQABaseTool):
    name: str = "hello_world"
    description: str = "打印问候消息"
    args_schema: Type[BaseModel] = HelloToolSchema

    ui_tester_instance: Any = Field(...)

    @classmethod
    def get_metadata(cls):
        return WebQAToolMetadata(
            name="hello_world",
            category="custom",
            description_short="简单的问候工具",
        )

    async def _arun(self, message: str) -> str:
        return self.format_success(f"你好，{message}！")
```

测试: `webqa-agent run -c config.yaml`

## 核心组件

**基类** (Base Classes):

- `WebQABaseTool` - 所有工具的基类
- `WebQAToolMetadata` - 工具元数据
- `ResponseTags` - 响应标签 (SUCCESS, FAILURE, CRITICAL_ERROR:TYPE)
- `ToolRegistry` - 工具注册系统

**必需方法** (Required Methods):

- `get_metadata()` - 工具元数据 (classmethod)
- `_arun()` - 异步执行 (必须是 async，不能是 sync `_run`)

**响应辅助方法** (Response Helpers):

- `format_success(msg)` - 返回成功
- `format_failure(msg, hints)` - 可恢复错误
- `format_critical_error(type, msg)` - 中止测试
- `format_warning(msg)` - 非阻塞问题
- `format_cannot_verify(msg, reason)` - 验证失败

## 文件结构

```
webqa_agent/testers/case_gen/tools/
├── base.py              # 基类
├── registry.py          # 注册系统
├── custom/              # 你的工具放这里
│   └── my_tool.py
└── __init__.py

tests/custom_tools/
└── test_my_tool.py      # 你的测试
```

## API 参考

### WebQABaseTool

```python
from webqa_agent.testers.case_gen.tools.base import WebQABaseTool

class MyTool(WebQABaseTool):
    name: str = "my_tool"
    description: str = "工具描述"
    args_schema: Type[BaseModel] = MyToolSchema
    ui_tester_instance: Any = Field(...)

    @classmethod
    def get_metadata(cls) -> WebQAToolMetadata:
        return WebQAToolMetadata(...)

    async def _arun(self, **kwargs) -> str:
        return self.format_success("完成")
```

### WebQAToolMetadata

```python
WebQAToolMetadata(
    name="my_tool",
    category="custom",  # action, assertion, ux, custom
    step_type="my_tool",
    description_short="简短描述",
    description_long="详细描述和示例",
    examples=['{"action": "my_tool", "params": {...}}'],
    use_when=["何时使用"],
    dont_use_when=["何时不使用"],
    priority=55,  # 1-100 (核心工具: 70-90, 自定义: 30-60)
    dependencies=["package1", "package2"]
)
```

### ResponseTags (响应标签)

**成功/失败**:

- `[SUCCESS]` - 继续下一步
- `[FAILURE]` - 触发自适应恢复 (如果启用)
- `[WARNING]` - 非阻塞问题
- `[CANNOT_VERIFY]` - 验证前提条件失败

**严重错误** (立即中止测试):

- `[CRITICAL_ERROR:ELEMENT_NOT_FOUND]`
- `[CRITICAL_ERROR:NAVIGATION_FAILED]`
- `[CRITICAL_ERROR:PERMISSION_DENIED]`
- `[CRITICAL_ERROR:PAGE_CRASHED]`
- `[CRITICAL_ERROR:NETWORK_ERROR]`
- `[CRITICAL_ERROR:SESSION_EXPIRED]`
- `[CRITICAL_ERROR:UNSUPPORTED_PAGE]`
- `[CRITICAL_ERROR:VALIDATION_ERROR]`

## 常见错误

1. **忘记响应标签**: 必须使用 `format_success/failure/critical_error`

   ```python
   # 错误
   return "操作完成"

   # 正确
   return self.format_success("操作完成")
   ```

2. **使用同步方法**: 使用 `async def _arun`，不是 `def _run`

   ```python
   # 错误
   def _run(self, param: str):
       return self.format_success("完成")

   # 正确
   async def _arun(self, param: str):
       return self.format_success("完成")
   ```

3. **没有 @register_tool**: 工具不会被发现

   ```python
   # 错误
   class MyTool(WebQABaseTool):
       ...

   # 正确
   @register_tool
   class MyTool(WebQABaseTool):
       ...
   ```

4. **缺少依赖声明**: 在 `get_metadata().dependencies` 中声明

   ```python
   dependencies=["aiohttp", "beautifulsoup4"]
   ```

5. **JSON 序列化错误**: 将异常转换为字符串用于 `case_recorder`

   ```python
   model_io=json.dumps({'error': str(exception)}, ensure_ascii=False)
   ```

## 上下文管理

**更新上下文** (用于 action 类工具):

```python
async def _arun(self, param: str) -> str:
    result = await self._execute(param)

    self.update_action_context(
        self.ui_tester_instance,
        {
            'description': '执行了操作',
            'action_type': 'MyAction',
            'status': 'success',
            'result': result,
            'timestamp': datetime.now().isoformat(),
        }
    )

    return self.format_success("完成")
```

**读取上下文** (用于 assertion 类工具):

```python
async def _arun(self, ...) -> str:
    context = self.get_execution_context(self.ui_tester_instance)
    if context:
        previous_data = context['last_action']['result']
        # 使用 previous_data
```

## 高级功能

**访问 LLM 配置**:

```python
@classmethod
def get_required_params(cls) -> Dict[str, str]:
    return {
        'ui_tester_instance': 'ui_tester_instance',
        'llm_config': 'llm_config',
        'case_recorder': 'case_recorder',
    }

async def _arun(self, param: str) -> str:
    model = self.llm_config.get('model', 'gpt-4')
    # 根据模型调整行为
```

**记录到 HTML 报告**:

```python
if self.case_recorder:
    self.case_recorder.add_step(
        description="自定义操作",
        model_io=json.dumps({'input': param, 'output': result}, ensure_ascii=False),
        status='passed',
        step_type='action',
    )
```

## 验证

```bash
# 检查注册
python -c "from webqa_agent.testers.case_gen.tools.registry import get_registry; print('my_tool' in get_registry().get_tool_names())"

# 运行测试
pytest tests/custom_tools/test_my_tool.py -v

# 格式化和检查
black webqa_agent/ && isort webqa_agent/ && flake8 webqa_agent/testers/case_gen/tools/custom/my_tool.py
```

## 配置示例

使用自定义工具的步骤：

1. 将工具放置在 `webqa_agent/testers/case_gen/tools/custom/` 目录
2. 使用 `@register_tool` 装饰器 - LLM 会自动发现它
3. 在配置文件中设置业务目标

**重要**: 在 AI 模式 (`type: ai`) 下，测试步骤**不在** YAML 中定义。LLM 会根据 `business_objectives` 自动生成测试步骤，并根据工具的描述和元数据选择使用。

```yaml
# config/config.yaml
target:
  url: https://example.com
  description: 测试自定义功能

# 测试配置 - AI模式下不需要 test_steps！
test_config:
  function_test:
    enabled: true
    type: "ai"  # AI模式 - LLM自动生成测试步骤
    business_objectives: "测试自定义功能，使用 my_tool 工具"
    dynamic_step_generation:
      enabled: true  # 启用自适应恢复
      max_dynamic_steps: 10
      min_elements_threshold: 1

# LLM配置
llm_config:
  model: claude-sonnet-4-5-20250929  # 或 gpt-4, gemini-2.5-flash-lite
  api_key: ${ANTHROPIC_API_KEY}  # 使用环境变量
  temperature: 1.0  # Claude Extended Thinking 必需
  max_tokens: 20000  # 必须大于 reasoning.budget_tokens

# 浏览器配置
browser_config:
  headless: false  # CI/CD环境设为 true
  viewport: {width: 1280, height: 720}
  language: zh-CN
```

**LLM 如何选择你的工具**:

- LLM 读取工具的 `description` 和 `get_metadata()` 输出
- 根据 `use_when` 提示和当前页面上下文选择工具
- 当 LLM 判断工具适合测试目标时，会调用你的工具

**配置提示**：

- 使用环境变量存储API密钥（绝不提交凭证）
- 根据模型调整 `temperature`（OpenAI: 0.1, Anthropic/Gemini: 1.0）
- Docker/CI环境中设置 `headless: true`

## 实战示例

页面标题检查器:

```python
import re
from typing import Any, Type
from pydantic import BaseModel, Field
from webqa_agent.testers.case_gen.tools.base import (
    WebQABaseTool,
    WebQAToolMetadata,
)
from webqa_agent.testers.case_gen.tools.registry import register_tool

class TitleCheckerSchema(BaseModel):
    expected_title: str = Field(description="期望的页面标题模式 (正则表达式)")
    case_sensitive: bool = Field(default=False, description="区分大小写匹配")

@register_tool
class TitleCheckerTool(WebQABaseTool):
    name: str = "check_page_title"
    description: str = "验证页面标题"
    args_schema: Type[BaseModel] = TitleCheckerSchema
    ui_tester_instance: Any = Field(...)

    @classmethod
    def get_metadata(cls):
        return WebQAToolMetadata(
            name="check_page_title",
            category="custom",
            step_type="check_page_title",
            description_short="验证页面标题是否匹配模式",
            examples=[
                '{"action": "check_page_title", "params": {"expected_title": "控制台"}}',
            ],
            use_when=["导航后", "在 SPA 中"],
            priority=55,
        )

    async def _arun(self, expected_title: str, case_sensitive: bool = False) -> str:
        try:
            page = await self.ui_tester_instance.get_current_page()
            actual_title = await page.title()

            flags = 0 if case_sensitive else re.IGNORECASE
            if re.search(expected_title, actual_title, flags):
                return self.format_success(f"标题匹配: '{actual_title}'")
            else:
                return self.format_failure(
                    f"标题不匹配。期望: '{expected_title}'，实际: '{actual_title}'",
                    recovery_hints=["检查模式", "等待动态标题加载"]
                )
        except Exception as e:
            return self.format_critical_error("PAGE_CRASHED", str(e))
```

## 参考资料

- `webqa_agent/testers/case_gen/tools/base.py` - 基类
- `webqa_agent/testers/case_gen/tools/element_action_tool.py` - UITool 参考
- `webqa_agent/testers/case_gen/tools/custom/link_detection_tool.py` - 自定义工具示例
- `webqa_agent/testers/case_gen/tools/registry.py` - 工具注册表

## 术语对照

- Tool = 工具
- Schema = 模式(Schema)
- Metadata = 元数据
- Registry = 注册表
- Response Tag = 响应标签
- Success = 成功
- Failure = 失败
- Critical Error = 严重错误
