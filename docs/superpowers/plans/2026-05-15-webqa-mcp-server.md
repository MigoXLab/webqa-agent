# WebQA MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose webqa-agent's testing capabilities as an MCP server that proxies requests to the SaaS backend via HTTP, with API Key authentication and a frontend key management UI.

**Architecture:** Stateless FastMCP server as a `webqa_agent.mcp_server` subpackage. All tools call the SaaS backend REST API via httpx. `run_test` uses MCP Tasks for async execution. Backend adds API Key auth middleware and a `mcp_quick` trigger type.

**Tech Stack:** FastMCP 2.x, httpx, pydantic-settings, FastAPI (backend), React + shadcn/ui (frontend)

**Spec:** `docs/superpowers/specs/2026-05-15-webqa-mcp-server-design.md`

______________________________________________________________________

**Scope note:** This plan covers 3 subsystems in dependency order:

1. **Backend changes** (API Key system + quick-mode execution) — Tasks 1-4
2. **MCP server subpackage** — Tasks 5-10
3. **Frontend API Key UI** — Tasks 11-12

**MCP Tasks (v2 follow-up):** The spec describes MCP Tasks (`taskSupport: "required"`) for `run_test`, but MCP Tasks is experimental (spec 2025-11-25) and FastMCP support may be incomplete. This plan implements a pragmatic v1: `run_test` returns the execution_id immediately, and the Agent polls via `get_test_status`. The `TaskManager` is implemented and ready to wire in when FastMCP stabilizes Task support.

______________________________________________________________________

## Task 1: Backend — API Key Database Model & Migration

**Files:**

- Create: `backend/app/models/api_key.py`

- Modify: `backend/app/models/__init__.py`

- Create: `backend/alembic/versions/xxxx_add_api_keys_table.py` (via autogenerate)

- [ ] **Step 1: Create the APIKey model**

Create `backend/app/models/api_key.py`:

```python
"""API Key model."""
import uuid
from datetime import datetime
from typing import Optional

from app.database import Base
from app.utils.datetime_utils import now_with_tz
from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class APIKey(Base):
    """API Key for MCP and external API access."""

    __tablename__ = 'api_keys'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    key_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    key_prefix: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_used: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_with_tz,
        nullable=False,
    )
```

- [ ] **Step 2: Register model in `__init__.py`**

Add to `backend/app/models/__init__.py`:

```python
from app.models.api_key import APIKey

__all__ = ['Business', 'Environment', 'TestCase', 'Execution', 'ScheduledTask', 'APIKey']
```

- [ ] **Step 3: Generate Alembic migration**

Run:

```bash
cd backend && alembic revision --autogenerate -m "add api_keys table"
```

Expected: A new migration file in `backend/alembic/versions/` with `create_table('api_keys', ...)`.

- [ ] **Step 4: Apply migration**

Run:

```bash
cd backend && alembic upgrade head
```

Expected: Table `api_keys` created in the database.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/api_key.py backend/app/models/__init__.py backend/alembic/versions/
git commit -m "feat(backend): add api_keys database model and migration"
```

______________________________________________________________________

## Task 2: Backend — API Key CRUD API

**Files:**

- Create: `backend/app/schemas/api_key.py`

- Create: `backend/app/api/api_keys.py`

- Modify: `backend/app/api/__init__.py`

- [ ] **Step 1: Create API Key schemas**

Create `backend/app/schemas/api_key.py`:

```python
"""API Key schemas."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class APIKeyCreate(BaseModel):
    """Schema for creating an API key."""
    name: str = Field(..., min_length=1, max_length=100)
    expires_in_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=365,
        description='Key expires after N days. Null = never expires.',
    )


class APIKeyResponse(BaseModel):
    """API key response (no secret)."""
    id: UUID
    name: str
    key_prefix: str
    expires_at: Optional[datetime] = None
    last_used: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class APIKeyCreatedResponse(APIKeyResponse):
    """Response after creating a key — includes the full key ONCE."""
    full_key: str


class APIKeyListResponse(BaseModel):
    """List of API keys."""
    items: list[APIKeyResponse]
    total: int
```

- [ ] **Step 2: Create API Key route handler**

Create `backend/app/api/api_keys.py`:

```python
"""API Key management routes."""
import hashlib
import secrets
from datetime import timedelta
from typing import Optional
from uuid import UUID

from app.database import get_db
from app.models.api_key import APIKey
from app.schemas.api_key import (APIKeyCreate, APIKeyCreatedResponse,
                                 APIKeyListResponse, APIKeyResponse)
from app.schemas.common import APIResponse
from app.utils.datetime_utils import now_with_tz
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

KEY_PREFIX = 'wqa_'
KEY_RANDOM_LENGTH = 40  # hex chars


def _generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns:
        (full_key, key_hash, key_prefix)
    """
    random_part = secrets.token_hex(KEY_RANDOM_LENGTH // 2)
    full_key = f'{KEY_PREFIX}{random_part}'
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    key_prefix = full_key[:12]
    return full_key, key_hash, key_prefix


@router.post('', response_model=APIResponse[APIKeyCreatedResponse], status_code=status.HTTP_201_CREATED)
async def create_api_key(
    data: APIKeyCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key. The full key is returned ONCE."""
    full_key, key_hash, key_prefix = _generate_api_key()

    expires_at = None
    if data.expires_in_days is not None:
        expires_at = now_with_tz() + timedelta(days=data.expires_in_days)

    api_key = APIKey(
        user_id='default',
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=data.name,
        expires_at=expires_at,
    )
    db.add(api_key)
    await db.flush()

    response = APIKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=key_prefix,
        expires_at=expires_at,
        last_used=None,
        created_at=api_key.created_at,
        full_key=full_key,
    )
    return APIResponse(data=response)


@router.get('', response_model=APIResponse[APIKeyListResponse])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
):
    """List all API keys (without secrets)."""
    count_result = await db.execute(select(func.count(APIKey.id)))
    total = count_result.scalar() or 0

    result = await db.execute(
        select(APIKey).order_by(APIKey.created_at.desc())
    )
    keys = result.scalars().all()

    return APIResponse(
        data=APIKeyListResponse(
            items=[APIKeyResponse.model_validate(k) for k in keys],
            total=total,
        )
    )


@router.delete('/{key_id}', response_model=APIResponse)
async def delete_api_key(
    key_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Revoke (delete) an API key."""
    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 6001, 'message': 'API Key not found'},
        )

    await db.delete(api_key)
    return APIResponse(data=None, message='API Key deleted')
