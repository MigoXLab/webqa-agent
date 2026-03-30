# CLAUDE.md

团队共享的 webqa-agent 项目指南。

**重要提示**:本文件是团队共享的,所有开发者都应遵循这些规范。个人偏好和本地配置应放在 `CLAUDE.local.md`(不会被 git 跟踪)。

## 模块化规则引用

本项目遵循模块化规则组织:

- **Python 代码质量**: `.claude/rules/python-quality.md`
- **测试模式**: `.claude/rules/testing.md`
- **Git 工作流**: `.claude/rules/git-workflow.md`
- **浏览器测试**: `.claude/rules/domain-specific/browser-testing.md`

这些规则继承自全局配置(`~/.claude/CLAUDE.md` 和 `~/.claude/rules/`),并增加了 webqa-agent 特定的要求。

______________________________________________________________________

## 研究和规划 (CRITICAL)

**对于复杂任务或涉及第三方依赖,必须先做调研:**

### 1. 使用 Context7 MCP 工具

- 工具:`mcp__plugin_context7_context7__resolve-library-id` 和 `query-docs`
- 获取最新的库文档和最佳实践
- 了解正确的 API 使用方式
- 避免基于过时知识的幻觉

### 2. 使用联网搜索

- 工具:`WebSearch`
- 查找最新的技术文章和实践
- 了解常见问题和解决方案
- 验证技术决策的合理性

### 3. 调研场景示例

- ✅ 集成新的第三方库(Playwright, LangChain, FastAPI 等)
- ✅ 实现复杂的异步模式或并发控制
- ✅ 使用不熟悉的 Python 特性或设计模式
- ✅ 配置复杂的工具链(Docker, CI/CD 等)
- ✅ 实现安全相关功能(认证、加密等)

### 4. 调研步骤

```
a. 识别任务中的三方依赖或复杂技术点
b. 使用 Context7 获取官方文档
c. 使用 WebSearch 查找最佳实践和常见陷阱
d. 基于调研结果制定实现计划
e. 开始编码实现
```

**❌ 不要做的事情**:

- 不要想当然地认为知道某个库的用法
- 不要跳过调研直接开始规划和写代码
- 不要基于旧版本的知识进行实现

______________________________________________________________________

## 代码质量要求 (CRITICAL)

### 规范性和可读性

- **类型注解**:严格模式 - 所有函数必须有类型注解
- **注释密度**:中等 - 复杂逻辑需要注释,简单逻辑不需要
- **错误处理**:显式 - 明确的 try-except 和错误处理
- **日志级别**:生产环境 info,调试时 debug

### 避免代码冗余

- ❌ 不要创建功能重复的类、方法或变量
- ❌ 不要复制粘贴代码,使用函数/方法复用
- ❌ 不要保留已废弃的代码(直接删除,Git 有历史记录)
- ✅ 重构时整合相似功能
- ✅ 使用继承和组合减少重复

### 命名规范

- **类名**:PascalCase
- **函数/方法**:snake_case
- **常量**:UPPER_SNAKE_CASE
- **私有成员**:\_leading_underscore
- **避免模糊命名**:`temp`, `tmp`, `data` 等

详细规范见:`.claude/rules/python-quality.md`

______________________________________________________________________

## 兼容性和稳定性 (CRITICAL)

**避免非必要的 breaking changes 和破坏性修改:**

### 1. 保持架构和使用的一致性

- ❌ 不要随意修改公共 API 的签名
- ❌ 不要改变已有功能的行为方式
- ❌ 不要删除正在使用的代码而不考虑影响
- ✅ 新功能应该向后兼容
- ✅ 废弃功能使用 deprecation 警告而不是直接删除
- ✅ API 变更需要提供迁移指南

### 2. 新特性设计原则

- **零学习成本优先**:新功能应该符合现有模式
- **可选而非强制**:新特性默认关闭或可选启用
- **渐进式增强**:不强迫用户立即升级或改动
- **文档完善**:新功能需要清晰的使用文档

### 3. 重构前的检查清单

