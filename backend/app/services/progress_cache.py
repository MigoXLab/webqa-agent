"""Progress cache service using Redis.

Unified progress caching for local development and cluster deployments.
Progress data remains after execution completes (cleaned up automatically when
TTL expires), supporting viewing logs from historical runs.
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import redis.asyncio as redis
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Redis connection pool (lazy-loaded)
_redis_pool: Optional[redis.ConnectionPool] = None
_redis_client: Optional[redis.Redis] = None


def _get_progress_key(execution_id: str) -> str:
    """Build the Redis key for progress cache."""
    return f'webqa:progress:{execution_id}'


async def get_redis_client() -> Optional[redis.Redis]:
    """Get Redis client (singleton)."""
    global _redis_pool, _redis_client

    if _redis_client is not None:
        return _redis_client

    try:
        _redis_pool = redis.ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=10,
        )
        _redis_client = redis.Redis(connection_pool=_redis_pool)

        # Test connection
        await _redis_client.ping()
        logger.info(f'[Redis] 连接成功: {settings.redis_url}')
        return _redis_client
    except Exception as e:
        logger.warning(f'[Redis] 连接失败: {e}，将回退到内存缓存')
        _redis_client = None
        return None


# In-memory fallback when Redis is unavailable
_memory_cache: Dict[str, Dict] = {}


async def set_progress(execution_id: str, progress_data: Dict[str, Any]) -> bool:
    """Persist execution progress to cache.

    Args:
        execution_id: Execution ID
        progress_data: Progress payload (e.g. completed, running, logs)

    Returns:
        Whether the save succeeded
    """
    # Add metadata
    data = {
        **progress_data,
        'execution_id': execution_id,
        'updated_at': datetime.now().isoformat(),
    }

    client = await get_redis_client()

    if client:
        try:
            key = _get_progress_key(execution_id)
            await client.setex(
                key,
                settings.PROGRESS_CACHE_TTL,
                json.dumps(data, ensure_ascii=False)
            )
            return True
        except Exception as e:
            logger.warning(f'[Redis] 写入进度失败: {e}')

    # Fall back to in-memory cache
    _memory_cache[execution_id] = data
    return True


async def get_progress(execution_id: str) -> Optional[Dict[str, Any]]:
    """Load execution progress.

    Args:
        execution_id: Execution ID

    Returns:
        Progress data, or None if missing
    """
    client = await get_redis_client()

    if client:
        try:
            key = _get_progress_key(execution_id)
            data = await client.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.warning(f'[Redis] 读取进度失败: {e}')

    # Fall back to in-memory cache
    return _memory_cache.get(execution_id)


async def refresh_progress_ttl(execution_id: str) -> bool:
    """Refresh progress cache TTL (call after execution completes to extend
    expiry for the UI).

    Args:
        execution_id: Execution ID

    Returns:
        Whether the refresh succeeded
    """
    client = await get_redis_client()

    if client:
        try:
            key = _get_progress_key(execution_id)
            await client.expire(key, settings.PROGRESS_CACHE_TTL)
            return True
        except Exception as e:
            logger.warning(f'[Redis] 刷新 TTL 失败: {e}')

    # In-memory cache has no TTL management
    return True


async def delete_progress(execution_id: str) -> bool:
    """Delete progress cache (optional; usually rely on TTL expiry).

    Args:
        execution_id: Execution ID

    Returns:
        Whether the delete succeeded
    """
    client = await get_redis_client()

    if client:
        try:
            key = _get_progress_key(execution_id)
            await client.delete(key)
            return True
        except Exception as e:
            logger.warning(f'[Redis] 删除进度失败: {e}')

    # Fall back to in-memory cache
    _memory_cache.pop(execution_id, None)
    return True


async def close_redis() -> None:
    """Close Redis connections (call on application shutdown)."""
    global _redis_client, _redis_pool

    if _redis_client:
        await _redis_client.close()
        _redis_client = None

    if _redis_pool:
        await _redis_pool.disconnect()
        _redis_pool = None
