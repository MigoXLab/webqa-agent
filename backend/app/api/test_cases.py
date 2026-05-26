"""TestCase API routes."""
import logging
from typing import List
from uuid import UUID

import yaml
from app.database import get_db
from app.models import Business, TestCase
from app.schemas.common import APIResponse
from app.schemas.test_case import (TestCaseCreate, TestCaseExport,
                                   TestCaseImport, TestCaseResponse,
                                   TestCaseUpdate)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()
logger = logging.getLogger(__name__)


def _convert_steps_to_dict(steps: list) -> list:
    """Convert TestStep schema objects to dict format for JSONB storage."""
    result = []
    for step in steps:
        step_dict = {'step_type': step.step_type}
        if step.step_type == 'action':
            step_dict['description'] = step.description or ''
        elif step.step_type == 'verify':
            step_dict['assertion'] = step.assertion or ''
        elif step.step_type == 'switch_account':
            step_dict['switch_account'] = step.switch_account or ''
        if step.args:
            step_dict['args'] = step.args
        result.append(step_dict)
    return result


@router.post('', response_model=APIResponse[TestCaseResponse], status_code=status.HTTP_201_CREATED)
async def create_test_case(
    data: TestCaseCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new test case."""
    # Verify business exists
    business_result = await db.execute(
        select(Business).where(Business.id == data.business_id)
    )
    if not business_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2001, 'message': '业务不存在'}
        )

    # Convert steps to dict format
    steps = _convert_steps_to_dict(data.steps)

    # Calculate sort_order: max existing + 1
    max_order_result = await db.execute(
        select(func.coalesce(func.max(TestCase.sort_order), 0))
        .where(TestCase.business_id == data.business_id)
    )
    next_order = max_order_result.scalar() + 1

    test_case = TestCase(
        business_id=data.business_id,
        name=data.name,
        description=data.description,
        login_required=data.login_required,
        account=data.account,
        steps=steps,
        version=data.version,
        snapshot=data.snapshot,
        use_snapshot=data.use_snapshot,
        status=data.status,
        sort_order=next_order,
    )
    db.add(test_case)
    await db.commit()
    await db.refresh(test_case)

    logger.info(f'[API] Created test case: id={test_case.id}, name={data.name}, business={data.business_id}')
    return APIResponse(data=TestCaseResponse.model_validate(test_case))


@router.get('/{case_id}', response_model=APIResponse[TestCaseResponse])
async def get_test_case(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a test case by ID."""
    result = await db.execute(
        select(TestCase).where(TestCase.id == case_id)
    )
    test_case = result.scalar_one_or_none()

    if not test_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2003, 'message': '用例不存在'}
        )

    return APIResponse(data=TestCaseResponse.model_validate(test_case))


@router.put('/{case_id}', response_model=APIResponse[TestCaseResponse])
async def update_test_case(
    case_id: UUID,
    data: TestCaseUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a test case."""
    result = await db.execute(
        select(TestCase).where(TestCase.id == case_id)
    )
    test_case = result.scalar_one_or_none()

    if not test_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2003, 'message': '用例不存在'}
        )

    # Update fields. Nullable fields must support explicit clearing.
    if 'name' in data.model_fields_set and data.name is not None:
        test_case.name = data.name
    if 'description' in data.model_fields_set:
        test_case.description = data.description
    if 'login_required' in data.model_fields_set and data.login_required is not None:
        test_case.login_required = data.login_required
    if 'account' in data.model_fields_set:
        test_case.account = data.account
    if 'steps' in data.model_fields_set and data.steps is not None:
        test_case.steps = _convert_steps_to_dict(data.steps)
    if 'version' in data.model_fields_set:
        test_case.version = data.version
    if 'snapshot' in data.model_fields_set:
        test_case.snapshot = data.snapshot
    if 'use_snapshot' in data.model_fields_set:
        test_case.use_snapshot = data.use_snapshot
    if 'status' in data.model_fields_set and data.status is not None:
        test_case.status = data.status
    if 'sort_order' in data.model_fields_set and data.sort_order is not None:
        test_case.sort_order = data.sort_order

    await db.commit()
    await db.refresh(test_case)

    logger.info(f'[API] Updated test case: id={case_id}')
    return APIResponse(data=TestCaseResponse.model_validate(test_case))


@router.delete('/{case_id}', response_model=APIResponse)
async def delete_test_case(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a test case."""
    result = await db.execute(
        select(TestCase).where(TestCase.id == case_id)
    )
    test_case = result.scalar_one_or_none()

    if not test_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2003, 'message': '用例不存在'}
        )

    await db.delete(test_case)
    await db.commit()

    logger.info(f'[API] Deleted test case: id={case_id}')
    return APIResponse(message='用例已删除')


