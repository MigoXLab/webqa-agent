"""Business API routes."""
from typing import Optional
from uuid import UUID

from app.database import get_db
from app.models import Business, Environment, TestCase
from app.schemas.business import (BusinessCreate, BusinessListResponse,
                                  BusinessResponse, BusinessUpdate)
from app.schemas.common import APIResponse
from app.schemas.test_case import TestCaseListResponse, TestCaseResponse
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

router = APIRouter()


@router.get('', response_model=APIResponse[BusinessListResponse])
async def list_businesses(
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
    offset: int = 0,
):
    """Get all businesses."""
    # Count total
    count_result = await db.execute(select(func.count(Business.id)))
    total = count_result.scalar() or 0

    # Get businesses with environments
    result = await db.execute(
        select(Business)
        .options(selectinload(Business.environments))
        .order_by(Business.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    businesses = result.scalars().all()

    return APIResponse(
        data=BusinessListResponse(
            items=[BusinessResponse.model_validate(b) for b in businesses],
            total=total
        )
    )


@router.post('', response_model=APIResponse[BusinessResponse], status_code=status.HTTP_201_CREATED)
async def create_business(
    data: BusinessCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new business with environments."""
    # Check if name already exists
    existing = await db.execute(
        select(Business).where(Business.name == data.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={'code': 3001, 'message': f"业务名称 '{data.name}' 已存在"}
        )

    # Create business
    business = Business(
        name=data.name,
        description=data.description,
    )
    db.add(business)
    await db.flush()  # Get the business ID

    # Create environments
    for env_data in data.environments:
        env = Environment(
            business_id=business.id,
            name=env_data.name,
            url=env_data.url,
            browser_config=env_data.browser_config,
            ignore_rules=env_data.ignore_rules,
            auth_type=env_data.auth_type,
            sso_username=env_data.sso_username,
            sso_password=env_data.sso_password,
            sso_env=env_data.sso_env or 'prod',
            cookies=env_data.cookies,
        )
        db.add(env)

    await db.commit()

    # Reload with relationships
    result = await db.execute(
        select(Business)
        .options(selectinload(Business.environments))
        .where(Business.id == business.id)
    )
    business = result.scalar_one()

    return APIResponse(data=BusinessResponse.model_validate(business))


@router.get('/{business_id}', response_model=APIResponse[BusinessResponse])
async def get_business(
    business_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a business by ID."""
    result = await db.execute(
        select(Business)
        .options(selectinload(Business.environments))
        .where(Business.id == business_id)
    )
    business = result.scalar_one_or_none()

    if not business:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2001, 'message': '业务不存在'}
        )

    return APIResponse(data=BusinessResponse.model_validate(business))


@router.put('/{business_id}', response_model=APIResponse[BusinessResponse])
async def update_business(
    business_id: UUID,
    data: BusinessUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a business."""
    result = await db.execute(
        select(Business)
        .options(selectinload(Business.environments))
        .where(Business.id == business_id)
    )
    business = result.scalar_one_or_none()

    if not business:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2001, 'message': '业务不存在'}
        )

    # Check name uniqueness if changing
    if data.name and data.name != business.name:
        existing = await db.execute(
            select(Business).where(Business.name == data.name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={'code': 3001, 'message': f"业务名称 '{data.name}' 已存在"}
            )
        business.name = data.name

    if data.description is not None:
        business.description = data.description

    # Update environments if provided
    if data.environments is not None:
        # Get existing environment IDs
        existing_env_ids = {env.id for env in business.environments}
        new_env_ids = {env.id for env in data.environments if env.id}

        # Delete removed environments
        for env in business.environments:
            if env.id not in new_env_ids:
                await db.delete(env)

        # Update or create environments
        for env_data in data.environments:
            if env_data.id and env_data.id in existing_env_ids:
                # Update existing
                env_result = await db.execute(
                    select(Environment).where(Environment.id == env_data.id)
                )
                env = env_result.scalar_one()
                env.name = env_data.name
                env.url = env_data.url
                env.browser_config = env_data.browser_config
                env.ignore_rules = env_data.ignore_rules
                env.auth_type = env_data.auth_type
                env.sso_username = env_data.sso_username
                if env_data.sso_password:  # Only update if provided
                    env.sso_password = env_data.sso_password
                env.sso_env = env_data.sso_env or env.sso_env or 'prod'
                env.cookies = env_data.cookies
            else:
                # Create new
                env = Environment(
                    business_id=business.id,
                    name=env_data.name,
                    url=env_data.url,
                    browser_config=env_data.browser_config,
                    ignore_rules=env_data.ignore_rules,
                    auth_type=env_data.auth_type,
                    sso_username=env_data.sso_username,
                    sso_password=env_data.sso_password,
                    sso_env=env_data.sso_env or 'prod',
                    cookies=env_data.cookies,
                )
                db.add(env)

    await db.commit()

    # Reload
    result = await db.execute(
        select(Business)
        .options(selectinload(Business.environments))
        .where(Business.id == business_id)
    )
    business = result.scalar_one()

    return APIResponse(data=BusinessResponse.model_validate(business))


@router.delete('/{business_id}', response_model=APIResponse)
async def delete_business(
    business_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a business."""
    result = await db.execute(
        select(Business).where(Business.id == business_id)
    )
    business = result.scalar_one_or_none()

    if not business:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2001, 'message': '业务不存在'}
        )

    await db.delete(business)
    await db.commit()

    return APIResponse(message='业务已删除')


# Nested routes for test cases
@router.get('/{business_id}/cases', response_model=APIResponse[TestCaseListResponse])
async def list_business_cases(
    business_id: UUID,
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[str] = None,
):
    """Get all test cases for a business."""
    # Verify business exists
    business_result = await db.execute(
        select(Business).where(Business.id == business_id)
    )
    if not business_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2001, 'message': '业务不存在'}
        )

    # Build query
    query = select(TestCase).where(TestCase.business_id == business_id)
    if status_filter:
        query = query.where(TestCase.status == status_filter)
    query = query.order_by(TestCase.sort_order.asc(), TestCase.created_at.asc())

    result = await db.execute(query)
    cases = result.scalars().all()

    return APIResponse(
        data=TestCaseListResponse(
            items=[TestCaseResponse.model_validate(c) for c in cases],
            total=len(cases)
        )
    )
