"""Environment API routes."""
import logging
from typing import Any, Dict, List, Optional
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


def normalize_accounts(
    auth_type: str,
    accounts: Optional[List[Dict[str, Any]]],
    existing_accounts: Optional[List[Dict[str, Any]]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Normalize and validate accounts data.

    - None or [] → None
    - SSO accounts must have sso_username and sso_password
    - Cookies accounts must have cookies
    - Names must be unique
    - Exactly one is_default=true (auto-fix if missing or duplicated)
    - On update: merge missing sso_password from existing_accounts by name
    """
    if auth_type == 'none':
        return None

    if not accounts:
        return None

    # Merge missing sso_password from existing accounts (update scenario)
    if existing_accounts and auth_type == 'sso':
        existing_by_name = {a.get('name'): a for a in existing_accounts if a.get('name')}
        for acc in accounts:
            if not acc.get('sso_password') and acc.get('name') in existing_by_name:
                old = existing_by_name[acc['name']]
                if old.get('sso_password'):
                    acc['sso_password'] = old['sso_password']

    if auth_type == 'sso':
        for acc in accounts:
            if not acc.get('sso_username') or not acc.get('sso_password'):
                raise ValueError(
                    f"SSO 账户 '{acc.get('name', '')}' 缺少 username 或 password"
                )

    if auth_type == 'cookies':
        for acc in accounts:
            if not acc.get('cookies'):
                raise ValueError(
                    f"Cookies 账户 '{acc.get('name', '')}' 缺少 cookies 数据"
                )

    names = [acc.get('name', '') for acc in accounts]
    if len(names) != len(set(names)):
        raise ValueError('账户名称不能重复')

    for acc in accounts:
        acc.setdefault('role', None)
        acc.setdefault('is_default', False)

    defaults = [a for a in accounts if a.get('is_default')]
    if not defaults:
        accounts[0]['is_default'] = True
    elif len(defaults) > 1:
        for acc in accounts:
            acc['is_default'] = False
        defaults[0]['is_default'] = True

    return accounts


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

    try:
        normalized_accounts = normalize_accounts(data.auth_type, data.accounts)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={'code': 2005, 'message': str(e)},
        ) from e

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
        accounts=normalized_accounts,
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
        if data.auth_type == 'none':
            env.sso_username = None
            env.sso_password = None
            env.cookies = None
            env.accounts = None
    if data.sso_username is not None:
        env.sso_username = data.sso_username
    if data.sso_password is not None:
        env.sso_password = data.sso_password
    if data.cookies is not None:
        env.cookies = data.cookies
    if data.accounts is not None:
        new_auth_type = data.auth_type or env.auth_type
        try:
            env.accounts = normalize_accounts(new_auth_type, data.accounts, env.accounts)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={'code': 2005, 'message': str(e)},
            ) from e

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
        # Prefer default account from accounts, fallback to legacy sso_username
        sso_username = None
        sso_password = None
        sso_env_val = 'prod'

        if env.accounts:
            default_acc = next(
                (a for a in env.accounts if a.get('is_default')),
                env.accounts[0] if env.accounts else None,
            )
            if default_acc:
                sso_username = default_acc.get('sso_username')
                sso_password = default_acc.get('sso_password')
                sso_env_val = default_acc.get('sso_env', 'prod') or 'prod'

        if not sso_username or not sso_password:
            # Legacy fallback
            sso_username = env.sso_username
            sso_password = env.sso_password
            sso_env_val = getattr(env, 'sso_env', 'prod') or 'prod'

        if not sso_username or not sso_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={'code': 2003, 'message': '当前环境未配置完整 SSO 账号信息，无法生成 cookies'},
            )

        try:
            _, cookies = generate_sso_cookies(sso_username, sso_password, sso_env_val)
        except Exception as exc:
            logger.exception('[EnvAPI] 生成 SSO cookies 失败: env_id=%s, sso_env=%s', env.id, sso_env_val)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={'code': 2004, 'message': f'生成 SSO cookies 失败: {exc}'},
            ) from exc

        return APIResponse(data=EnvironmentCookiesResponse(cookies=cookies or [], source='sso'))

    if env.auth_type == 'cookies':
        return APIResponse(
            data=EnvironmentCookiesResponse(cookies=env.cookies or [], source='environment')
        )

    return APIResponse(data=EnvironmentCookiesResponse(cookies=[], source='none'))
