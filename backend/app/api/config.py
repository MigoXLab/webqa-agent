"""Config API routes."""
from typing import Optional

from app.config import get_settings
from app.schemas.common import APIResponse
from fastapi import APIRouter

router = APIRouter()
settings = get_settings()


@router.get('/models')
async def get_available_models(mode: Optional[str] = None):
    """Get available LLM models.

    Args:
        mode: 'gen' for AI exploration mode, otherwise returns Run mode models.
    """
    if mode == 'gen':
        return APIResponse(
            data={
                'models': settings.gen_models,
                'default': settings.gen_default_model,
            }
        )
    return APIResponse(
        data={
            'models': settings.available_models,
            'default': settings.LLM_DEFAULT_MODEL,
        }
    )


@router.get('/oss')
async def get_oss_config():
    """Get OSS configuration for direct upload."""
    # Return only public-safe config for frontend direct upload
    if not settings.OSS_ENDPOINT or not settings.OSS_BUCKET:
        return APIResponse(
            data={
                'enabled': False,
                'message': 'OSS not configured'
            }
        )

    return APIResponse(
        data={
            'enabled': True,
            'endpoint': settings.OSS_ENDPOINT,
            'bucket': settings.OSS_BUCKET,
            'region': settings.OSS_ENDPOINT.split('.')[0].replace('oss-', ''),
        }
    )
