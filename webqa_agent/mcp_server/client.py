"""Async HTTP client for WebQA SaaS backend API."""
from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

API_PREFIX = '/api/v1'


class WebQAAPIError(Exception):
    """Raised when the backend returns an error response."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


class WebQAClient:
    """Async HTTP client wrapping all SaaS backend API calls."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={'X-WebQA-Key': api_key},
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Extract data from response or raise WebQAAPIError."""
        if response.status_code == 401:
            raise WebQAAPIError(401, 'Invalid API key')
        if response.status_code == 404:
            detail = response.json().get('detail', {})
            msg = detail.get('message', 'Resource not found') if isinstance(detail, dict) else str(detail)
            raise WebQAAPIError(404, f'Resource not found: {msg}')
        if response.status_code == 429:
            raise WebQAAPIError(429, 'Server busy, concurrent limit reached')
        if response.status_code == 400:
            detail = response.json().get('detail', {})
            msg = detail.get('message', 'Bad request') if isinstance(detail, dict) else str(detail)
            raise WebQAAPIError(400, msg)
        if response.status_code >= 500:
            raise WebQAAPIError(response.status_code, f'Backend service error: {response.text[:200]}')
        response.raise_for_status()
        body = response.json()
        return body.get('data', body)

    async def create_execution(self, params: dict[str, Any]) -> dict[str, Any]:
        resp = await self._client.post(f'{API_PREFIX}/executions', json=params)
        return self._handle_response(resp)

    async def get_execution_status(self, execution_id: str) -> dict[str, Any]:
        resp = await self._client.get(f'{API_PREFIX}/executions/{execution_id}')
        return self._handle_response(resp)

    async def get_execution_progress(self, execution_id: str) -> dict[str, Any]:
        resp = await self._client.get(f'{API_PREFIX}/executions/{execution_id}/progress')
        return self._handle_response(resp)

    async def cancel_execution(self, execution_id: str) -> dict[str, Any]:
        resp = await self._client.post(f'{API_PREFIX}/executions/{execution_id}/stop')
        return self._handle_response(resp)

    async def list_businesses(self) -> list[dict[str, Any]]:
        resp = await self._client.get(f'{API_PREFIX}/businesses')
        data = self._handle_response(resp)
        return data.get('items', [])

    async def list_environments(self, business_id: str) -> list[dict[str, Any]]:
        resp = await self._client.get(f'{API_PREFIX}/businesses/{business_id}')
        data = self._handle_response(resp)
        return data.get('environments', [])

    async def list_files(self, business_id: str) -> list[dict[str, Any]]:
        resp = await self._client.get(f'{API_PREFIX}/files/{business_id}')
        data = self._handle_response(resp)
        return data.get('items', [])

    async def upload_file(self, business_id: str, local_path: str) -> dict[str, Any]:
        path = Path(local_path).expanduser()
        content_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        with path.open('rb') as file_obj:
            resp = await self._client.post(
                f'{API_PREFIX}/files/{business_id}/upload',
                files={'file': (path.name, file_obj, content_type)},
            )
        return self._handle_response(resp)

    async def list_executions(
        self,
        business_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {'limit': limit}
        if business_id:
            params['business_id'] = business_id
        if status:
            params['status'] = status
        resp = await self._client.get(f'{API_PREFIX}/executions', params=params)
        data = self._handle_response(resp)
        return data.get('items', [])