```

- [ ] **Step 3: Register route in API router**

Add to `backend/app/api/__init__.py`:

```python
from app.api import (businesses, config, environments, executions, files,
                     scheduled_tasks, test_cases, api_keys)

api_router.include_router(api_keys.router, prefix='/settings/api-keys', tags=['api_keys'])
```

- [ ] **Step 4: Verify manually**

Run:

```bash
cd backend && python run.py
```

Test with curl:

```bash
curl -X POST http://localhost:8000/api/v1/settings/api-keys \
  -H 'Content-Type: application/json' \
  -d '{"name": "test-key"}'
```

Expected: 201 response with `full_key` starting with `wqa_`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/api_key.py backend/app/api/api_keys.py backend/app/api/__init__.py
git commit -m "feat(backend): add API Key CRUD endpoints"
```

______________________________________________________________________

## Task 3: Backend — API Key Authentication Middleware

**Files:**

- Create: `backend/app/middleware/api_key_auth.py`

- Modify: `backend/app/main.py`

- [ ] **Step 1: Create API Key auth middleware**

Create `backend/app/middleware/api_key_auth.py`:

```python
"""API Key authentication middleware.

Adds Bearer token authentication as an alternative to session/cookie auth.
When a valid API Key is present in the Authorization header, the request
proceeds with the associated user context.
"""
import hashlib
import logging
from datetime import datetime, timezone

from app.database import AsyncSessionLocal
from app.models.api_key import APIKey
from fastapi import Request
from sqlalchemy import select, update
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

BEARER_PREFIX = 'Bearer '
KEY_PREFIX = 'wqa_'


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Middleware that authenticates requests via API Key.

    If an Authorization header with a valid `wqa_` key is present,
    sets `request.state.api_key_user_id` for downstream handlers.
    If the header is absent, the request passes through unchanged
    (existing auth mechanisms handle it).
    If the header is present but invalid, returns 401.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint,
    ) -> Response:
        auth_header = request.headers.get('Authorization', '')

        if not auth_header.startswith(BEARER_PREFIX):
            return await call_next(request)

        token = auth_header[len(BEARER_PREFIX):]
        if not token.startswith(KEY_PREFIX):
            return await call_next(request)

        key_hash = hashlib.sha256(token.encode()).hexdigest()

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(APIKey).where(APIKey.key_hash == key_hash)
            )
            api_key = result.scalar_one_or_none()

            if api_key is None:
                return JSONResponse(
                    status_code=401,
                    content={'detail': {'code': 6002, 'message': 'Invalid API key'}},
                )

            if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
                return JSONResponse(
                    status_code=401,
                    content={'detail': {'code': 6003, 'message': 'API key expired'}},
                )

            request.state.api_key_user_id = api_key.user_id

            await session.execute(
                update(APIKey)
                .where(APIKey.id == api_key.id)
                .values(last_used=datetime.now(timezone.utc))
            )
            await session.commit()

        return await call_next(request)
```

- [ ] **Step 2: Register middleware in FastAPI app**

Add to `backend/app/main.py`, after the `app = FastAPI(...)` line:

```python
from app.middleware.api_key_auth import APIKeyAuthMiddleware

app.add_middleware(APIKeyAuthMiddleware)
```

- [ ] **Step 3: Verify manually**

```bash
# Create a key
KEY=$(curl -s -X POST http://localhost:8000/api/v1/settings/api-keys \
  -H 'Content-Type: application/json' \
  -d '{"name": "test"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['full_key'])")

# Use it to list businesses
curl -H "Authorization: Bearer $KEY" http://localhost:8000/api/v1/businesses
```

