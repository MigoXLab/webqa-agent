# WebQA MCP Server

通过 MCP 协议将 WebQA 的 AI 浏览器测试能力暴露给 Claude Code、Cursor 等 AI 工具。

## 安装

```bash
git clone https://github.com/MigoXLab/webqa-agent.git
cd webqa-agent
pip install -e .
```

安装后自动获得 `webqa-mcp-server` 命令。确认安装路径：

```bash
which webqa-mcp-server
```

后续更新只需 `git pull`，无需重新安装。

## 获取 API Key

登录 WebQA 平台 → 导航栏 **API Keys** → **创建 API Key** → 复制密钥（仅显示一次）。

## 配置 IDE

将 `command` 替换为 `which webqa-mcp-server` 输出的绝对路径。

### Claude Code

`.claude/settings.json`：

```json
{
  "mcpServers": {
    "webqa": {
      "command": "/path/to/webqa-mcp-server",
      "env": {
        "WEBQA_API_URL": "https://your-webqa-platform.com",
        "WEBQA_API_KEY": "wqa_xxxxxxxx..."
      }
    }
  }
}
```

### Cursor

Settings → MCP → Add Server：

```json
{
  "mcpServers": {
    "webqa": {
      "command": "/path/to/webqa-mcp-server",
      "env": {
        "WEBQA_API_URL": "https://your-webqa-platform.com",
        "WEBQA_API_KEY": "wqa_xxxxxxxx..."
      }
    }
  }
}
```

## 可用工具

| 工具                   | 用途                     | 必填参数                    |
| ---------------------- | ------------------------ | --------------------------- |
| `run_test`             | 发起浏览器测试           | `url`, `task`               |
| `get_test_status`      | 查询执行进度             | `execution_id`              |
| `get_test_report`      | 获取测试报告             | `execution_id`              |
| `cancel_test`          | 取消执行                 | `execution_id`              |
| `list_businesses`      | 列出所有业务             | 无                          |
| `list_environments`    | 列出业务环境             | `business_id`               |
| `list_business_files`  | 列出业务文件池           | `business_id`               |
| `upload_business_file` | 上传本地文件到业务文件池 | `business_id`, `local_path` |
| `list_executions`      | 列出执行历史             | 无（可选过滤）              |

## run_test 参数

| 参数               | 类型               | 必填 | 默认值   | 说明                                           |
| ------------------ | ------------------ | ---- | -------- | ---------------------------------------------- |
| `url`              | string             | 是   | —        | 目标 URL                                       |
| `task`             | string             | 是   | —        | 自然语言测试目标                               |
| `language`         | `zh-CN` \| `en-US` | 否   | `zh-CN`  | 报告语言                                       |
| `model`            | string             | 否   | 平台默认 | LLM 模型覆盖                                   |
| `cookies`          | object\[\]         | 否   | —        | 登录态 cookies，覆盖 business_id 的认证        |
| `business_id`      | string             | 否   | —        | 平台业务 ID，自动使用 SSO 认证和关联文件       |
| `environment_id`   | string             | 否   | —        | 环境 ID，配合 business_id 指定环境             |
| `test_files`       | string\[\]         | 否   | —        | 业务文件池中的文件名白名单，需配合 business_id |
| `workers`          | 1-5                | 否   | 1        | 并发数                                         |
| `save_screenshots` | boolean            | 否   | true     | 保存截图                                       |

`test_files` 只接受业务文件池里的文件名，例如 `["test.jpg"]`，不要传本机绝对路径或 URL。需要本地文件时，先调用 `upload_business_file` 上传，再把返回的 `name` 传给 `run_test.test_files`。

## 使用流程

```
run_test(url, task)
  → 返回 execution_id
  → 每 10 秒调用 get_test_status(execution_id)
  → 状态变为 completed/failed 后调用 get_test_report(execution_id)
  → 获取通过率、耗时、报告链接
```

## 使用示例

### 基础测试

> 用 webqa 测试 https://www.baidu.com ，验证首页加载正常，搜索框可见，输入 hello 点击搜索按钮，验证搜索结果正常显示

### 带登录态测试

> 用 webqa 测试 https://example.com/dashboard ，
> cookies 是 \[{"name":"token","value":"abc123","domain":".example.com"}\]，
> 验证仪表盘数据正常加载

### 使用平台 SSO 认证

> 用 webqa 测试论文搜索功能，business_id 用 "泛科学-知识空间" 的 ID，
> 验证搜索结果正确展示

Agent 会先调用 `list_businesses` 获取 ID，然后 `run_test(url=..., task=..., business_id=xxx)`，后端自动用 SSO 生成 cookies。

### 测试上传文件

> 用 webqa 测试上传图片功能，business_id 用 "示例业务" 的 ID，上传 `test.jpg` 并验证上传成功。

推荐流程：

```
list_businesses
  → list_business_files(business_id)
  → 如果业务文件池已有 test.jpg：run_test(..., business_id=xxx, test_files=["test.jpg"])
  → 如果没有且用户提供了本地文件：upload_business_file(business_id=xxx, local_path="/abs/path/test.jpg")
  → run_test(..., business_id=xxx, test_files=["test.jpg"])
```

如果任务需要上传文件，但业务文件池为空或没有匹配任务语义的文件（例如任务要求上传图片但业务池只有 PDF），`run_test` 会直接报错，避免测试在缺少文件的情况下继续运行。

### 英文报告

> Use webqa to test https://example.com, verify the homepage loads correctly.
> Set language to en-US.

## 返回格式

所有工具返回结构化 JSON，Agent 可直接解析：

**run_test**：

```json
{"execution_id": "xxx", "status": "pending"}
```

**get_test_status**：

```json
{
  "status": "completed",
  "tasks": [{"name": "验证百度搜索", "result": "passed", "duration_seconds": 120.5}]
}
```

**get_test_report**：

```json
{
  "execution_id": "xxx",
  "status": "completed",
  "passed": 1,
  "failed": 0,
  "warning": 0,
  "total": 1,
  "duration_seconds": 120,
  "report_url": "https://..."
}
```

## 环境变量

| 变量                  | 必填 | 说明                   |
| --------------------- | ---- | ---------------------- |
| `WEBQA_API_URL`       | 是   | WebQA 平台地址         |
| `WEBQA_API_KEY`       | 是   | API Key（`wqa_` 开头） |
| `WEBQA_DEFAULT_MODEL` | 否   | 默认 LLM 模型覆盖      |

## Streamable HTTP 模式

除 STDIO（IDE 集成）外，也支持 HTTP 传输：

```bash
webqa-mcp-server --transport streamable-http --port 8080
```

适用于远程 Agent 调用场景。
