# Mini-Agent

Use this reference for the default WebQA testing path: one focused browser QA task against one starting URL.

## Inputs

Required:

- `url`: target page or website.
- `task`: natural-language objective.

Optional:

- `language`: `zh-CN` or `en-US`; default to the user's language, otherwise `zh-CN`.
- `model`: optional LLM model override.
- `cookies`: browser cookies for authenticated testing; read `cookies.md` first.
- `workers`: integer from 1 to 5; default `1`.
- `save_screenshots`: default `true`.

If the user only provides a URL, use this default task:

```text
从真实用户视角验证该网站首页可以正常加载，核心入口可见，主要交互没有明显错误。
```

If the user asks for a specific flow, make `task` concrete about actions and expected outcomes, for example:

```text
验证搜索流程：打开首页，找到搜索框，输入 hello，提交搜索，确认结果页正常显示。
```

## Workflow

1. Confirm the URL exists. If missing, ask the user for it.
2. If the task needs login state and cookies are not provided, read `cookies.md` and ask for cookie JSON.
3. Call `run_test` with `url`, `task`, and any optional parameters the user supplied.
4. Save the returned `execution_id`.
5. Poll `get_test_status(execution_id)` until a terminal status appears.
6. Call `get_test_report(execution_id)` after terminal status.
7. Summarize the final result using the report data.

## Polling

Poll once after 3 to 5 seconds, then about every 10 seconds.

Terminal statuses:

- `completed`
- `passed`
- `failed`
- `timeout`
- `cancelled`
- `stopped`

Non-terminal statuses are typically `pending` or `running`. If the execution runs longer than 30 minutes, call `cancel_test(execution_id)` and report that the run was cancelled because it exceeded the hard timeout.

If the user asks to stop, call `cancel_test(execution_id)` and report the cancellation result.

## Report

Use `get_test_report(execution_id)` as the source of truth.

Expected report fields may include:

- `status`
- `passed`
- `failed`
- `warning`
- `total`
- `duration_seconds`
- `report_url`
- `error`

Important: `completed` or `passed` execution status does not mean every tested item passed. Prefer `passed`, `failed`, `warning`, and `total` when present.

If counts are missing, fall back to the latest `get_test_status` response:

- Use `tasks[].result` to estimate passed, warning, failed, running, or unknown items.
- Say clearly that the summary is based on status-task fallback because report counts were unavailable.

Always include:

- Final status.
- Counts when available.
- Brief issue summary for failed or warning items.
- `report_url` when available.
- Duration when available.