Expected: 200 response with businesses list (same as cookie-authenticated request).

- [ ] **Step 4: Commit**

```bash
git add backend/app/middleware/ backend/app/main.py
git commit -m "feat(backend): add API Key authentication middleware"
```

______________________________________________________________________

## Task 4: Backend — Quick Mode Execution (`mcp_quick` trigger type)

**Files:**

- Modify: `backend/app/schemas/execution.py`

- Modify: `backend/app/services/executor.py`

- [ ] **Step 1: Extend ExecutionCreate schema**

In `backend/app/schemas/execution.py`, modify the `validate_trigger_type_requirements` validator to accept `mcp_quick`:

```python
@model_validator(mode='after')
def validate_trigger_type_requirements(self):
    trigger_type = self.trigger_type
    test_case_ids = self.test_case_ids
    gen_config = self.gen_config
    business_id = self.business_id

    if trigger_type in ('manual', 'debug'):
        if not business_id:
            raise ValueError(f'{trigger_type} mode requires business_id')
        if not test_case_ids or len(test_case_ids) < 1:
            raise ValueError(f'{trigger_type} mode requires at least one test_case_id')
    elif trigger_type == 'gen':
        if not gen_config:
            raise ValueError('gen mode requires gen_config')
    elif trigger_type == 'mcp_quick':
        if not gen_config:
            raise ValueError('mcp_quick mode requires gen_config')
        if not gen_config.get('url'):
            raise ValueError('mcp_quick mode requires url in gen_config')
        if not gen_config.get('task'):
            raise ValueError('mcp_quick mode requires task in gen_config')

    return self
```

Also update the `trigger_type` field pattern:

```python
trigger_type: str = Field(default='manual', pattern='^(manual|debug|gen|mcp_quick)$')
```

- [ ] **Step 2: Handle `mcp_quick` in executor**

In `backend/app/services/executor.py`, modify the `_resolve_gen_runner_source` function to recognize `mcp_quick`:

```python
def _resolve_gen_runner_source(gen_config: Optional[Dict[str, Any]]) -> str:
    """Resolve which gen runner should execute this task."""
    if not isinstance(gen_config, dict):
        return 'standard'

    raw = str(gen_config.get('runner_source') or '').strip().lower()
    if raw in {'cc-mini', 'cc_mini'}:
        return 'cc-mini'

    test_cfg = gen_config.get('test_config') or {}
    if bool(test_cfg.get('use_cc_mini', False)):
        return 'cc-mini'

    return 'standard'
```

And in the execution creation flow in `backend/app/api/executions.py`, handle `mcp_quick` like `gen` but without requiring `business_id`:

In the `create_execution` function, after the business/environment validation block, add:

```python
    # mcp_quick mode: no business/environment required
    if data.trigger_type == 'mcp_quick':
        gen_config_dict = data.gen_config or {}
        gen_config_dict.setdefault('runner_source', 'cc-mini')
        gen_config_dict.setdefault('test_config', {})
        gen_config_dict['test_config']['use_cc_mini'] = True
        gen_config_dict['test_config']['business_objectives'] = gen_config_dict.get('task', '')
        gen_config_dict.setdefault('target', {})
        gen_config_dict['target']['url'] = gen_config_dict.get('url', '')
```

- [ ] **Step 3: Verify manually**

```bash
curl -X POST http://localhost:8000/api/v1/executions \
  -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "trigger_type": "mcp_quick",
    "gen_config": {
      "url": "https://example.com",
      "task": "verify the homepage loads"
    }
  }'
```

Expected: 201 response with execution record, status `pending`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas/execution.py backend/app/services/executor.py backend/app/api/executions.py
git commit -m "feat(backend): add mcp_quick trigger type for quick-mode execution"
```

______________________________________________________________________

## Task 5: MCP Server — Package Scaffold & Config

**Files:**

- Create: `webqa_agent/mcp_server/__init__.py`

- Create: `webqa_agent/mcp_server/config.py`

- Modify: `pyproject.toml`

- [ ] **Step 1: Create config module**

Create `webqa_agent/mcp_server/__init__.py`:

```python
"""WebQA MCP Server — exposes webqa testing capabilities via MCP protocol."""
```

Create `webqa_agent/mcp_server/config.py`:

```python
"""MCP Server configuration via environment variables."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings for the WebQA MCP server."""

    api_url: str = 'http://localhost:8000'
    api_key: str = ''
    default_model: str = ''

    model_config = SettingsConfigDict(
        env_prefix='WEBQA_',
    )


