"""Business and environment query tools."""
from __future__ import annotations

from webqa_agent.mcp_server.client import WebQAClient


async def list_businesses(client: WebQAClient) -> str:
    """List all businesses with IDs and names."""
    items = await client.list_businesses()
    if not items:
        return 'No businesses found.'
    lines = [f'{b["id"]}  {b.get("name", "")}' for b in items]
    return '\n'.join(lines)


async def list_environments(client: WebQAClient, business_id: str) -> str:
    """List environments for a business."""
    envs = await client.list_environments(business_id)
    if not envs:
        return f'No environments for business {business_id}.'
    lines = []
    for e in envs:
        name = e.get('name', '')
        url = e.get('url', '')
        auth = e.get('auth_type', 'none')
        lines.append(f'{e.get("id", "?")}  {name}  {url}  auth={auth}')
    return '\n'.join(lines)