- [ ] 是否影响现有的公共 API?
- [ ] 是否改变了用户可见的行为?
- [ ] 是否需要用户修改配置文件?
- [ ] 是否需要更新文档和示例?
- [ ] 是否测试了向后兼容性?
- [ ] 上下游依赖是否需要适配?

### 4. 兼容性策略

- **配置兼容**:旧配置仍然可用,新配置为可选
- **API 兼容**:保留旧 API,新 API 为增强版
- **数据兼容**:支持旧数据格式,自动迁移到新格式
- **行为兼容**:默认行为不变,通过选项启用新行为

### 5. 何时允许 breaking changes

- ✅ Major 版本升级(如 v0.2.x → v0.3.0)
- ✅ 修复严重的安全漏洞
- ✅ 修复导致数据损坏的 bug
- ✅ 在充分沟通后废弃长期标记为 deprecated 的功能

______________________________________________________________________

## 代码审查清单 (团队标准)

所有代码提交前必须通过以下检查:

- [ ] **类型注解**:所有函数都有类型提示
- [ ] **错误处理**:适当的 try-except 和日志记录
- [ ] **测试**:编写/更新测试并通过
- [ ] **文档**:更新代码注释和 markdown 文档
- [ ] **清理**:无调试 print 语句或注释代码
- [ ] **去冗余**:无重复的类、方法或变量
- [ ] **兼容性**:保持向后兼容
- [ ] **配置**:配置变更是可选的且有文档
- [ ] **Pre-commit**:通过所有 pre-commit hooks

______________________________________________________________________

## 项目概述

WebQA Agent 是一个自主式 Web 浏览器代理,用于全面的网站测试(功能、性能、UX、安全)。使用 OpenAI/Anthropic/Gemini 模型和浏览器自动化提供 AI 驱动的测试。

**理念**:自主探索和测试 - 无需手动脚本。适合快速迭代和 vibe-coding 工作流。

**核心能力**:

- AI 驱动的自主测试(无需手动脚本)
- 多提供商 LLM 支持(OpenAI, Anthropic, Gemini)
- **可扩展工具系统** - 通过 WebQABaseTool 添加自定义工具
- 全面的测试模式(功能、UX、性能、安全)

**版本**: v0.2.x 系列(当前分支:`dev_0.2.4`,已发布:v0.2.3)

### 已移除的功能（待统一规划）

**StateRestorer**（v0.2.4 移除）：

- 原功能：自动恢复 replanned case 的 URL 状态
- 移除原因：将与 run 模式的 snapshot 功能统一规划
- 当前行为：replanned cases 从 homepage 开始，需通过 `preamble_actions` 手动恢复状态
- 保留字段：`_is_replanned`, `_replan_source`, `preamble_actions`（供后续使用）

## Quick Reference

### Essential Commands

```bash
# Testing
uv run pytest tests/                              # Run all tests
uv run pytest tests/test_action_executor.py -v    # Run specific test

# Running WebQA Agent
webqa-agent init                                  # Generate config.yaml template
webqa-agent gen                                   # Generate test cases (AI mode)
webqa-agent run                                   # Run tests (auto-discovers config)

# Browser Setup
uv run playwright install chromium                # Install browser

# Code Quality (use pre-commit, not individual tools)
pre-commit run --files <files>                    # Check/fix specific files
pre-commit run --all-files                        # Check/fix all files
```

### Key File Locations

- **CLI Entry**: `webqa_agent/cli.py:main()` - Command-line interface
- **Configuration Models**: `webqa_agent/config_models/` - Pydantic V2 config classes (GenConfig, RunConfig)
- **Browser Session Pool**: `webqa_agent/browser/session.py:BrowserSessionPool` - Browser lifecycle
- **LLM API**: `webqa_agent/llm/llm_api.py:LLMAPI` - Multi-provider LLM client
- **Action Handler**: `webqa_agent/actions/action_handler.py:ActionHandler` - Browser actions
- **UI Driver**: `webqa_agent/tools/core/ui_driver.py:UITester` - AI-powered UI testing
- **LangGraph Workflow**: `webqa_agent/executor/gen/graph.py` - AI workflow orchestration (Gen mode)
- **Executors**: `webqa_agent/executor/` - GenExecutor and RunExecutor for dual-mode execution
- **Tools Registry**: `webqa_agent/tools/registry.py` - Custom tools and default tools
- **Prompts**: `webqa_agent/prompts/` - Prompt templates for test planning and execution
- **Configuration File**: `config/config.yaml` - Main configuration file

