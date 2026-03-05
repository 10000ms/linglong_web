"""Redis based caching decorator for Linglong services.

提供基于 Redis 的协程缓存装饰器，支持自定义键后缀与按用户隔离。
"""
import hashlib
import inspect
import os
from functools import wraps
from typing import (
    Any,
    Awaitable,
    Callable,
)

import orjson
from redis import asyncio as aioredis

from .resource import Rmanager
from .types import P, R
from ..utils.context import get_context_user_id
from ..utils.log import logger


def _build_cache_key(
        func: Callable[..., Any],
        *,
        add_str: str,
        cache_by_user: bool,
) -> str:
    """Generate a stable cache key based on function source metadata.

    结合函数文件路径、行号、模块与名称生成稳定的缓存键，可选追加自定义后缀与用户 ID。
    """

    source_file = inspect.getsourcefile(func)
    filepath = os.path.abspath(source_file) if source_file else "N/A"
    hash_hex = hashlib.md5(filepath.encode("utf-8"), usedforsecurity=False).hexdigest()

    try:
        _, line_no = inspect.getsourcelines(func)
    except (TypeError, OSError):  # pragma: no cover - fallback when inspect fails
        line_no = "N/A"

    key_parts = [hash_hex, str(line_no), func.__module__, func.__name__]
    if add_str:
        key_parts.append(add_str)
    if cache_by_user:
        user_id = get_context_user_id()
        if user_id:
            key_parts.append(str(user_id))
    return ":".join(key_parts)


def cacher(
        expire_time: int,
        add_str: str = "",
        cache_by_user: bool = False,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Cache coroutine results in Redis for a configurable TTL.

    Args:
        expire_time: 缓存秒数 / TTL in seconds.
        add_str: 自定义键后缀 / Optional suffix for more granularity.
        cache_by_user: 是否按用户区分缓存 / Split cache entries by user id.
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            if Rmanager.RedisPool is None:
                logger.warning("redis cache is not available")
                return await func(*args, **kwargs)

            redis_client = aioredis.Redis(connection_pool=Rmanager.RedisPool)
            cache_key = _build_cache_key(func, add_str=add_str, cache_by_user=cache_by_user)

            try:
                cached = await redis_client.get(cache_key)
                if cached:
                    logger.debug("redis cache hit: %s", cache_key)
                    return orjson.loads(cached)

                result = await func(*args, **kwargs)
                await redis_client.setex(cache_key, expire_time, orjson.dumps(result))
                return result
            except Exception as exc:  # noqa: BLE001
                logger.error("redis cache error: %s", exc, exc_info=True)
                return await func(*args, **kwargs)

        return wrapper

    return decorator