settings = Settings()
```

- [ ] **Step 2: Add dependencies and CLI entry point to pyproject.toml**

Add `fastmcp>=2.0.0` and `httpx>=0.28.0` to the `dependencies` list in `pyproject.toml`.

Add to `[project.scripts]`:

```toml
webqa-mcp-server = "webqa_agent.mcp_server.server:main"
```

- [ ] **Step 3: Install dependencies**

Run:

```bash
uv sync
```

Expected: `fastmcp` and `httpx` installed, `webqa-mcp-server` command available.

- [ ] **Step 4: Commit**

```bash
git add webqa_agent/mcp_server/__init__.py webqa_agent/mcp_server/config.py pyproject.toml
git commit -m "feat(mcp): scaffold mcp_server subpackage with config"
```

______________________________________________________________________

## Task 6: MCP Server — HTTP Client (`WebQAClient`)

**Files:**

- Create: `webqa_agent/mcp_server/client.py`

- Create: `tests/test_mcp_server/test_client.py`

- [ ] **Step 1: Write tests for WebQAClient**

Create `tests/test_mcp_server/__init__.py` (empty) and `tests/test_mcp_server/test_client.py`:

```python
"""Tests for WebQAClient."""
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from webqa_agent.mcp_server.client import WebQAClient, WebQAAPIError


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_server/test_client.py -v`

Expected: FAIL — `WebQAClient` not yet defined.

- [ ] **Step 3: Implement WebQAClient**

Create `webqa_agent/mcp_server/client.py`:

```python
"""Async HTTP client for WebQA SaaS backend API."""
from __future__ import annotations

import logging
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
            headers={'Authorization': f'Bearer {api_key}'},
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
        resp = await self._client.get(f'{API_PREFIX}/environments', params={'business_id': business_id})
        data = self._handle_response(resp)
        return data.get('items', [])

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_server/test_client.py -v`

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add webqa_agent/mcp_server/client.py tests/test_mcp_server/
git commit -m "feat(mcp): add WebQAClient HTTP client with tests"
```

______________________________________________________________________

## Task 7: MCP Server — TaskManager (MCP Tasks state mapping)

**Files:**

- Create: `webqa_agent/mcp_server/task_manager.py`

- Create: `tests/test_mcp_server/test_task_manager.py`

- [ ] **Step 1: Write tests for TaskManager**

Create `tests/test_mcp_server/test_task_manager.py`:

```python
"""Tests for TaskManager."""
import pytest
from datetime import datetime, timezone, timedelta

from webqa_agent.mcp_server.task_manager import TaskManager


@pytest.fixture
def manager():
    return TaskManager()


def test_create_task(manager):
    task_id = manager.create_task('exec-123')
    state = manager.get_task(task_id)
    assert state is not None
    assert state.execution_id == 'exec-123'
    assert state.status == 'working'


def test_get_nonexistent_task_returns_none(manager):
    assert manager.get_task('nonexistent') is None


def test_map_backend_status_pending(manager):
    assert manager.map_backend_status('pending') == 'working'
    assert manager.map_backend_status('running') == 'working'


def test_map_backend_status_completed(manager):
    assert manager.map_backend_status('completed') == 'completed'
    assert manager.map_backend_status('passed') == 'completed'


def test_map_backend_status_failed(manager):
    assert manager.map_backend_status('failed') == 'failed'
    assert manager.map_backend_status('timeout') == 'failed'


def test_map_backend_status_cancelled(manager):
    assert manager.map_backend_status('cancelled') == 'cancelled'
    assert manager.map_backend_status('stopped') == 'cancelled'


def test_adaptive_poll_interval_early(manager):
    task_id = manager.create_task('exec-1')
    interval = manager.get_poll_interval(task_id)
    assert interval == 3000


def test_adaptive_poll_interval_steady(manager):
    task_id = manager.create_task('exec-1')
    state = manager.get_task(task_id)
    state.created_at = datetime.now(timezone.utc) - timedelta(seconds=60)
    interval = manager.get_poll_interval(task_id)
    assert interval == 5000


def test_cleanup_expired(manager):
    task_id = manager.create_task('exec-1', ttl_ms=1)
    import time
    time.sleep(0.01)
    manager.cleanup_expired()
    assert manager.get_task(task_id) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_server/test_task_manager.py -v`

Expected: FAIL — `TaskManager` not defined.

- [ ] **Step 3: Implement TaskManager**

Create `webqa_agent/mcp_server/task_manager.py`:

