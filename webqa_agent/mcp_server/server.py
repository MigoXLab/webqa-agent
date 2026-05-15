"""FastMCP server for WebQA — entry point and tool registration."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.context import Context

from webqa_agent.mcp_server.client import WebQAAPIError, WebQAClient
from webqa_agent.mcp_server.config import settings
from webqa_agent.mcp_server.tools import businesses, executions, testing

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(server: FastMCP):
    if not settings.api_key:
        logger.warning('WEBQA_API_KEY not set — tools will fail on auth')
    client = WebQAClient(base_url=settings.api_url, api_key=settings.api_key)
    try:
        yield {'client': client}
    finally:
        await client.close()


mcp = FastMCP(
    'WebQA',
    instructions=(
        'WebQA is an AI-powered web testing service. Use run_test to start a browser test, '
        'get_test_status to poll progress, and get_test_report to retrieve results. '
        'Tests typically take 2-10 minutes. Always call get_test_report after completion.'
    ),
    lifespan=lifespan,
)


def _get_client(ctx: Context) -> WebQAClient:
    return ctx.request_context.lifespan_context['client']


@mcp.tool()
async def run_test(
    url: str,
    task: str,
    language: str = 'zh-CN',
    model: Optional[str] = None,
    cookies: Optional[str] = None,
    workers: int = 1,
    save_screenshots: bool = True,
    ctx: Context = None,
) -> str:
    """Start an AI-powered browser test against a URL.

    The agent navigates the page, performs actions, and verifies results
    autonomously. Tests take 2-10 minutes depending on task complexity.

    Args:
        url: Target URL to test. Must be accessible from the server.
        task: What to test, in natural language. Be specific about actions
            and expected outcomes.
            Example: "Verify homepage loads, search for 'hello', check results page"
        language: Report language. 'zh-CN' for Chinese, 'en-US' for English.
        model: LLM model override. Defaults to server configuration.
        cookies: JSON array of browser cookies for authenticated testing.
            Example: '[{"name":"token","value":"xxx","domain":".example.com"}]'
        workers: Number of concurrent test workers (when task has multiple parts).
        save_screenshots: Whether to capture screenshots during testing.
    """
    client = _get_client(ctx)
    try:
        result = await testing.run_test(
            client,
            url=url,
            task=task,
            language=language,
            model=model or settings.default_model or None,
            cookies=cookies,
            workers=workers,
            save_screenshots=save_screenshots,
        )
    except ValueError as e:
        raise ToolError(str(e)) from e
    except WebQAAPIError as e:
        raise ToolError(e.message) from e

    execution_id = str(result.get('id', ''))
    return f'Started: execution_id={execution_id}'


@mcp.tool()
async def get_test_status(execution_id: str, ctx: Context = None) -> str:
    """Check progress of a running test execution.

    Returns current status, completed/running tasks, and recent log entries.
    Poll every 10-15 seconds until status is completed, failed, or timeout.

    Args:
        execution_id: Execution ID returned by run_test.
    """
    client = _get_client(ctx)
    try:
        return await testing.get_test_status(client, execution_id)
    except WebQAAPIError as e:
        raise ToolError(e.message) from e


@mcp.tool()
async def get_test_report(execution_id: str, ctx: Context = None) -> str:
    """Get test results after execution completes.

    Returns pass/fail summary, duration, and a link to the full HTML report.
    Call this after get_test_status shows completed/failed/timeout status.

    Args:
        execution_id: Execution ID returned by run_test.
    """
    client = _get_client(ctx)
    try:
        return await testing.get_test_report(client, execution_id)
    except WebQAAPIError as e:
        raise ToolError(e.message) from e


@mcp.tool()
async def cancel_test(execution_id: str, ctx: Context = None) -> str:
    """Cancel a running test execution.

    Args:
        execution_id: Execution ID returned by run_test.
    """
    client = _get_client(ctx)
    try:
        return await testing.cancel_test(client, execution_id)
    except WebQAAPIError as e:
        raise ToolError(e.message) from e


@mcp.tool()
async def list_businesses(ctx: Context = None) -> str:
    """List all configured businesses (test projects).

    Returns business IDs and names. Use the ID with list_environments to see
    available test environments and their URLs.
    """
    client = _get_client(ctx)
    try:
        return await businesses.list_businesses(client)
    except WebQAAPIError as e:
        raise ToolError(e.message) from e


@mcp.tool()
async def list_environments(business_id: str, ctx: Context = None) -> str:
    """List test environments for a business.

    Shows environment URLs, names, and auth types. Useful for discovering
    what URLs are configured for testing.

    Args:
        business_id: Business ID from list_businesses.
    """
    client = _get_client(ctx)
    try:
        return await businesses.list_environments(client, business_id)
    except WebQAAPIError as e:
        raise ToolError(e.message) from e


@mcp.tool()
async def list_executions(
    business_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 10,
    ctx: Context = None,
) -> str:
    """List recent test executions.

    Args:
        business_id: Filter by business ID (optional).
        status: Filter by status: running, completed, failed (optional).
        limit: Maximum number of results (default 10).
    """
    client = _get_client(ctx)
    try:
        return await executions.list_executions(
            client,
            business_id=business_id,
            status=status,
            limit=limit,
        )
    except WebQAAPIError as e:
        raise ToolError(e.message) from e


def main() -> None:
    """CLI entry point for webqa-mcp-server."""
    mcp.run()


if __name__ == '__main__':
    main()
