"""FastMCP server for WebQA — entry point and tool registration."""
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal, Optional

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from webqa_agent.mcp_server.client import WebQAAPIError, WebQAClient
from webqa_agent.mcp_server.config import settings
from webqa_agent.mcp_server.tools import businesses, executions, files, testing

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
        'WebQA is an AI-powered web testing service. '
        'Workflow: run_test -> poll get_test_status every 10s -> get_test_report when done. '
        'Tests take 2-10 minutes. All results are structured JSON.'
    ),
    lifespan=lifespan,
)


def _get_client(ctx: Context) -> WebQAClient:
    return ctx.request_context.lifespan_context['client']


# ---------------------------------------------------------------------------
# Testing tools
# ---------------------------------------------------------------------------

@mcp.tool(
    annotations=ToolAnnotations(
        title='Run Web Test',
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
async def run_test(
    url: Annotated[str, Field(description='Target URL to test')],
    task: Annotated[str, Field(
        description='What to test in natural language. Be specific about actions and expected outcomes. '
        'Example: "Verify homepage loads, search for hello, check results page"',
    )],
    language: Annotated[Literal['zh-CN', 'en-US'], Field(
        description='Report language',
    )] = 'zh-CN',
    model: Annotated[Optional[str], Field(
        description='LLM model override. Uses server default if not set',
    )] = None,
    cookies: Annotated[Optional[list[dict[str, Any]]], Field(
        description='Browser cookies for authenticated testing. '
        'Array of objects: [{"name":"token","value":"xxx","domain":".example.com"}]. '
        'Overrides business_id auth when both are provided',
    )] = None,
    business_id: Annotated[Optional[str], Field(
        description='Business ID from list_businesses. When set, uses the '
        "business's configured auth (SSO/cookies) and test files automatically. "
        'No need to pass cookies separately',
    )] = None,
    environment_id: Annotated[Optional[str], Field(
        description='Environment ID from list_environments. Use with business_id '
        'to select a specific environment. Defaults to the first environment',
    )] = None,
    test_files: Annotated[Optional[list[str]], Field(
        description='Business file-pool names to use. Requires business_id. '
        'Do not pass local paths; call upload_business_file first and pass '
        'the returned file name. Example: ["test.pdf", "invoice.xlsx"]',
    )] = None,
    workers: Annotated[int, Field(
        description='Concurrent test workers', ge=1, le=5,
    )] = 1,
    save_screenshots: Annotated[bool, Field(
        description='Capture screenshots during testing',
    )] = True,
    ctx: Context = None,
) -> dict[str, Any]:
    """Start an AI browser test against a URL.

    The agent navigates the page, performs actions, and verifies results. Tests
    take 2-10 minutes. Returns execution_id for status polling.

    For pages requiring login, either pass cookies directly or set business_id
    to use the platform's pre-configured SSO/cookie auth.
    """
    client = _get_client(ctx)
    try:
        result = await testing.run_test(
            client, url=url, task=task, language=language,
            model=model or settings.default_model or None,
            cookies=cookies, business_id=business_id,
            environment_id=environment_id, test_files=test_files,
            workers=workers, save_screenshots=save_screenshots,
        )
    except ValueError as e:
        raise ToolError(str(e)) from e
    except WebQAAPIError as e:
        raise ToolError(e.message) from e

    return {
        'execution_id': str(result.get('id', '')),
        'status': result.get('status', 'pending'),
    }


@mcp.tool(
    annotations=ToolAnnotations(
        title='Get Test Status',
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_test_status(
    execution_id: Annotated[str, Field(description='Execution ID from run_test')],
    ctx: Context = None,
) -> dict[str, Any]:
    """Check progress of a running test.

    Returns status, task results, and recent logs. Poll every 10s until status
    is completed/failed/timeout.
    """
    client = _get_client(ctx)
    try:
        return await testing.get_test_status(client, execution_id)
    except WebQAAPIError as e:
        raise ToolError(e.message) from e


@mcp.tool(
    annotations=ToolAnnotations(
        title='Get Test Report',
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_test_report(
    execution_id: Annotated[str, Field(description='Execution ID from run_test')],
    ctx: Context = None,
) -> dict[str, Any]:
    """Get test results after execution completes.

    Returns pass/fail counts, duration, and report URL. Call after
    get_test_status shows completed/failed status.
    """
    client = _get_client(ctx)
    try:
        return await testing.get_test_report(client, execution_id)
    except WebQAAPIError as e:
        raise ToolError(e.message) from e


@mcp.tool(
    annotations=ToolAnnotations(
        title='Cancel Test',
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def cancel_test(
    execution_id: Annotated[str, Field(description='Execution ID from run_test')],
    ctx: Context = None,
) -> dict[str, str]:
    """Cancel a running test execution."""
    client = _get_client(ctx)
    try:
        return await testing.cancel_test(client, execution_id)
    except WebQAAPIError as e:
        raise ToolError(e.message) from e


# ---------------------------------------------------------------------------
# Query tools
# ---------------------------------------------------------------------------

@mcp.tool(
    annotations=ToolAnnotations(
        title='List Businesses',
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_businesses(ctx: Context = None) -> list[dict[str, Any]]:
    """List all configured businesses (test projects).

    Returns IDs and names. Use ID with list_environments to see URLs.
    """
    client = _get_client(ctx)
    try:
        return await businesses.list_businesses(client)
    except WebQAAPIError as e:
        raise ToolError(e.message) from e


@mcp.tool(
    annotations=ToolAnnotations(
        title='List Environments',
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_environments(
    business_id: Annotated[str, Field(description='Business ID from list_businesses')],
    ctx: Context = None,
) -> list[dict[str, Any]]:
    """List test environments for a business.

    Shows URLs, names, and auth types.
    """
    client = _get_client(ctx)
    try:
        return await businesses.list_environments(client, business_id)
    except WebQAAPIError as e:
        raise ToolError(e.message) from e


@mcp.tool(
    annotations=ToolAnnotations(
        title='List Business Files',
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_business_files(
    business_id: Annotated[str, Field(description='Business ID from list_businesses')],
    ctx: Context = None,
) -> list[dict[str, Any]]:
    """List files already staged for a business.

    Use this before run_test when the task mentions upload/file attachment.
    run_test.test_files accepts names from this list, not local paths.
    """
    client = _get_client(ctx)
    try:
        return await files.list_business_files(client, business_id)
    except WebQAAPIError as e:
        raise ToolError(e.message) from e


@mcp.tool(
    annotations=ToolAnnotations(
        title='Upload Business File',
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
async def upload_business_file(
    business_id: Annotated[str, Field(description='Business ID from list_businesses')],
    local_path: Annotated[str, Field(
        description='Absolute path to a local file on this machine. The file '
        'is uploaded into the business file pool and can then be referenced by '
        'name in run_test.test_files.',
    )],
    ctx: Context = None,
) -> dict[str, Any]:
    """Upload a local file into a business file pool.

    Call this when upload testing needs a file but list_business_files shows no
    suitable existing file.
    """
    client = _get_client(ctx)
    try:
        return await files.upload_business_file(client, business_id, local_path)
    except ValueError as e:
        raise ToolError(str(e)) from e
    except WebQAAPIError as e:
        raise ToolError(e.message) from e


@mcp.tool(
    annotations=ToolAnnotations(
        title='List Executions',
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_executions(
    business_id: Annotated[Optional[str], Field(
        description='Filter by business ID',
    )] = None,
    status: Annotated[Optional[Literal['running', 'completed', 'failed']], Field(
        description='Filter by execution status',
    )] = None,
    limit: Annotated[int, Field(
        description='Max results', ge=1, le=50,
    )] = 10,
    ctx: Context = None,
) -> list[dict[str, Any]]:
    """List recent test executions with optional filters."""
    client = _get_client(ctx)
    try:
        return await executions.list_executions(
            client, business_id=business_id, status=status, limit=limit,
        )
    except WebQAAPIError as e:
        raise ToolError(e.message) from e


def main() -> None:
    """CLI entry point for webqa-mcp-server."""
    mcp.run()


if __name__ == '__main__':
    main()
