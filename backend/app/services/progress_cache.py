"""Progress cache service using Redis.

支持本地开发和集群部署的统一进度缓存方案。 执行完成后进度数据仍保留（TTL 过期自动清理），支持查看历史执行的日志。
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import redis.asyncio as redis
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Redis 连接池（懒加载）
_redis_pool: Optional[redis.ConnectionPool] = None
_redis_client: Optional[redis.Redis] = None


def _get_progress_key(execution_id: str) -> str:
    """生成进度缓存的 Redis key."""
    return f'webqa:progress:{execution_id}'


async def get_redis_client() -> Optional[redis.Redis]:
    """获取 Redis 客户端（单例模式）"""
    global _redis_pool, _redis_client

    if _redis_client is not None:
        return _redis_client

    try:
        _redis_pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=10,
        )
        _redis_client = redis.Redis(connection_pool=_redis_pool)

        # 测试连接
        await _redis_client.ping()
        logger.info(f'[Redis] 连接成功: {settings.REDIS_URL}')
        return _redis_client
    except Exception as e:
        logger.warning(f'[Redis] 连接失败: {e}，将回退到内存缓存')
        _redis_client = None
        return None


# 内存缓存回退（Redis 不可用时使用）
_memory_cache: Dict[str, Dict] = {}


async def set_progress(execution_id: str, progress_data: Dict[str, Any]) -> bool:
    """保存执行进度到缓存。

    Args:
        execution_id: 执行 ID
        progress_data: 进度数据，包含 completed, running, logs 等字段

    Returns:
        是否保存成功
    """
    # 添加元数据
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

    # 回退到内存缓存
    _memory_cache[execution_id] = data
    return True


async def get_progress(execution_id: str) -> Optional[Dict[str, Any]]:
    """获取执行进度。

    Args:
        execution_id: 执行 ID

    Returns:
        进度数据，如果不存在返回 None
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

    # 回退到内存缓存
    return _memory_cache.get(execution_id)


async def refresh_progress_ttl(execution_id: str) -> bool:
    """刷新进度缓存的 TTL（执行完成后调用，延长过期时间供前端查看）。

    Args:
        execution_id: 执行 ID

    Returns:
        是否刷新成功
    """
    client = await get_redis_client()

    if client:
        try:
            key = _get_progress_key(execution_id)
            await client.expire(key, settings.PROGRESS_CACHE_TTL)
            return True
        except Exception as e:
            logger.warning(f'[Redis] 刷新 TTL 失败: {e}')

    # 内存缓存不需要 TTL 管理
    return True


async def delete_progress(execution_id: str) -> bool:
    """删除进度缓存（可选，通常让 TTL 自动过期）。

    Args:
        execution_id: 执行 ID

    Returns:
        是否删除成功
    """
    client = await get_redis_client()

    if client:
        try:
            key = _get_progress_key(execution_id)
            await client.delete(key)
            return True
        except Exception as e:
            logger.warning(f'[Redis] 删除进度失败: {e}')

    # 回退到内存缓存
    _memory_cache.pop(execution_id, None)
    return True


async def close_redis() -> None:
    """关闭 Redis 连接（应用关闭时调用）"""
    global _redis_client, _redis_pool

    if _redis_client:
        await _redis_client.close()
        _redis_client = None

    if _redis_pool:
        await _redis_pool.disconnect()
        _redis_pool = None
