---
name: webqa-cc-mini
description: "Embed the lightweight webqa-cc-mini web agent as a Python library (`run_cc_mini`) to drive Chrome via chrome-devtools-mcp for a single focused web QA task per run. ReAct loop over MCP browser tools, no Playwright, no multi-case planner. Supports Anthropic (default) and OpenAI-compatible providers (GPT, Gemini, Ollama, vLLM). Optional CLI bridge: `webqa-agent gen -c config.yaml` with `test_config.use_cc_mini: True`. Trigger words: webqa-cc-mini, cc-mini, run_cc_mini, chrome-devtools-mcp, MCP 浏览器代理, 单任务网页代理, CDP 浏览器自动化, 轻量级网页测试代理, use_cc_mini, cc-mini 库、cc-mini 调用、cc-mini 用法、嵌入式网页代理."
---

# webqa-cc-mini skill

A minimal single-task web agent that drives Chrome through [chrome-devtools-mcp](https://www.npmjs.com/package/chrome-devtools-mcp) and an LLM. Use it as a Python library or via the parent webqa-agent CLI bridge.

## When to choose webqa-cc-mini vs the parent webqa-agent skill

| Scenario                                                                        | Pick                |
| ------------------------------------------------------------------------------- | ------------------- |
| Multi-case YAML-driven exploration / execution mode, parallel workers, full report panel | **webqa-agent**     |
| One focused task per run, Python library embedding, MCP/CDP loop, no Playwright | **webqa-cc-mini**   |
| Need cookies + multi-account switching with CDP-level injection                 | **webqa-cc-mini** (via `features.cookies`) |

Two ways to invoke:

| Path                | Entry                              | When to use                                                               |
| ------------------- | ---------------------------------- | ------------------------------------------------------------------------- |
| 📦 **Library mode** | `from runner import run_cc_mini`   | Programmatic control over hooks, tools, skills, concurrency               |
| ▶️ **CLI bridge**   | `webqa-agent gen -c config.yaml`   | YAML-driven via webqa-agent CLI (sets `test_config.use_cc_mini: True`)    |

---

## 🔑 Prerequisites

- **Python** ≥ 3.10
- **Node.js** ≥ v20.19 LTS
- **Chrome** stable or newer (or set `PUPPETEER_EXECUTABLE_PATH` to a custom binary)
- **LLM credential** in env: `ANTHROPIC_API_KEY` (default) **or** `OPENAI_API_KEY`

```bash
pip install anthropic openai httpx                # cc-mini SDK requirements
npm install -g chrome-devtools-mcp@latest         # browser MCP server
```

> **Security note**: chrome-devtools-mcp opens a CDP port (`9222 + worker_id` by default). cc-mini binds it to `127.0.0.1` and disables telemetry — never expose this port to a public network.

---

## 🛠️ Library Mode — `run_cc_mini`

### Minimal example

```python
import sys
import subprocess
from pathlib import Path

# webqa-cc-mini is a directory (hyphenated, not a Python package).
# Resolve the repo root, then add the sibling directory to sys.path.
repo_root = Path(subprocess.check_output(
    ["git", "rev-parse", "--show-toplevel"], text=True).strip())
sys.path.insert(0, str(repo_root / "webqa-cc-mini"))

from runner import run_cc_mini, RunResult

result: RunResult = run_cc_mini(
    url="https://example.com",
    user_input="Find the H1 heading on the page and report it.",
    browser_headless=True,           # default False — set True on servers / CI
)

print(result.final_text)
print(f"steps={len(result.steps)} aborted={result.aborted} "
      f"in={result.input_tokens} out={result.output_tokens}")
```

> ⚠️ **`browser_headless` defaults to `False`**. On a headless server / Docker / CI, omitting `browser_headless=True` causes Chromium to fail to start and the run hangs until the time/iteration cap. The CLI bridge auto-forces `True` inside Docker (`DOCKER_ENV=true`); the library does not.

### Provider switching (explicit)

cc-mini's library API does **not** auto-detect the provider from the model name — you must pass `provider="anthropic"` or `provider="openai"` (default `"anthropic"`). The webqa-agent CLI bridge does derive the provider from `llm_config.model` and rewrites `gemini` → `openai`; the library does not.

```python
# Anthropic Claude (default; ANTHROPIC_API_KEY env fallback)
run_cc_mini(url, task, provider="anthropic", model="claude-sonnet-4-6")

# OpenAI GPT-4o (OPENAI_API_KEY env fallback)
run_cc_mini(url, task, provider="openai", model="gpt-4o", api_key="sk-...")

# Gemini via OpenAI-compatible endpoint (use provider="openai")
run_cc_mini(
    url, task,
    provider="openai",
    model="gemini-3-flash-preview",
    api_key="<gemini-key>",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

# Local Ollama / vLLM
run_cc_mini(
    url, task,
    provider="openai", model="llama3.1:70b",
    base_url="http://localhost:11434/v1", api_key="ollama",
)
```

> Use a **vision-capable** model (Claude Sonnet 4+, GPT-4o, Gemini 3 Flash, etc.). Text-only models cannot interpret screenshots and the agent loops emitting empty actions.

### Quick-start parameters (most common)

| Parameter          | Type / default               | Notes                                                                                 |
| ------------------ | ---------------------------- | ------------------------------------------------------------------------------------- |
| `url`              | `str` (required)             | Starting page                                                                         |
| `user_input`       | `str` (required)             | Task description                                                                      |
| `worker_id`        | `int = 0`                    | Per-worker isolated profile + CDP port (`9222 + worker_id`); range `[0, 56313]`       |
| `provider`         | `"anthropic"` (default) \| `"openai"` | No model-name auto-detection; pass explicitly                                  |
| `model`            | `str = "claude-sonnet-4-6"`  | Anthropic aliases: `sonnet`, `opus`, `haiku`, `best`, `sonnet45`, `opus45` (`webqa-cc-mini/core/config.py`) |
| `browser_headless` | `bool = False`               | **Set `True` on servers / CI** — see warning above                                    |
| `max_iterations`   | `int = 50`                   | Hard cap on tool steps                                                                |
| `max_time_seconds` | `float \| None = None`       | Wall-clock budget; `None` = unlimited                                                 |

### Full API reference

<details>
<summary>Click to expand all <code>run_cc_mini</code> parameters</summary>

| Parameter                | Type                          | Notes                                                                                                                |
| ------------------------ | ----------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `api_key` / `base_url`   | `str`                         | Falls back to env vars (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) when None                                            |
| `effort`                 | `"low"`/`"medium"`/`"high"`   | Maps to OpenAI `reasoning_effort` (GPT-5 family) and Anthropic Extended Thinking budget                              |
| `temperature` / `top_p`  | `float`                       | Provider defaults when None                                                                                          |
| `max_tokens`             | `int`                         | Auto-derived from model when None; for Anthropic Extended Thinking must exceed `budget_tokens`                       |
| `timeout`                | `float`                       | HTTP request timeout. Anthropic default: 600 s (with 30 s connect). OpenAI defaults to the SDK's own timeout         |
| `skills_dir`             | `str` \| `Path`               | Enables Progressive Disclosure for SKILL.md skills (see below)                                                       |
| `file_catalog`           | `str`                         | Pre-rendered catalog of test files; appended to system prompt (used with `mcp__browser__upload_file`)                |
| `save_screenshots`       | `bool`                        | **Requires `screenshot_dir` to actually persist** — `True` alone is silently a no-op                                 |
| `screenshot_dir`         | `str` \| `Path`               | Directory root for per-step PNG/JPG                                                                                  |
| `browser_viewport`       | `(width, height)` tuple       | e.g. `(1280, 720)`                                                                                                   |
| `mcp_servers`            | `list[MCPServerConfig]`       | Override the default chrome-devtools-mcp config                                                                      |
| `extra_tools`            | `list[Tool]`                  | Append custom native tools — implement `bind_mcp(server, port)` if CDP-dependent                                     |
| `pre_engine_hook`        | `callable(mcp, cdp_port)`     | Run after MCP up + Chromium started, before engine loop (e.g. cookie injection)                                      |
| `extra_section`          | `str`                         | Verbatim text appended to system prompt                                                                              |
| `on_event`               | `callable(event_tuple)`       | Stream engine events (`text`, `tool_call`, `tool_result`, `usage`, `error`, `waiting`)                               |
| `data_flow_sink`         | `callable(event_dict)`        | Receive structured data-flow events for downstream reporting                                                         |
| `enable_display_progress`| `bool`                        | Enable webqa-agent's `Display` task panel for cc-mini runs                                                           |

</details>

### Return value: `RunResult`

```python
@dataclass
class RunResult:
    final_text: str                        # last assistant text
    steps: list[Step]                      # per-turn tool calls + screenshots + tokens
    aborted: bool
    input_tokens: int
    output_tokens: int
    extensions_failed: list[str]           # diagnostics from pre_engine_hook / bind_mcp
    data_flow_events: list[dict]
```

### HTML report (optional)

```python
from features.report import render_html_report

html_path = render_html_report(            # returns a Path to the written file
    result,
    output_path="run_report.html",
    title="Smoke test",
    url="https://example.com",
    task="Verify the H1 heading",
)
```

---

## 🍪 Cookie Injection & Multi-Account Switching

Use `features.cookies` to authenticate before the agent starts and (optionally) let it switch identities mid-run.

### Single account (no mid-run switching)

```python
from features.cookies import build_cookie_extensions
from runner import run_cc_mini

ext = build_cookie_extensions(cookies=[
    {"name": "session", "value": "abc",
     "domain": ".example.com", "path": "/", "secure": True, "httpOnly": True},
])
result = run_cc_mini(url="https://example.com/", user_input="...",
                    worker_id=0, **ext.as_kwargs())
```

### Multiple accounts (agent may call `switch_account`)

```python
from features.cookies import AccountSpec, build_cookie_extensions

ext = build_cookie_extensions(accounts=[
    AccountSpec(name="admin",  cookies=ADMIN_COOKIES,  default=True,
                role="Full administrator"),
    AccountSpec(name="viewer", cookies=VIEWER_COOKIES,
                role="Read-only user"),
])
result = run_cc_mini(
    url="https://example.com/",
    user_input=(
        "Start as admin. After the first observation, "
        'call switch_account(account="viewer", navigate_url="...") '
        "and report any visible differences."
    ),
    worker_id=0,
    **ext.as_kwargs(),                     # spreads pre_engine_hook + extra_tools + extra_section
)
```

### Cookie shape requirements (validated, fails fast)

`build_cookie_extensions` raises `ValueError` if any cookie violates the CDP `CookieParam` contract:

- Must have non-empty **`name`**
- Must include **`value`** key (empty string is OK)
- Must have **`domain`** *or* a fully-qualified `url` starting with `http://` / `https://`

Without `domain`/`url` CDP rejects with `-32602` and the test silently runs logged-out.

### Composing extensions

`Extensions` instances combine with `+`:

```python
combined = build_cookie_extensions(...) + my_other_extensions
run_cc_mini(..., **combined.as_kwargs())
```

> ⚠️ Composition raises `ValueError` if **both** sides supply a `pre_engine_hook` — the bundle accepts only one. Merge their effects manually if you need both.

---

## 🧠 Skills (Progressive Disclosure)

Pass `skills_dir` to expose optional domain knowledge without bloating every API call:

```python
result = run_cc_mini(
    url="https://example.com",
    user_input="Audit the homepage UI consistency.",
    skills_dir=str(repo_root / "webqa-cc-mini" / "skills"),
)
```

At startup the engine parses each `<skills_dir>/<name>/SKILL.md` frontmatter (~100 tokens each) and injects `name + description` into the system prompt. The LLM calls the auto-registered `load_skill` tool to fetch the full body when it actually needs the procedure.

SKILL.md frontmatter supports only single-line scalar pairs — `name`, `description`, optional `when_to_use`. See `webqa-cc-mini/skills/README.md` for the format and `webqa-cc-mini/skills/{plan,ui-audit}/SKILL.md` for examples.

---

## ▶️ CLI Bridge (via webqa-agent)

If you have webqa-agent installed and want a YAML-driven workflow, set `test_config.use_cc_mini: True` to route the `gen` command through the cc-mini engine instead of the standard Gen executor. (`webqa-agent run` does **not** trigger cc-mini.)

```yaml
target:
  url: https://your-target-site.com/
  max_concurrent_tests: 1                  # cc-mini is single-task per run

test_config:
  use_cc_mini: True
  business_objectives: "测试搜索功能并验证结果列表"   # required when use_cc_mini=True (single string)
  cc_mini_skills_dir: ./webqa-cc-mini/skills   # optional, Progressive Disclosure
  test_files_dir: ./test_assets                # optional, builds upload catalog injected into the prompt
  # test_files: ["sample.pdf", "form.docx"]    # optional whitelist within test_files_dir

llm_config:
  # Provider auto-derived from model: claude-* → anthropic; gpt/o*/gemini-* → openai
  model: gpt-5.4-mini                      # vision-capable model required
  api_key: ${OPENAI_API_KEY}
  base_url: ${OPENAI_BASE_URL}             # required for non-default OpenAI endpoints
  temperature: 0.1
  # top_p: 0.95                            # forwarded to cc-mini if set
  # max_tokens: 8192                       # forwarded; required for Anthropic Extended Thinking
  # timeout: 600                           # HTTP timeout in seconds, forwarded
  # reasoning:
  #   effort: medium                       # GPT-5 reasoning_effort / Claude thinking budget

browser_config:
  viewport: {width: 1280, height: 720}
  headless: true                           # auto-true in Docker (DOCKER_ENV=true)
  language: zh-CN

report:
  language: zh-CN
  save_screenshots: true
  save_dataflow: true                      # default true; writes data_flow.json + gantt panel

log:
  level: info

# Optional: top-level `accounts:` (parsed into features.cookies AccountSpec)
# Each entry maps 1:1 to AccountSpec; `default: true` marks the startup identity.
# accounts:
#   - name: admin
#     default: true                        # the account loaded before the agent starts
#     role: "full admin"                   # sent to the LLM in the role summary
#     cookies: [{name: ..., value: ..., domain: ..., path: /}, ...]
#   - name: viewer
#     role: "read-only"
#     cookies: [...]
```

```bash
# Provider auto-resolves from llm_config.model
webqa-agent gen -c config.yaml
```

CLI specifics that differ from library mode:

- `business_objectives` (a **single string**) becomes the `user_input` task.
- `provider="gemini"` is rewritten to `"openai"` automatically.
- Reports land under `reports/test_<timestamp>/` with screenshots + `data_flow.json` when enabled.
- Anthropic users: if `llm_config.base_url` got auto-filled with `https://api.openai.com/v1` upstream, the bridge resets it to the Anthropic default automatically.

---

## ⚡ Concurrency

Each run owns an isolated Chromium profile and CDP port keyed by `worker_id`. Fan out with distinct IDs:

```python
import asyncio

async def run_one(worker_id: int, account: AccountSpec) -> str:
    ext = build_cookie_extensions(accounts=[account])
    result = await asyncio.to_thread(
        run_cc_mini,
        url="https://example.com/",
        user_input=f"Worker {worker_id}: report the H1.",
        worker_id=worker_id,
        browser_headless=True,
        **ext.as_kwargs(),
    )
    return result.final_text

await asyncio.gather(*(run_one(i, a) for i, a in enumerate(accounts)))
```

> ⚠️ **Port collision**: if `9222 + worker_id` is already bound, the MCP server exits with `Critical MCP server 'browser' failed to start`. Check `lsof -iTCP:9222` or pick a different `worker_id`.

---

## 🐛 Troubleshooting

| Symptom                                              | Likely cause / fix                                                                                                |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `Critical MCP server 'browser' failed to start`      | Port collision or chrome-devtools-mcp not installed → `npm install -g chrome-devtools-mcp@latest`, change worker_id |
| Run hangs silently on a server / CI                  | `browser_headless` defaults to `False` → pass `browser_headless=True` (library) or `headless: true` (YAML)         |
| `save_screenshots=True` but no images on disk        | Must also pass `screenshot_dir=...` (library) or set `report.save_screenshots: true` with a resolved report dir   |
| Agent runs logged-out despite `cookies=[...]`        | Cookie missing required `name`/`value` or both `domain` and `url` → `build_cookie_extensions` raises `ValueError` |
| `pre_engine_hook: CDP port could not be resolved`    | Custom `mcp_servers` without `--browser-url` / `--ws-endpoint` / `--chrome-arg=--remote-debugging-port=N`         |
| All tool calls return empty / agent loops            | Model lacks vision → switch to a vision-capable model (Claude Sonnet 4+, GPT-4o, Gemini 3 Flash)                  |
| OpenAI provider hits `api.openai.com` unexpectedly   | `OPENAI_BASE_URL` env var overrides YAML — explicitly set or unset it before invocation                           |
| Extended Thinking budget rejected                    | `max_tokens` must exceed `budget_tokens` and `temperature` must be `1.0`                                          |
| `cannot merge Extensions with conflicting pre_engine_hook` | Two extension bundles both define `pre_engine_hook` → consolidate them into one hook function manually        |

---

## 📚 References

- `webqa-cc-mini/runner.py` — full `run_cc_mini` signature & docstring
- `webqa-cc-mini/examples/cookies_basic.py` — single / multi / concurrent runnable demos
- `webqa-cc-mini/features/cookies/__init__.py` — `AccountSpec`, `build_cookie_extensions`, validation rules
- `webqa-cc-mini/features/report.py` — `render_html_report` post-processor
- `webqa-cc-mini/skills/README.md` — SKILL.md format & Progressive Disclosure semantics
- `webqa_agent/cli.py::_execute_cc_mini_mode` — CLI bridge implementation
- `config/config.yaml` (cc-mini section near the bottom) — annotated YAML example
