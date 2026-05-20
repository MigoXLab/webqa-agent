# Troubleshooting

Use this reference when a WebQA MCP call fails, a run stalls, or the final report is missing or incomplete.

## Authentication

`401` or `Invalid API key`:

- Check `WEBQA_API_KEY`.
- Confirm the key is copied from the WebQA platform and has not expired.
- Confirm the MCP server process was restarted after changing environment variables.

`403` or permission errors:

- Confirm the API key has access to the target WebQA workspace or platform.
- If the target website itself blocks access, ask for valid cookies or a reachable test URL.

## Server Busy

`429` or concurrent limit reached:

- Reduce `workers`.
- Retry later.
- Use `list_executions` to see whether recent runs are still active.

## Execution Not Found

If `get_test_status` or `get_test_report` cannot find the execution:

- Verify the `execution_id` came from the latest `run_test` call.
- Use `list_executions` to find recent execution IDs.
- If the run is older, it may have expired or been deleted from the platform.

## Timeout Or Stuck Run

If the run stays `pending` or `running` beyond the expected window:

- Continue polling up to the 30 minute hard timeout defined in `mini-agent.md`.
- If the user asks to stop, call `cancel_test`.
- At hard timeout, call `cancel_test` and report that WebQA did not finish in time.

## Missing Report URL

If `get_test_report` has no `report_url`:

- Still summarize `status`, counts, `duration_seconds`, and `error` when present.
- Fall back to the latest `get_test_status` task results.
- Say clearly that the report link was not available.

## Useful Query Tools

Use these only for diagnosis, not the normal mini-agent flow:

- `list_executions`: find recent runs or active executions.
- `list_businesses`: inspect available WebQA projects.
- `list_environments`: inspect project environments after a business ID is known.
