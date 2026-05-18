"""Business and environment query tools."""
from __future__ import annotations

from typing import Any

from webqa_agent.mcp_server.client import WebQAClient


async def list_businesses(client: WebQAClient) -> list[dict[str, Any]]:
    """List all businesses."""
    items = await client.list_businesses()
    return [{'id': b['id'], 'name': b.get('name', '')} for b in items]


async def list_environments(client: WebQAClient, business_id: str) -> list[dict[str, Any]]:
    """List environments for a business."""
    envs = await client.list_environments(business_id)
    return [
        {
            'id': e.get('id', ''),
            'name': e.get('name', ''),
            'url': e.get('url', ''),
            'auth_type': e.get('auth_type', 'none'),
        }
        for e in envs
    ]