```python
"""MCP task ID <-> backend execution_id mapping."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

_STATUS_MAP = {
    'pending': 'working',
    'running': 'working',
    'completed': 'completed',
    'passed': 'completed',
    'failed': 'failed',
    'timeout': 'failed',
    'cancelled': 'cancelled',
    'stopped': 'cancelled',
}

DEFAULT_TTL_MS = 3_600_000  # 1 hour


@dataclass
class TaskState:
    """State for a single MCP task."""

    execution_id: str
    status: str = 'working'
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_ms: int = DEFAULT_TTL_MS
    status_message: str = ''


class TaskManager:
    """In-memory mapping from MCP task IDs to backend execution IDs."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskState] = {}

    def create_task(
        self, execution_id: str, ttl_ms: int = DEFAULT_TTL_MS,
    ) -> str:
        task_id = str(uuid.uuid4())
        self._tasks[task_id] = TaskState(
            execution_id=execution_id,
            ttl_ms=ttl_ms,
        )
        return task_id

    def get_task(self, task_id: str) -> Optional[TaskState]:
        return self._tasks.get(task_id)

    def update_status(
        self, task_id: str, backend_status: str, status_message: str = '',
    ) -> None:
        state = self._tasks.get(task_id)
        if state:
            state.status = self.map_backend_status(backend_status)
            state.status_message = status_message

    @staticmethod
    def map_backend_status(backend_status: str) -> str:
        return _STATUS_MAP.get(backend_status, 'working')

    def get_poll_interval(self, task_id: str) -> int:
        state = self._tasks.get(task_id)
        if not state:
            return 5000
        elapsed = (datetime.now(timezone.utc) - state.created_at).total_seconds()
        if elapsed < 30:
            return 3000
        return 5000

    def cleanup_expired(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [
            tid for tid, state in self._tasks.items()
            if now > state.created_at + timedelta(milliseconds=state.ttl_ms)
        ]
        for tid in expired:
            del self._tasks[tid]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_server/test_task_manager.py -v`

Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add webqa_agent/mcp_server/task_manager.py tests/test_mcp_server/test_task_manager.py
git commit -m "feat(mcp): add TaskManager for MCP task state mapping"
```

______________________________________________________________________

## Task 8: MCP Server — Query Tools (list_businesses, list_environments, list_executions)

**Files:**

- Create: `webqa_agent/mcp_server/tools/__init__.py`

- Create: `webqa_agent/mcp_server/tools/businesses.py`

- Create: `webqa_agent/mcp_server/tools/executions.py`

- [ ] **Step 1: Create tools package**

Create `webqa_agent/mcp_server/tools/__init__.py`:

```python
"""MCP tool definitions for WebQA."""
```

- [ ] **Step 2: Implement business tools**

Create `webqa_agent/mcp_server/tools/businesses.py`:

```python
"""Business and environment query tools."""
from __future__ import annotations

import json
from typing import Optional

from webqa_agent.mcp_server.client import WebQAClient


async def list_businesses(client: WebQAClient) -> str:
    """List all available businesses (test projects) with their IDs and names."""
    businesses = await client.list_businesses()
    if not businesses:
        return 'No businesses found.'
    lines = ['| ID | Name |', '| --- | --- |']
    for b in businesses:
        lines.append(f"| {b['id']} | {b.get('name', '')} |")
    return '\n'.join(lines)


async def list_environments(client: WebQAClient, business_id: str) -> str:
    """List environments for a specific business."""
    envs = await client.list_environments(business_id)
    if not envs:
        return f'No environments found for business {business_id}.'
    lines = ['| ID | Name | URL |', '| --- | --- | --- |']
    for e in envs:
        lines.append(f"| {e['id']} | {e.get('name', '')} | {e.get('url', '')} |")
    return '\n'.join(lines)
```

- [ ] **Step 3: Implement execution list tool**

Create `webqa_agent/mcp_server/tools/executions.py`:

```python
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
    """List recent test executions with optional filters."""
    executions = await client.list_executions(
        business_id=business_id, status=status, limit=limit,
    )
    if not executions:
        return 'No executions found.'
    lines = ['| ID | Status | Business | Created |', '| --- | --- | --- | --- |']
    for e in executions:
        lines.append(
            f"| {e['id'][:8]}... | {e.get('status', '')} "
            f"| {e.get('business_name', 'N/A')} | {e.get('created_at', '')[:19]} |"
        )
    return '\n'.join(lines)
```

- [ ] **Step 4: Commit**

```bash
git add webqa_agent/mcp_server/tools/
git commit -m "feat(mcp): add query tools (businesses, environments, executions)"
```

______________________________________________________________________

## Task 9: MCP Server — Testing Tools (run_test, get_test_status, get_test_report, cancel_test)

**Files:**

- Create: `webqa_agent/mcp_server/tools/testing.py`

- [ ] **Step 1: Implement testing tools**

Create `webqa_agent/mcp_server/tools/testing.py`:

```python
"""Testing tools — run, status, report, cancel."""
from __future__ import annotations

from typing import Any, Optional

from webqa_agent.mcp_server.client import WebQAClient


def _validate_run_params(
    url: Optional[str],
    task: Optional[str],
    business_id: Optional[str],
    environment_id: Optional[str],
    business_objectives: Optional[str],
) -> tuple[str, dict[str, Any]]:
    """Validate and build execution params. Returns (mode, params_dict).

    Raises ValueError if params are invalid.
    """
    quick = url is not None or task is not None
    standard = business_id is not None or environment_id is not None or business_objectives is not None

    if quick and standard:
        raise ValueError(
            'Cannot mix quick mode (url/task) with standard mode '
            '(business_id/environment_id/business_objectives). Choose one.'
        )
    if not quick and not standard:
        raise ValueError(
            'Provide either quick mode (url + task) or standard mode '
            '(business_id + environment_id + business_objectives).'
        )

    if quick:
        if not url:
            raise ValueError('Quick mode requires url.')
        if not task:
            raise ValueError('Quick mode requires task.')
        return 'quick', {
            'trigger_type': 'mcp_quick',
            'gen_config': {'url': url, 'task': task},
        }

    if not business_id:
        raise ValueError('Standard mode requires business_id.')
    if not environment_id:
        raise ValueError('Standard mode requires environment_id.')
    if not business_objectives:
        raise ValueError('Standard mode requires business_objectives.')
    return 'standard', {
        'trigger_type': 'gen',
        'business_id': business_id,
        'environment_id': environment_id,
        'gen_config': {'business_objectives': business_objectives},
    }