## Architecture Essentials

### Configuration Architecture (v0.2.4)

**Pydantic V2 Configuration Models** (`webqa_agent/config_models/`):

1. **Base Configs** (`base_config.py`)

   - `BrowserConfig` - Browser settings (unified cookies management)
   - `ReportConfig` - Report generation settings
   - `LLMConfig` - LLM provider settings with Extended Thinking support

2. **Mode-Specific Configs**

   - `GenConfig` (`gen_config.py`) - AI-driven test generation configuration
   - `RunConfig` (`run_config.py`) - YAML case execution configuration

3. **Key Features**

   - Field validators with `@field_validator` + `@classmethod`
   - `.model_dump()` for serialization (Pydantic V2)
   - Provider auto-detection (Claude/OpenAI/Gemini)
   - Extended Thinking validation (temperature=1.0, max_tokens>budget_tokens)

**Configuration Flow**:

```
config.yaml → CLI → GenConfig/RunConfig → Executor → LangGraph/CaseExecutor → Tools
```

### Core Components

1. **Browser Session Pool** (`webqa_agent/browser/session.py`)

   - Pool-based concurrency with `acquire()`/`release()` semantics
   - Automatic session recovery on failure
   - Token-gated session creation (only pool can create sessions)

2. **LLM Integration** (`webqa_agent/llm/llm_api.py`)

   - Auto-detection: `claude-*` → Anthropic, `gemini-*` → Gemini, `gpt-*` → OpenAI
   - Environment variables: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`
   - Provider-specific defaults (OpenAI temp=0.1, Anthropic/Gemini temp=1.0)

3. **Test Execution** (`webqa_agent/executor/`)

   - `GenExecutor` - Gen mode orchestration (AI-driven test generation)
   - `RunExecutor` - Run mode orchestration (YAML case execution)
   - `CaseExecutor` - Individual case execution with parallel support
   - Session pool integration for resource management

4. **Executor/Gen** (`webqa_agent/executor/gen/`)

   - LangGraph-based AI agent workflows for Gen mode
   - **Modular architecture:**
     - `agents/` - Execution agents (execute_agent.py)
     - `state/` - State schemas and management
     - `utils/` - Case recorder and message converter

5. **Tools System** (`webqa_agent/tools/`)

   - **Default tools** (always enabled): action_tool.py, ux_tool.py, verify_tool.py
   - **Custom tools** (optional): lighthouse_tool.py, nuclei_tool.py, button_check_tool.py, link_check_tool.py
   - **Core implementations** (tools/core/): ui_driver.py, web_checks.py, lighthouse.py
   - **Registry** (registry.py): Dependency checking and tool filtering
   - **Base class** (base.py): WebQABaseTool for extensibility

6. **Prompts** (`webqa_agent/prompts/`)

   - `test_planning_prompts.py` - Test case planning and reflection
   - `agent_execution_prompts.py` - Agent execution guidance
   - `ui_automation_prompts.py` - UI automation and verification

### Critical Constraints

**Single-Tab Architecture** (AI Mode):

- All testing in single browser tab - multi-tab not supported
- Test modes:
  - **AI Mode** (UI Agent, UX Test): Strict single-tab with layered coordination architecture
  - **Default Mode** (Basic Test): Multi-tab allowed
- **Layered Coordination Architecture** (prevents 95%+ of new tabs, zero conflicts):
  - **Layer 0 (Base)**: session.py - Context-level DOM preprocessing and event listening via `add_init_script()`
  - **Layer 1 (Enhancement)**: action_handler.py - Click-level enhancements (history recording, periodic checks, form handling)
  - **Layer 2 (Monitoring)**: click_handler.py - Test execution monitoring and result tracking
- **Coordination Mechanism**: Global flags prevent redundancy; session.py takes priority, action_handler.py enhances
- **Features**: No memory leaks, no conflicts, preserves all validated functionality
- Navigation: Use `GoBack` (browser history) and `GoToPage` (direct URL)
- Test pattern: Click → Verify → GoBack

**Browser Session Management**:

- Migration: `Driver.getInstance()` → `pool.acquire()`, `driver.page` → `session.page`
- No singleton pattern - sessions are pool-managed
- Per-session locking prevents race conditions

### Navigation Actions

**GoBack** - Navigate to previous page

- Returns `True` if succeeded, `False` if no history exists

**GoToPage** - Navigate to specific URL

- Returns `True` if navigation succeeded

**Standard Links** - Click links normally

- All clicks navigate current tab (even if `target="_blank"`)

## Testing

### Test Structure

- `tests/conftest.py` - Shared fixtures (supports `--url` override)
- `tests/mocks/` - JSON mock data for unit/integration tests
- `tests/test_pages/` - Local HTML pages for isolated testing

### Common Commands

```bash
uv run pytest tests/ -v -l                        # Verbose with local vars
uv run pytest tests/ --cov=webqa_agent            # With coverage
uv run pytest tests/ -s                           # Show print statements
uv run pytest tests/test_crawler.py --url https://example.com
```

## Configuration

### LLM Setup Examples

**OpenAI:**

```yaml
llm_config:
  model: gpt-4.1-2025-04-14
  filter_model: gpt-4o-mini
  api_key: ${OPENAI_API_KEY}
  temperature: 0.1
