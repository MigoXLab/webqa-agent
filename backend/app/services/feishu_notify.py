"""Feishu (Lark) webhook notification service.

Sends execution results to Feishu group via webhook bot.
Card format:
- Header: 执行业务：XX ✅ 测试通过 / ❌ 测试不通过
- Body: 任务ID, 执行完成时间, 分割线, passed/warning/failed counts, @mentions
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import pytz

logger = logging.getLogger(__name__)

SHANGHAI_TZ = pytz.timezone('Asia/Shanghai')


def _format_time(dt: Optional[datetime] = None) -> str:
    """Format datetime to Shanghai timezone string."""
    if dt is None:
        dt = datetime.now(pytz.utc)
    return dt.astimezone(SHANGHAI_TZ).strftime('%Y-%m-%d %H:%M:%S')


def _parse_notify_user_ids(raw: Optional[str]) -> List[str]:
    """Parse comma/space separated open_ids into a list.

    Supports separators: , ; ， ；and whitespace.
    """
    if not raw or not raw.strip():
        return []
    import re
    parts = re.split(r'[,;，；\s]+', raw.strip())
    return [p.strip() for p in parts if p.strip()]


def _build_card(
    execution_id: str,
    business_name: str,
    completed_at: Optional[datetime],
    result_count: Optional[Dict[str, Any]],
    oss_report_url: Optional[str] = None,
    feishu_notify_user_ids: Optional[str] = None,
) -> dict:
    """Build Feishu interactive card message.

    Args:
        execution_id: Execution UUID string
        business_name: Business name
        completed_at: When execution completed
        result_count: { total, passed, failed, warning }
        oss_report_url: Optional OSS report URL
        feishu_notify_user_ids: Comma-separated Feishu open_ids to @mention when failed > 0
    """
    passed = result_count.get('passed', 0) if result_count else 0
    failed = result_count.get('failed', 0) if result_count else 0
    warning = result_count.get('warning', 0) if result_count else 0

    # Determine overall result
    is_passed = failed == 0
    header_template = 'green' if is_passed else 'red'
    result_emoji = '✅ 测试通过' if is_passed else '❌ 测试不通过'

    completion_time = _format_time(completed_at)

    # Card title: 执行业务：XX ✅ 测试通过 / ❌ 测试不通过
    header_title = f'执行业务：{business_name} {result_emoji}'

    # Build detail content: 任务ID + 执行完成时间
    detail_content = (
        f'**任务ID：** {execution_id[:8]}\n'
        f'**执行完成时间：** {completion_time}'
    )

    # Build counts content
    counts_content = (
        f'passed: **{passed}**\n'
        f'warning: **{warning}**\n'
        f'failed: **{failed}**'
    )

    # @mention users when failed > 0
    user_ids = _parse_notify_user_ids(feishu_notify_user_ids)
    at_content = ''
    if not is_passed and user_ids:
        at_tags = ' '.join(f'<at id={uid}></at>' for uid in user_ids)
        at_content = at_tags

    # Build card elements
    elements = [
        # 任务ID & 完成时间
        {
            'tag': 'div',
            'text': {
                'content': detail_content,
                'tag': 'lark_md',
            },
        },
        # 分割线
        {
            'tag': 'hr',
        },
        # passed / warning / failed 横排
        {
            'tag': 'div',
            'text': {
                'content': counts_content,
                'tag': 'lark_md',
            },
        },
    ]

    # @通知人
    if at_content:
        elements.append({
            'tag': 'div',
            'text': {
                'content': at_content,
                'tag': 'lark_md',
            },
        })

    # Add report link if available
    if oss_report_url:
        elements.append({
            'tag': 'action',
            'actions': [
                {
                    'tag': 'button',
                    'text': {
                        'content': '📊 查看报告',
                        'tag': 'lark_md',
                    },
                    'url': oss_report_url,
                    'type': 'primary',
                },
            ],
        })

    card = {
        'msg_type': 'interactive',
        'card': {
            'header': {
                'title': {
                    'content': header_title,
                    'tag': 'plain_text',
                },
                'template': header_template,
            },
            'elements': elements,
        },
    }

    return card


async def send_feishu_notification(
    webhook_url: str,
    execution_id: str,
    business_name: str,
    completed_at: Optional[datetime],
    result_count: Optional[Dict[str, Any]],
    oss_report_url: Optional[str] = None,
    feishu_notify_user_id: Optional[str] = None,
) -> bool:
    """Send execution result notification to Feishu group via webhook.

    Args:
        webhook_url: Feishu bot webhook URL
        execution_id: Execution UUID string
        business_name: Business name
        completed_at: When execution completed
        result_count: { total, passed, failed, warning }
        oss_report_url: Optional OSS report URL
        feishu_notify_user_id: Comma-separated Feishu open_ids to @mention when failed > 0

    Returns:
        True if notification was sent successfully, False otherwise
    """
    if not webhook_url:
        return False

    try:
        card = _build_card(
            execution_id=execution_id,
            business_name=business_name,
            completed_at=completed_at,
            result_count=result_count,
            oss_report_url=oss_report_url,
            feishu_notify_user_ids=feishu_notify_user_id,
        )

        logger.info(f'[Feishu] Sending notification for execution {execution_id} to {webhook_url[:50]}...')

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=card)
            response.raise_for_status()

            resp_data = response.json()
            if resp_data.get('code') == 0:
                logger.info(f'[Feishu] Notification sent successfully for execution {execution_id}')
                return True
            else:
                logger.warning(f'[Feishu] Notification failed: {resp_data}')
                return False

    except Exception as e:
        logger.exception(f'[Feishu] Failed to send notification for execution {execution_id}: {e}')
        return False