async def run_test(
    client: WebQAClient,
    url: Optional[str] = None,
    task: Optional[str] = None,
    business_id: Optional[str] = None,
    environment_id: Optional[str] = None,
    business_objectives: Optional[str] = None,
    model: Optional[str] = None,
    workers: int = 1,
) -> dict[str, Any]:
    """Create a test execution. Returns execution data dict."""
    _, params = _validate_run_params(url, task, business_id, environment_id, business_objectives)
    if model:
        params['model'] = model
    params['workers'] = workers
    return await client.create_execution(params)


async def get_test_status(client: WebQAClient, execution_id: str) -> str:
    """Get current status and progress of a test execution."""
    progress = await client.get_execution_progress(execution_id)

    lines = [f"**Status:** {progress.get('status', 'unknown')}"]

    completed = progress.get('completed', [])
    if completed:
        lines.append('\n**Completed:**')
        for t in completed:
            result = t.get('result', '')
            icon = '✅' if result == 'passed' else '❌' if result == 'failed' else '⚠️'
            duration = f" ({t['duration']:.1f}s)" if t.get('duration') else ''
            lines.append(f"- {icon} {t.get('name', 'unnamed')}{duration}")

    running = progress.get('running', [])
    if running:
        lines.append('\n**Running:**')
        for t in running:
            elapsed = f" ({t['elapsed']:.1f}s)" if t.get('elapsed') else ''
            lines.append(f"- ⏳ {t.get('name', 'unnamed')}{elapsed}")

    logs = progress.get('logs', [])
    if logs:
        lines.append(f"\n**Recent logs:** ({len(logs)} entries)")
        for log in logs[-5:]:
            lines.append(f"  {log}")

    return '\n'.join(lines)


async def get_test_report(
    client: WebQAClient, execution_id: str, format: str = 'summary',
) -> str:
    """Get test report for a completed execution."""
    execution = await client.get_execution_status(execution_id)

    if format == 'url':
        report_url = execution.get('report_url') or execution.get('oss_report_url')
        if report_url:
            return f'Report URL: {report_url}'
        return 'No report URL available yet.'

    status = execution.get('status', 'unknown')
    result_count = execution.get('result_count') or {}
    lines = [
        f'## Test Report — {execution_id[:8]}...',
        f'**Status:** {status}',
    ]

    if result_count:
        total = sum(result_count.values())
        passed = result_count.get('passed', 0)
        failed = result_count.get('failed', 0)
        warning = result_count.get('warning', 0)
        lines.append(f'**Results:** {passed} passed, {failed} failed, {warning} warning / {total} total')

    started = execution.get('started_at', '')
    completed = execution.get('completed_at', '')
    if started and completed:
        lines.append(f'**Duration:** {started[:19]} → {completed[:19]}')

    report_url = execution.get('report_url') or execution.get('oss_report_url')
    if report_url:
        lines.append(f'\n**Full report:** {report_url}')

    if execution.get('error_message'):
        lines.append(f"\n**Error:** {execution['error_message']}")

    return '\n'.join(lines)


async def cancel_test(client: WebQAClient, execution_id: str) -> str:
    """Cancel a running test execution."""
    result = await client.cancel_execution(execution_id)
    return f"Execution {execution_id[:8]}... cancelled."
```

- [ ] **Step 2: Commit**

```bash
git add webqa_agent/mcp_server/tools/testing.py
git commit -m "feat(mcp): add testing tools (run, status, report, cancel)"
```

______________________________________________________________________

## Task 10: MCP Server — Server Entry Point & Tool Registration

**Files:**

- Create: `webqa_agent/mcp_server/server.py`

- Create: `tests/test_mcp_server/test_tools.py`

- [ ] **Step 1: Write tests for tool parameter validation**

Create `tests/test_mcp_server/test_tools.py`:

```python
"""Tests for MCP tool parameter validation."""
import pytest

from webqa_agent.mcp_server.tools.testing import _validate_run_params


def test_quick_mode_valid():
    mode, params = _validate_run_params(
        url='https://example.com', task='test login', business_id=None,
        environment_id=None, business_objectives=None,
    )
    assert mode == 'quick'
    assert params['trigger_type'] == 'mcp_quick'
    assert params['gen_config']['url'] == 'https://example.com'


