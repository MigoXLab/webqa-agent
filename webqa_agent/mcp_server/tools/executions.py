"""Execution query tools."""
from __future__ import annotations

from typing import Any, Optional

from webqa_agent.mcp_server.client import WebQAClient


async def list_executions(
    client: WebQAClient,
    business_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """List recent test executions."""
    items = await client.list_executions(
        business_id=business_id, status=status, limit=limit,
    )
    return [
        {
            'execution_id': e['id'],
            'status': e.get('status', ''),
            'business_name': e.get('business_name') or None,
            'created_at': (e.get('created_at') or '')[:19],
        }
        for e in items
    ]
