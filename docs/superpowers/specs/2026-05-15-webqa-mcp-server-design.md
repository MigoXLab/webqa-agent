# WebQA MCP Server Design

Date: 2026-05-15
Status: Draft
Branch: feature/webqa-mcp

## Overview

Expose webqa-agent's Web testing capabilities as an MCP (Model Context Protocol) server, allowing external AI agents (Claude Code, Cursor, custom agents) to trigger tests, poll progress, and retrieve reports through the standard MCP protocol.

**Architecture:** The MCP server is a stateless API client that proxies all requests to the SaaS backend via HTTP. It does not execute tests itself. All task execution, state management, and reporting remain in the SaaS backend.

```
Agent (Claude Code / Cursor / Custom)
  | MCP protocol (STDIO or Streamable HTTP)
  v
webqa-mcp-server (FastMCP, stateless)
  | HTTP + API Key
  v
SaaS Backend (FastAPI)
  | internal scheduling
  v
cc-mini executor / K8s Job -> Browser
```

## Target Users

1. **AI Agent developers** - Integrate webqa into CI/CD, agentic workflows, or custom agents
2. **SaaS platform users** - Trigger tests from IDE via MCP without switching to the Web UI; results visible on the SaaS dashboard

## Package Structure

MCP server is a subpackage of `webqa_agent`, installed automatically with `pip install webqa-agent` / `uv sync`. Dependencies `fastmcp` and `httpx` are added to `pyproject.toml` main dependencies.

```
webqa_agent/
├── ...                         # existing modules
└── mcp_server/
    ├── __init__.py
    ├── server.py               # FastMCP server + tool registration
    ├── client.py               # WebQAClient: async httpx wrapper for backend API
    ├── auth.py                 # API Key validation
    ├── config.py               # Settings via env vars (WEBQA_API_URL, WEBQA_API_KEY)
    ├── task_manager.py         # MCP task ID <-> backend execution_id mapping
    └── tools/
        ├── __init__.py
        ├── testing.py          # run_test, cancel_test, get_test_status, get_test_report
        ├── businesses.py       # list_businesses, list_environments
        └── executions.py       # list_executions

tests/
├── ...                         # existing tests
└── test_mcp_server/
    ├── test_tools.py
    ├── test_client.py
    ├── test_task_manager.py
    └── test_integration.py
```

CLI entry point added to `pyproject.toml`:

```toml
[project.scripts]
webqa-agent = "webqa_agent.cli:main"
webqa-mcp-server = "webqa_agent.mcp_server.server:main"  # new
```

This way `pip install webqa-agent` gives users both `webqa-agent` and `webqa-mcp-server` commands.

## Tool Definitions

### 1. `run_test` (long-running, MCP Tasks required)

Initiate a web test. Supports two mutually exclusive modes:

- **Quick mode:** `url` + `task` (natural language task description)
- **Standard mode:** `business_id` + `environment_id` + `business_objectives`

Parameters:

| Parameter             | Type      | Required        | Description                       |
| --------------------- | --------- | --------------- | --------------------------------- |
| `url`                 | str\|None | Quick mode      | Target URL                        |
| `task`                | str\|None | Quick mode      | Natural language task description |
| `business_id`         | str\|None | Standard mode   | Business (project) ID from SaaS   |
| `environment_id`      | str\|None | Standard mode   | Environment ID from SaaS          |
| `business_objectives` | str\|None | Standard mode   | Test objectives                   |
| `model`               | str\|None | No              | LLM model override                |
| `workers`             | int       | No (default: 1) | Concurrent worker count           |

Validation: exactly one mode must be provided. Both or neither is an error.

Execution: `taskSupport: "required"`. Returns `CreateTaskResult` immediately; Agent polls via `tasks/get`.

Backend mapping:

- Quick mode -> `POST /executions` with `trigger_type: "mcp_quick"`, `url`, `task` in `gen_config`
- Standard mode -> `POST /executions` with `trigger_type: "gen"`, `business_id`, `environment_id`, `business_objectives` in `gen_config`

### 2. `get_test_status`

Query current status and real-time progress of a test execution.

| Parameter      | Type | Required | Description    |
| -------------- | ---- | -------- | -------------- |
| `execution_id` | str  | Yes      | Execution UUID |

Returns: status, completed tasks (name + result + duration), running tasks (name + elapsed), recent logs.

Backend: `GET /executions/{id}` + `GET /executions/{id}/progress`.

### 3. `get_test_report`

Retrieve test report for a completed execution.

