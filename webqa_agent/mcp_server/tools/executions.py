"""Execution query tools."""
from __future__ import annotations

from typing import Optional

from webqa_agent.mcp_server.client import WebQAClient


async def list_executions(
    client: WebQAClient,
    business_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 10,
) -> str:
    """List recent test executions."""
    items = await client.list_executions(
        business_id=business_id, status=status, limit=limit,
    )
    if not items:
        return 'No executions found.'
    lines = []
    for e in items:
        eid = e['id'][:8]
        st = e.get('status', '?')
        biz = e.get('business_name') or 'N/A'
        created = (e.get('created_at') or '')[:16]
        lines.append(f'{eid}  {st:<10} {biz}  {created}')
    return '\n'.join(lines)
