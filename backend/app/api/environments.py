"""Environment API routes."""
import logging
from uuid import UUID

from app.database import get_db
from app.models import Business, Environment
from app.schemas.common import APIResponse
from app.schemas.environment import (EnvironmentCookiesResponse,
                                     EnvironmentCreate, EnvironmentResponse,
                                     EnvironmentUpdate)
from app.services.executor import generate_sso_cookies
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post('', response_model=APIResponse[EnvironmentResponse], status_code=status.HTTP_201_CREATED)
async def create_environment(
    data: EnvironmentCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new environment."""
    # Verify business exists
    business_result = await db.execute(
        select(Business).where(Business.id == data.business_id)
    )
    if not business_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2001, 'message': '业务不存在'}
        )

    env = Environment(
        business_id=data.business_id,
        name=data.name,
        url=data.url,
        browser_config=data.browser_config,
        ignore_rules=data.ignore_rules,
        auth_type=data.auth_type,
        sso_username=data.sso_username,
        sso_password=data.sso_password,
        cookies=data.cookies,
    )
    db.add(env)
    await db.commit()
    await db.refresh(env)

    return APIResponse(data=EnvironmentResponse.model_validate(env))


@router.get('/{environment_id}', response_model=APIResponse[EnvironmentResponse])
async def get_environment(
    environment_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get an environment by ID."""
    result = await db.execute(
        select(Environment).where(Environment.id == environment_id)
    )
    env = result.scalar_one_or_none()

    if not env:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2002, 'message': '环境不存在'}
        )

    return APIResponse(data=EnvironmentResponse.model_validate(env))


@router.put('/{environment_id}', response_model=APIResponse[EnvironmentResponse])
async def update_environment(
    environment_id: UUID,
    data: EnvironmentUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an environment."""
    result = await db.execute(
        select(Environment).where(Environment.id == environment_id)
    )
    env = result.scalar_one_or_none()

    if not env:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2002, 'message': '环境不存在'}
        )

    # Update fields
    if data.name is not None:
        env.name = data.name
    if data.url is not None:
        env.url = data.url
    if data.browser_config is not None:
        env.browser_config = data.browser_config
    if data.ignore_rules is not None:
        env.ignore_rules = data.ignore_rules
    if data.auth_type is not None:
        env.auth_type = data.auth_type
    if data.sso_username is not None:
        env.sso_username = data.sso_username
    if data.sso_password is not None:
        env.sso_password = data.sso_password
    if data.cookies is not None:
        env.cookies = data.cookies

    await db.commit()
    await db.refresh(env)

    return APIResponse(data=EnvironmentResponse.model_validate(env))


@router.delete('/{environment_id}', response_model=APIResponse)
async def delete_environment(
    environment_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete an environment."""
    result = await db.execute(
        select(Environment).where(Environment.id == environment_id)
    )
    env = result.scalar_one_or_none()

    if not env:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2002, 'message': '环境不存在'}
        )

    await db.delete(env)
    await db.commit()

    return APIResponse(message='环境已删除')


@router.post('/{environment_id}/generate-cookies', response_model=APIResponse[EnvironmentCookiesResponse])
async def generate_environment_cookies(
    environment_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Generate cookies for an environment without persisting."""
    result = await db.execute(
        select(Environment).where(Environment.id == environment_id)
    )
    env = result.scalar_one_or_none()

    if not env:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2002, 'message': '环境不存在'}
        )

    if env.auth_type == 'sso':
        if not env.sso_username or not env.sso_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={'code': 2003, 'message': '当前环境未配置完整 SSO 账号信息，无法生成 cookies'}
            )

        sso_env = getattr(env, 'sso_env', 'prod') or 'prod'
        try:
            _, cookies = generate_sso_cookies(env.sso_username, env.sso_password, sso_env)
        except Exception as exc:
            logger.exception('[EnvAPI] 生成 SSO cookies 失败: env_id=%s, sso_env=%s', env.id, sso_env)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={'code': 2004, 'message': f'生成 SSO cookies 失败: {exc}'}
            ) from exc

        return APIResponse(data=EnvironmentCookiesResponse(cookies=cookies or [], source='sso'))

    if env.auth_type == 'cookies':
        return APIResponse(
            data=EnvironmentCookiesResponse(cookies=env.cookies or [], source='environment')
        )

    return APIResponse(data=EnvironmentCookiesResponse(cookies=[], source='none'))