| Parameter      | Type | Required              | Description                      |
| -------------- | ---- | --------------------- | -------------------------------- |
| `execution_id` | str  | Yes                   | Execution UUID                   |
| `format`       | str  | No (default: summary) | `summary` \| `detailed` \| `url` |

Returns:

- `summary`: pass/fail counts, duration, key metrics (Markdown)
- `detailed`: full step-by-step results (Markdown)
- `url`: report URL for browser viewing

Backend: `GET /executions/{id}` for status + report URLs. For `detailed` format, fetch the HTML report content via the report URL and convert key sections to Markdown. For `summary`, extract result_count and metadata from the execution record.

### 4. `cancel_test`

Cancel a running test execution.

| Parameter      | Type | Required | Description    |
| -------------- | ---- | -------- | -------------- |
| `execution_id` | str  | Yes      | Execution UUID |

Backend: `POST /executions/{id}/stop`.

### 5. `list_businesses`

List all available businesses (test projects).

No parameters.

Returns: list of `{id, name, url, description}`.

Backend: `GET /businesses`.

### 6. `list_environments`

List environments for a specific business.

| Parameter     | Type | Required | Description   |
| ------------- | ---- | -------- | ------------- |
| `business_id` | str  | Yes      | Business UUID |

Returns: list of `{id, name, url, accounts}`.

Backend: `GET /environments?business_id=...`.

### 7. `list_executions`

List recent test executions with optional filters.

| Parameter     | Type      | Required | Description                            |
| ------------- | --------- | -------- | -------------------------------------- |
| `business_id` | str\|None | No       | Filter by business                     |
| `status`      | str\|None | No       | Filter: running \| completed \| failed |
| `limit`       | int       | No (10)  | Max results                            |

Backend: `GET /executions?business_id=...&status=...&limit=...`.

## MCP Tasks Integration

### Task Lifecycle

`run_test` is the only long-running tool. It uses MCP Tasks with `taskSupport: "required"`.

```
Agent calls run_test(url, task)
  -> MCP server: POST /executions -> gets execution_id
  -> MCP server: returns CreateTaskResult{taskId, status: working}
  -> Agent polls tasks/get
  -> MCP server: GET /executions/{id}/progress -> maps status
  -> returns Task{status: working, statusMessage: "2/5 tests completed"}
  ...
  -> backend execution completes
  -> MCP server: returns Task{status: completed}
  -> Agent calls tasks/result
  -> MCP server: GET /executions/{id} -> formats report
  -> returns CallToolResult with Markdown report
```

### TaskManager

In-memory mapping from MCP task IDs to backend execution IDs. Passive polling: only queries backend when Agent calls `tasks/get`, no background threads.

```python
@dataclass
class TaskState:
    execution_id: str
    status: str           # working | completed | failed | cancelled
    created_at: datetime
    ttl: int              # ms, default 3600000 (1 hour)
    poll_interval: int    # ms, adaptive
```

### Status Mapping

| Backend execution.status | MCP task status |
| ------------------------ | --------------- |
| `pending`, `running`     | `working`       |
| `completed`, `passed`    | `completed`     |
| `failed`, `timeout`      | `failed`        |
| `cancelled`, `stopped`   | `cancelled`     |

### Adaptive Poll Interval

| Condition              | `pollInterval` |
| ---------------------- | -------------- |
| First 30 seconds       | 3000ms         |
| Running (steady state) | 5000ms         |
| Near completion (>80%) | 2000ms         |

## HTTP Client

### WebQAClient

Async httpx client wrapping all backend API calls. Managed via FastMCP lifespan.

```python
class WebQAClient:
    def __init__(self, base_url: str, api_key: str): ...
    async def create_execution(self, params: dict) -> dict: ...
    async def get_execution_status(self, execution_id: str) -> dict: ...
    async def get_execution_progress(self, execution_id: str) -> dict: ...
    async def cancel_execution(self, execution_id: str) -> dict: ...
    async def list_businesses(self) -> list[dict]: ...
    async def list_environments(self, business_id: str) -> list[dict]: ...
    async def list_executions(self, **filters) -> list[dict]: ...
    async def close(self) -> None: ...
```

Lifespan integration:

```python
@asynccontextmanager
async def lifespan(server: FastMCP):
    client = WebQAClient(settings.api_url, settings.api_key)
    try:
        yield {"client": client}
    finally:
        await client.close()
```

### Error Mapping

