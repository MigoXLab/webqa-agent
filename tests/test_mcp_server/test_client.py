"""Tests for WebQAClient."""
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from webqa_agent.mcp_server.client import WebQAAPIError, WebQAClient


@pytest.fixture
def client():
    return WebQAClient(base_url='http://test:8000', api_key='wqa_testkey')


@pytest.mark.asyncio
async def test_list_businesses_success(client):
    mock_response = httpx.Response(
        200,
        json={'data': {'items': [{'id': '123', 'name': 'Test Biz'}], 'total': 1}},
        request=httpx.Request('GET', 'http://test:8000/api/v1/businesses'),
    )
    with patch.object(client._client, 'get', new_callable=AsyncMock, return_value=mock_response):
        result = await client.list_businesses()
    assert len(result) == 1
    assert result[0]['name'] == 'Test Biz'


@pytest.mark.asyncio
async def test_create_execution_success(client):
    mock_response = httpx.Response(
        201,
        json={'data': {'id': 'exec-123', 'status': 'pending'}},
        request=httpx.Request('POST', 'http://test:8000/api/v1/executions'),
    )
    with patch.object(client._client, 'post', new_callable=AsyncMock, return_value=mock_response):
        result = await client.create_execution({'trigger_type': 'mcp_quick', 'gen_config': {}})
    assert result['id'] == 'exec-123'


@pytest.mark.asyncio
async def test_unauthorized_raises_error(client):
    mock_response = httpx.Response(
        401,
        json={'detail': {'message': 'Invalid API key'}},
        request=httpx.Request('GET', 'http://test:8000/api/v1/businesses'),
    )
    with patch.object(client._client, 'get', new_callable=AsyncMock, return_value=mock_response):
        with pytest.raises(WebQAAPIError, match='Invalid API key'):
            await client.list_businesses()


@pytest.mark.asyncio
async def test_server_error_raises_error(client):
    mock_response = httpx.Response(
        500,
        json={'detail': 'Internal server error'},
        request=httpx.Request('GET', 'http://test:8000/api/v1/businesses'),
    )
    with patch.object(client._client, 'get', new_callable=AsyncMock, return_value=mock_response):
        with pytest.raises(WebQAAPIError, match='Backend service error'):
            await client.list_businesses()
