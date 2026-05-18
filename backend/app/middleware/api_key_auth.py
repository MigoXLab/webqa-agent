"""API Key authentication middleware."""
import hashlib
import logging
from datetime import datetime, timezone

from app.database import AsyncSessionLocal
from app.models.api_key import APIKey
from fastapi import Request
from sqlalchemy import select, update
from starlette.middleware.base import (BaseHTTPMiddleware,
                                       RequestResponseEndpoint)
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

BEARER_PREFIX = 'Bearer '
KEY_PREFIX = 'wqa_'


def _extract_api_key(request: Request) -> str:
    """Extract API key from X-API-Key or Authorization header."""
    key = request.headers.get('X-WebQA-Key', '')
    if key.startswith(KEY_PREFIX):
        return key

    auth = request.headers.get('Authorization', '')
    if auth.startswith(BEARER_PREFIX):
        token = auth[len(BEARER_PREFIX):]
        if token.startswith(KEY_PREFIX):
            return token

    return ''


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate requests via API Key.

    Checks X-API-Key header first, then Authorization: Bearer.
    No key: passes through. Invalid key: returns 401.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint,
    ) -> Response:
        token = _extract_api_key(request)
        if not token:
            if request.headers.get('X-WebQA-Key', ''):
                return JSONResponse(
                    status_code=401,
                    content={'detail': {'code': 6004, 'message': 'Malformed API key'}},
                )
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
