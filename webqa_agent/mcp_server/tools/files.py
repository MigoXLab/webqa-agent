"""Business file tools."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from webqa_agent.mcp_server.client import WebQAClient


async def list_business_files(
    client: WebQAClient,
    business_id: str,
) -> list[dict[str, Any]]:
    """List files staged in a business file pool."""
    items = await client.list_files(business_id)
    return [
        {
            'name': f.get('name', ''),
            'size': f.get('size', 0),
            'type': f.get('type', ''),
            'uploaded_at': f.get('uploaded_at'),
        }
        for f in items
    ]


async def upload_business_file(
    client: WebQAClient,
    business_id: str,
    local_path: str,
) -> dict[str, Any]:
    """Upload a local file into a business file pool."""
    path = Path(local_path).expanduser()
    if not path.is_absolute():
        raise ValueError('local_path must be an absolute path')
    if not path.is_file():
        raise ValueError(f'Local file does not exist: {local_path}')

    result = await client.upload_file(business_id, str(path))
    return {
        'name': result.get('name', path.name),
        'size': result.get('size', 0),
        'type': result.get('type', ''),
        'uploaded_at': result.get('uploaded_at'),
    }