```

**Anthropic Claude:**

```yaml
llm_config:
  model: claude-sonnet-4-5-20250929
  filter_model: claude-haiku-4-5-20251001
  api_key: ${ANTHROPIC_API_KEY}
  temperature: 1.0  # Default for Claude; REQUIRED when using Extended Thinking
  max_tokens: 20000  # Must be larger than budget_tokens
  reasoning:
    effort: medium  # Enables Extended Thinking (budget_tokens=10000)
```

**Extended Thinking Requirements:**

1. **temperature = 1.0** (Required, auto-enforced)
2. **max_tokens > budget_tokens** (Required, auto-validated)

**Recommended Configuration Table:**

| effort  | budget_tokens | recommended max_tokens | use case                    |
| ------- | ------------- | ---------------------- | --------------------------- |
| minimal | 1,024         | 2,000 - 3,000          | Quick tasks                 |
| low     | 4,096         | 8,000 - 10,000         | Basic reasoning             |
| medium  | 10,000        | 20,000 - 25,000        | **Recommended for testing** |
| high    | 20,000        | 40,000 - 50,000        | Complex analysis            |

**Note**: The system automatically adjusts `budget_tokens` if it exceeds `max_tokens`, but proper configuration yields better results. Temperature is automatically enforced to 1.0 when Extended Thinking is enabled.

**Google Gemini:**

```yaml
llm_config:
  model: gemini-3-flash-preview
  filter_model: gemini-2.5-flash-lite
  api_key: ${GEMINI_API_KEY}
  temperature: 1.0
```

### Test Configuration

**Gen Mode (AI-driven testing):**

```yaml
test_config:
  business_objectives: "test search functionality"
  custom_tools:
    enabled: ['lighthouse', 'nuclei']  # Optional custom tools: lighthouse, nuclei, traverse_clickable_elements, detect_dynamic_links
  dynamic_step_generation:
    enabled: true
    max_dynamic_steps: 5
    min_elements_threshold: 2
```

**Browser Config:**

```yaml
browser_config:
  viewport: {width: 1280, height: 720}
  headless: false  # Auto true in Docker
  language: en-US
  save_screenshots: false