def test_standard_mode_valid():
    mode, params = _validate_run_params(
        url=None, task=None, business_id='biz-1',
        environment_id='env-1', business_objectives='test login',
    )
    assert mode == 'standard'
    assert params['trigger_type'] == 'gen'


def test_both_modes_raises():
    with pytest.raises(ValueError, match='Cannot mix'):
        _validate_run_params(
            url='https://example.com', task='test',
            business_id='biz-1', environment_id=None, business_objectives=None,
        )


def test_neither_mode_raises():
    with pytest.raises(ValueError, match='Provide either'):
        _validate_run_params(
            url=None, task=None, business_id=None,
            environment_id=None, business_objectives=None,
        )


def test_quick_mode_missing_task():
    with pytest.raises(ValueError, match='requires task'):
        _validate_run_params(
            url='https://example.com', task=None, business_id=None,
            environment_id=None, business_objectives=None,
        )


def test_standard_mode_missing_environment():
    with pytest.raises(ValueError, match='requires environment_id'):
        _validate_run_params(
            url=None, task=None, business_id='biz-1',
            environment_id=None, business_objectives='test',
        )
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_server/test_tools.py -v`

Expected: All 6 tests PASS (validation logic already implemented in Task 9).

- [ ] **Step 3: Implement server entry point**

Create `webqa_agent/mcp_server/server.py`:

```python
"""FastMCP server for WebQA — entry point and tool registration."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastmcp import FastMCP

from webqa_agent.mcp_server.client import WebQAClient, WebQAAPIError
from webqa_agent.mcp_server.config import settings
from webqa_agent.mcp_server.task_manager import TaskManager
from webqa_agent.mcp_server.tools import businesses, executions, testing

logger = logging.getLogger(__name__)

task_manager = TaskManager()


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
    description='AI-powered web testing: trigger tests, check progress, get reports.',
    lifespan=lifespan,
)


def _get_client(ctx) -> WebQAClient:
    return ctx.request_context.lifespan_context['client']


@mcp.tool()
async def run_test(
    ctx,
    url: Optional[str] = None,
    task: Optional[str] = None,
    business_id: Optional[str] = None,
    environment_id: Optional[str] = None,
    business_objectives: Optional[str] = None,
    model: Optional[str] = None,
    workers: int = 1,
) -> str:
    """Run a web test.

    Two modes (mutually exclusive):
    - Quick mode: provide url + task
    - Standard mode: provide business_id + environment_id + business_objectives
    """
    client = _get_client(ctx)
    try:
        result = await testing.run_test(
            client, url=url, task=task, business_id=business_id,
            environment_id=environment_id, business_objectives=business_objectives,
            model=model or settings.default_model or None, workers=workers,
        )
    except ValueError as e:
        return f'[ERROR] {e}'
    except WebQAAPIError as e:
        return f'[ERROR] {e.message}'

    execution_id = str(result.get('id', ''))
    status = result.get('status', 'pending')
    return (
        f'Test started.\n'
        f'**Execution ID:** {execution_id}\n'
        f'**Status:** {status}\n\n'
        f'Use `get_test_status(execution_id="{execution_id}")` to check progress.'
    )


@mcp.tool()
async def get_test_status(ctx, execution_id: str) -> str:
    """Get current status and progress of a test execution."""
    client = _get_client(ctx)
    try:
        return await testing.get_test_status(client, execution_id)
    except WebQAAPIError as e:
        return f'[ERROR] {e.message}'


@mcp.tool()
async def get_test_report(ctx, execution_id: str, format: str = 'summary') -> str:
    """Get test report for a completed execution.

    Formats: summary (default), detailed, url
    """
    client = _get_client(ctx)
    try:
        return await testing.get_test_report(client, execution_id, format=format)
    except WebQAAPIError as e:
        return f'[ERROR] {e.message}'


@mcp.tool()
async def cancel_test(ctx, execution_id: str) -> str:
    """Cancel a running test execution."""
    client = _get_client(ctx)
    try:
        return await testing.cancel_test(client, execution_id)
    except WebQAAPIError as e:
        return f'[ERROR] {e.message}'


@mcp.tool()
async def list_businesses(ctx) -> str:
    """List all available businesses (test projects) with their IDs and names."""
    client = _get_client(ctx)
    try:
        return await businesses.list_businesses(client)
    except WebQAAPIError as e:
        return f'[ERROR] {e.message}'


@mcp.tool()
async def list_environments(ctx, business_id: str) -> str:
    """List environments for a specific business, including URLs and accounts."""
    client = _get_client(ctx)
    try:
        return await businesses.list_environments(client, business_id)
    except WebQAAPIError as e:
        return f'[ERROR] {e.message}'


@mcp.tool()
async def list_executions(
    ctx,
    business_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 10,
) -> str:
    """List recent test executions with optional filters.

    Status filter: running, completed, failed
    """
    client = _get_client(ctx)
    try:
        return await executions.list_executions(
            client, business_id=business_id, status=status, limit=limit,
        )
    except WebQAAPIError as e:
        return f'[ERROR] {e.message}'


def main():
    """CLI entry point for webqa-mcp-server."""
    mcp.run()


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Verify the server starts**

Run:

```bash
WEBQA_API_KEY=test WEBQA_API_URL=http://localhost:8000 uv run webqa-mcp-server
```

Expected: Server starts and waits for MCP connections on STDIO. Ctrl+C to stop.

- [ ] **Step 5: Commit**

```bash
git add webqa_agent/mcp_server/server.py tests/test_mcp_server/test_tools.py
git commit -m "feat(mcp): add FastMCP server entry point with all 7 tools"
```

______________________________________________________________________

## Task 11: Frontend — API Key Management Page

**Files:**

- Create: `frontend/src/components/ApiKeyManager.tsx`

- Modify: `frontend/src/api/client.ts`

- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Add API types and client functions**

Add to `frontend/src/api/client.ts`:

```typescript
// API Key types
export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  expires_at: string | null;
  last_used: string | null;
  created_at: string;
}

export interface ApiKeyCreated extends ApiKey {
  full_key: string;
}

// API Key endpoints
export async function createApiKey(name: string, expiresInDays?: number): Promise<ApiKeyCreated> {
  const body: any = { name };
  if (expiresInDays) body.expires_in_days = expiresInDays;
  const response = await fetch(`${API_BASE_URL}/settings/api-keys`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error('Failed to create API key');
  const data = await response.json();
  return data.data;
}

export async function listApiKeys(): Promise<ApiKey[]> {
  const response = await fetch(`${API_BASE_URL}/settings/api-keys`);
  if (!response.ok) throw new Error('Failed to list API keys');
  const data = await response.json();
  return data.data.items;
}

export async function deleteApiKey(keyId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/settings/api-keys/${keyId}`, {
    method: 'DELETE',
  });
  if (!response.ok) throw new Error('Failed to delete API key');
}
```

- [ ] **Step 2: Create ApiKeyManager component**

Create `frontend/src/components/ApiKeyManager.tsx`. This component should include:

- A table listing existing keys (name, prefix `wqa_xxxx...`, created date, last used, expiry)

- A "Create API Key" button that opens a dialog with name input + optional expiry selector

- After creation, show the full key once in a copy-to-clipboard dialog with a Claude Code config JSON snippet:

  ```json
  ```

{
"mcpServers": {
"webqa": {
"command": "webqa-mcp-server",
"env": {
"WEBQA_API_URL": "\<current_site_url>",
"WEBQA_API_KEY": "\<full_key>"
}
}
}
}

````

- Each row has a "Revoke" button with confirmation dialog
- Use existing shadcn/ui components: `Table`, `Button`, `Dialog`, `Input`, `Select`, `AlertDialog`

The exact React implementation should follow the existing component patterns in the codebase (see `BusinessManager.tsx`, `ScheduledTaskManager.tsx` for reference).

- [ ] **Step 3: Add route in App.tsx**

Add the ApiKeyManager to the app's navigation/settings area. Check `App.tsx` for the existing routing pattern and add an "API Keys" tab or settings section.

- [ ] **Step 4: Test in browser**

Run:

```bash
cd frontend && npm run dev
````

Verify:

1. Navigate to the API Keys section
2. Create a key — full key displayed with copy button and config snippet
3. Key appears in the list with prefix only
4. Revoke a key — confirmation dialog, key removed from list

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ApiKeyManager.tsx frontend/src/api/client.ts frontend/src/App.tsx
git commit -m "feat(frontend): add API Key management UI"
```

______________________________________________________________________

## Task 12: End-to-End Verification

**Files:**

- No new files

- [ ] **Step 1: Start backend**

```bash
cd backend && python run.py
```

- [ ] **Step 2: Create an API Key via the API**

```bash
curl -s -X POST http://localhost:8000/api/v1/settings/api-keys \
  -H 'Content-Type: application/json' \
  -d '{"name": "e2e-test"}'
```

Save the `full_key` from the response.

- [ ] **Step 3: Start the MCP server with the key**

```bash
WEBQA_API_URL=http://localhost:8000 WEBQA_API_KEY=<full_key> uv run webqa-mcp-server
```

Expected: Server starts on STDIO.

- [ ] **Step 4: Test with FastMCP dev tools**

```bash
WEBQA_API_URL=http://localhost:8000 WEBQA_API_KEY=<full_key> \
  fastmcp dev webqa_agent/mcp_server/server.py
```

In the MCP Inspector:

1. Call `list_businesses` — should return businesses table
2. Call `run_test` with `url=https://example.com` and `task=verify homepage loads` — should return execution ID
3. Call `get_test_status` with the execution ID — should return status
4. Call `cancel_test` with the execution ID — should confirm cancellation

- [ ] **Step 5: Run all MCP server tests**

```bash
uv run pytest tests/test_mcp_server/ -v
```

Expected: All tests PASS.

- [ ] **Step 6: Run pre-commit on all changed files**

```bash
pre-commit run --all-files
```

Expected: All hooks PASS.

- [ ] **Step 7: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address pre-commit and e2e issues"
```
