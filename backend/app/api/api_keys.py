"""API Key management routes."""
import hashlib
import secrets
from datetime import timedelta
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
KEY_RANDOM_LENGTH = 40


def _generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns (full_key, key_hash, key_prefix).
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
    """Create a new API key.

    The full key is returned ONCE.
    """
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