# Import/Export routes (nested under businesses in the main router)
async def import_cases_from_yaml(
    business_id: UUID,
    yaml_content: str,
    db: AsyncSession,
) -> List[TestCase]:
    """Import test cases from YAML content."""
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        logger.warning(f'[API] YAML 解析失败: business={business_id}, error={e}')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={'code': 1002, 'message': f'YAML格式错误: {str(e)}'}
        )

    if not data or 'cases' not in data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={'code': 1002, 'message': "YAML格式错误: 缺少 'cases' 字段"}
        )

    # Check for duplicate names against existing cases in this business
    import_names = [c.get('name', 'Unnamed Case') for c in data['cases']]

    existing_result = await db.execute(
        select(TestCase.name)
        .where(TestCase.business_id == business_id)
        .where(TestCase.name.in_(import_names))
    )
    existing_names = [row[0] for row in existing_result.all()]
    if existing_names:
        dup_list = '、'.join(existing_names[:5])
        suffix = f' 等 {len(existing_names)} 个' if len(existing_names) > 5 else ''
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                'code': 1003,
                'message': f'存在重名用例：{dup_list}{suffix}，请修改后重新导入',
            }
        )

    # Check for duplicates within the import file itself
    seen_names: set[str] = set()
    dup_in_file = []
    for name in import_names:
        if name in seen_names:
            dup_in_file.append(name)
        seen_names.add(name)
    if dup_in_file:
        dup_list = '、'.join(list(set(dup_in_file))[:5])
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                'code': 1003,
                'message': f'导入文件内存在重名用例：{dup_list}，请修改后重新导入',
            }
        )

    # Get current max sort_order for this business
    max_order_result = await db.execute(
        select(func.coalesce(func.max(TestCase.sort_order), 0))
        .where(TestCase.business_id == business_id)
    )
    current_max_order = max_order_result.scalar()

    imported_cases = []
    for idx, case_data in enumerate(data['cases']):
        # Parse steps
        steps = []
        for step in case_data.get('steps', []):
            if 'action' in step:
                step_dict = {
                    'step_type': 'action',
                    'description': step['action'],
                }
            elif 'verify' in step:
                step_dict = {
                    'step_type': 'verify',
                    'assertion': step['verify'],
                }
            elif 'switch_account' in step:
                step_dict = {
                    'step_type': 'switch_account',
                    'switch_account': step['switch_account'],
                }
            else:
                continue

            if 'args' in step:
                step_dict['args'] = step['args']
            steps.append(step_dict)

        test_case = TestCase(
            business_id=business_id,
            name=case_data.get('name', 'Unnamed Case'),
            description=case_data.get('description'),
            login_required=case_data.get('login_required', False),
            account=case_data.get('account'),
            steps=steps,
            version=case_data.get('version'),
            snapshot=case_data.get('snapshot'),
            use_snapshot=case_data.get('use_snapshot'),
            status='active',
            sort_order=current_max_order + idx + 1,
        )
        db.add(test_case)
        imported_cases.append(test_case)

    await db.commit()

    # Refresh all cases
    for case in imported_cases:
        await db.refresh(case)

    logger.info(f'[API] Imported {len(imported_cases)} test cases for business={business_id}')
    return imported_cases


def export_cases_to_yaml(cases: List[TestCase]) -> str:
    """Export test cases to YAML format."""
    yaml_cases = []

    for case in cases:
        case_dict = {
            'name': case.name,
            'login_required': case.login_required,
            'steps': [],
        }

        if case.account:
            case_dict['account'] = case.account
        if case.version:
            case_dict['version'] = case.version
        if case.snapshot:
            case_dict['snapshot'] = case.snapshot
        if case.use_snapshot:
            case_dict['use_snapshot'] = case.use_snapshot

        for step in case.steps:
            step_dict = {}
            if step.get('step_type') == 'action':
                step_dict['action'] = step.get('description', '')
            elif step.get('step_type') == 'verify':
                step_dict['verify'] = step.get('assertion', '')
            elif step.get('step_type') == 'switch_account':
                step_dict['switch_account'] = step.get('switch_account', '')

            if 'args' in step and step['args']:
                step_dict['args'] = step['args']

            case_dict['steps'].append(step_dict)

        yaml_cases.append(case_dict)

    return yaml.dump({'cases': yaml_cases}, allow_unicode=True, default_flow_style=False)


# =============================================================================
# Import/Export API Endpoints
# =============================================================================

@router.post('/import/{business_id}', response_model=APIResponse, status_code=status.HTTP_201_CREATED)
async def import_test_cases(
    business_id: UUID,
    data: TestCaseImport,
    db: AsyncSession = Depends(get_db),
):
    """Import test cases from YAML content."""
    # Verify business exists
    business_result = await db.execute(
        select(Business).where(Business.id == business_id)
    )
    if not business_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2001, 'message': '业务不存在'}
        )

    imported_cases = await import_cases_from_yaml(business_id, data.yaml_content, db)

    return APIResponse(
        data={
            'imported_count': len(imported_cases),
            'cases': [TestCaseResponse.model_validate(c) for c in imported_cases]
        },
        message=f'成功导入 {len(imported_cases)} 个测试用例'
    )


@router.get('/export/{business_id}', response_model=APIResponse[TestCaseExport])
async def export_test_cases(
    business_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Export all test cases for a business to YAML format."""
    # Verify business exists
    business_result = await db.execute(
        select(Business).where(Business.id == business_id)
    )
    if not business_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 2001, 'message': '业务不存在'}
        )

    # Get all test cases for the business
    result = await db.execute(
        select(TestCase)
        .where(TestCase.business_id == business_id)
        .order_by(TestCase.sort_order.asc(), TestCase.created_at.asc())
    )
    cases = result.scalars().all()

    yaml_content = export_cases_to_yaml(cases)

    return APIResponse(
        data=TestCaseExport(yaml_content=yaml_content, count=len(cases))
    )