```

## Error Handling

### Unified Tag System

**Tool Response Tags:**

- `[SUCCESS]` - Action completed successfully
- `[FAILURE:root_cause]` - Recoverable failure
- `[CRITICAL_ERROR:root_cause]` - Unrecoverable, must abort
- `[WARNING]` - Non-blocking issue
- `[CANNOT_VERIFY]` - Assertion prerequisite failed

**Failure Categories:**

1. ELEMENT_NOT_FOUND - Element missing/inaccessible
2. NAVIGATION_FAILED - Page navigation failures
3. PERMISSION_DENIED - Access denied
4. PAGE_CRASHED - Browser crash
5. NETWORK_ERROR - Network issues
6. SESSION_EXPIRED - Authentication expired
7. UNSUPPORTED_PAGE - PDF/plugin pages
8. VALIDATION_ERROR - Form validation failures

### Adaptive Recovery

When `dynamic_step_generation.enabled = true`:

- **Two-layer recovery** for ELEMENT_NOT_FOUND (retry + LLM replanning)
- **LLM-driven recovery** for all failure types (GoBack, timeout, permission, etc.)
- **Loop detection**: Aborts if same error pattern repeats (2+ times)
- **Strategies**: retry_modified, skip, abort

### Auto-Handled Features

- **JavaScript dialogs**: Auto-accepted (`alert()`, `confirm()`, `prompt()`)
- **Critical errors**: Auto-abort to save resources
- **Browser state**: Detection flags for navigation actions (GoBack, GoToPage)

## Development

### Local Setup

```bash
uv sync                                           # Install dependencies
uv run playwright install chromium                # Install browser
webqa-agent run                                   # Run tests
```

### Docker Setup

```bash
./start.sh --build                                # Build and start
./start.sh --local                                # Start existing image
docker-compose down                               # Stop services
```

### Code Quality

```bash
pre-commit install                                # Install pre-commit hooks
pre-commit run --all-files                        # Run all hooks
```

## Documentation

📚 **User-facing documentation in `/docs`:**

- **[CUSTOM_TOOL_DEVELOPMENT.md](docs/CUSTOM_TOOL_DEVELOPMENT.md)** - Building custom tools for agent extensibility
- **[CUSTOM_TOOL_DEVELOPMENT_AI.md](docs/CUSTOM_TOOL_DEVELOPMENT_AI.md)** - AI-enhanced custom tool development
- **[MODES&CLI.md](docs/MODES&CLI.md)** - Complete CLI reference and test modes

Chinese versions also available: CUSTOM_TOOL_DEVELOPMENT_zh-CN.md, MODES&CLI_zh-CN.md

📝 **Claude's working documents in `/claude_docs`:**

All Claude-generated documentation is organized in `/claude_docs`:

- **Top level:** General reference docs (ARCHITECTURE.md, CONFIGURATION.md, DEVELOPMENT.md, TROUBLESHOOTING.md)
- **sessions/:** Session-specific work documents using format `YYYY-MM-DD_task-description`

See [claude_docs/README.md](claude_docs/README.md) for structure details and naming conventions.

**For future Claude sessions:** All new documentation should follow the session-based organization in `claude_docs/sessions/YYYY-MM-DD_task-description/`.

## Output Structure

- `reports/` - Generated HTML test reports (root level)
- `logs/` - Application logs and traces (root level)
- `webqa_agent/logs/` - Application logs (package level)
- `webqa_agent/reports/` - Test reports (package level)
- `tests/actions_test_results/` - Test execution outputs
- `tests/actions_test_results/screenshots/` - Action test screenshots
- `tests/crawler_test_results/screenshots/` - Crawler test screenshots

## Quick Troubleshooting

**Playwright not installed:**

```bash
uv run playwright install chromium
```

**API key issues:**

```bash
export OPENAI_API_KEY="your-key"
# or
export ANTHROPIC_API_KEY="your-key"
# or
export GEMINI_API_KEY="your-key"
```

**Config not found:**

```bash
webqa-agent init                                  # Generate template
webqa-agent run -c /path/to/config.yaml           # Specify path
```

**Enable debug logging:**

```yaml
log:
  level: debug
```

See [TROUBLESHOOTING.md](claude_docs/TROUBLESHOOTING.md) for complete guide.
