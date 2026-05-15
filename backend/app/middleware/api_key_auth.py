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


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate requests via API Key in Authorization header.

    Valid `wqa_` key: sets request.state.api_key_user_id, updates last_used.
    No auth header: passes through (existing auth handles it).
    Invalid key: returns 401.
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