| Backend HTTP status | MCP behavior                                         |
| ------------------- | ---------------------------------------------------- |
| 200                 | Normal tool result                                   |
| 401                 | `ToolError("Invalid API key")`                       |
| 404                 | `ToolError("Resource not found: {detail}")`          |
| 429                 | `ToolError("Server busy, concurrent limit reached")` |
| 500                 | `ToolError("Backend service error: {detail}")`       |

## Backend Changes Required

### 1. API Key System (new)

#### Database Model

`api_keys` table:

| Column       | Type      | Description                                      |
| ------------ | --------- | ------------------------------------------------ |
| `id`         | UUID PK   | Primary key                                      |
| `user_id`    | UUID FK   | Owner (references users table)                   |
| `key_hash`   | str       | SHA-256 hash of the key (never store plaintext)  |
| `key_prefix` | str(8)    | First 8 chars of key for display (`wqa_xxxx...`) |
| `name`       | str       | User-given label (e.g. "Claude Code", "CI/CD")   |
| `expires_at` | datetime? | Optional expiry, null = never expires            |
| `last_used`  | datetime? | Last successful authentication time              |
| `created_at` | datetime  | Creation timestamp                               |

#### Backend API

```
POST   /api/settings/api-keys          # Create key (returns full key ONCE)
GET    /api/settings/api-keys          # List keys (prefix + name + dates only)
DELETE /api/settings/api-keys/{id}     # Revoke key
```

Key format: `wqa_` prefix + 40 random hex chars (e.g. `wqa_a1b2c3d4...`). Full key shown only once at creation; afterwards only `key_prefix` is visible.

#### Authentication Middleware

All `/api/*` routes accept API Key via `Authorization: Bearer wqa_xxx` header as an alternative to session/cookie auth. When a valid API Key is present, resolve to the associated user and proceed with normal permission checks. No separate `/api/v1/mcp/*` namespace needed — same API, dual auth.

#### Frontend UI

Settings page with "API Keys" section:

- **Create:** name input + optional expiry selector → show full key once in a copy-to-clipboard dialog with usage instructions (Claude Code config JSON snippet)
- **List:** table of keys (name, prefix `wqa_a1b2...`, created, last used, expires)
- **Revoke:** delete button with confirmation dialog

### 2. Quick Mode Execution (extend existing)

Extend `ExecutionCreate` schema to accept `trigger_type: "mcp_quick"`:

- Accepts `url` + `task` in `gen_config` instead of `business_id` + `test_case_ids`
- Backend creates a transient execution record (no business/environment association needed)
- Routes through cc-mini runner with `runner_source: "cc-mini"`

No new endpoints; reuses `POST /executions` with the new trigger type.

## Configuration

Environment variables with `WEBQA_` prefix:

| Variable              | Required | Default                 | Description                |
| --------------------- | -------- | ----------------------- | -------------------------- |
| `WEBQA_API_URL`       | Yes      | `http://localhost:8000` | SaaS backend URL           |
| `WEBQA_API_KEY`       | Yes      | -                       | API Key for auth           |
| `WEBQA_DEFAULT_MODEL` | No       | -                       | Override default LLM model |

### Claude Code Configuration

```json
{
  "mcpServers": {
    "webqa": {
      "command": "webqa-mcp-server",
      "env": {
        "WEBQA_API_URL": "https://webqa.example.com",
        "WEBQA_API_KEY": "wqa_xxxxx"
      }
    }
  }
}
```

### Streamable HTTP Deployment

```bash
webqa-mcp-server --transport streamable-http --port 8080
```

Optional Docker sidecar with the SaaS backend.

## Testing Strategy

### Unit Tests

- `test_tools.py`: parameter validation (quick vs standard mode mutual exclusion), error messages
- `test_client.py`: httpx mock for all backend API calls, error status handling
- `test_task_manager.py`: status mapping correctness, TTL expiry cleanup, adaptive poll interval

### Integration Tests

- `test_integration.py`: FastMCP test client, end-to-end tool calls with mocked backend

### Key Test Scenarios

1. Quick mode vs standard mode parameter mutual exclusion
2. Backend status -> MCP task status mapping for all states
3. Backend unreachable: connection error handling
4. API Key invalid/expired: proper ToolError returned
5. `cancel_test` behavior at each execution state
6. `get_test_report` with each format option
7. `list_executions` with various filter combinations

## Non-Goals (v1)

- MCP server is a subpackage of webqa-agent, not a separate package
- No MCP Resources or Prompts (tools only)
- No test case CRUD (list_test_cases, create_test_case, etc.)
- No file upload via MCP
- No streaming logs (Agent polls `get_test_status` for log snapshots)
- No multi-tenant isolation beyond API Key scoping
