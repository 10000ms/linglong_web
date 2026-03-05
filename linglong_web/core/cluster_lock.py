"""Redis backed cluster wide lock helpers.

提供依赖 Redis 的集群锁装饰器，防止分布式并发执行同一段逻辑。
"""
from functools import wraps
from typing import (
    Any,
    Awaitable,
    Callable,
)

import redis.asyncio as redis

from .errors import ClusterLockError
from .resource import Rmanager
from .types import LockKeyBuilder, OnLockFail, P, R
from ..utils.log import logger


def _get_redis_client() -> redis.Redis | None:
    """Lazily build Redis client from the global pool.

    从 Rmanager 注入的连接池创建 Redis 实例，若池未初始化则返回 ``None``。
    """

    if not Rmanager.RedisPool:
        return None
    return redis.Redis(connection_pool=Rmanager.RedisPool)


def _compose_lock_key(
        lock_prefix: str,
        func: Callable[..., Any],
        include_func_name: bool,
        extra_key: str,
        key_builder: LockKeyBuilder | None,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
) -> str:
    """Build a stable lock key with optional custom suffixes.

    将锁前缀、函数名、自定义 key 与用户提供的 ``key_builder`` 结果拼接为最终键。
    """

    key_parts: list[str] = [lock_prefix]
    if include_func_name:
        key_parts.append(func.__name__)
    if extra_key:
        key_parts.append(extra_key)
    if key_builder:
        custom = key_builder(func, args, kwargs)
        if custom:
            key_parts.append(custom)
    return ":".join(key_parts)


def cluster_lock(
        lock_prefix: str,
        *,
        timeout_seconds: float = 60.0,
        blocking_timeout_seconds: float | None = None,
        extra_key: str = "",
        include_func_name: bool = True,
        key_builder: LockKeyBuilder | None = None,
        error_message: str | None = None,
        on_fail: OnLockFail | None = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorate a coroutine to enforce Redis distributed locking.

    Args:
        lock_prefix: 锁键前缀 / Prefix for Redis lock key.
        timeout_seconds: 锁自动过期时间 / Lock expiration in seconds.
        blocking_timeout_seconds: 获取锁的最大等待时间 / Max wait when acquiring.
        extra_key: 自定义后缀 / Optional static suffix.
        include_func_name: 是否包含函数名 / Append function name or not.
        key_builder: 用户自定义键构造 / Custom builder for dynamic parts.
        error_message: 获取失败提示 / Optional override error text.
        on_fail: 获取失败回调 / Optional coroutine executed on contention.
    """

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            redis_client = _get_redis_client()
            if redis_client is None:
                logger.warning("Redis pool is not initialized, skip cluster lock for %s", func.__name__)
                return await func(*args, **kwargs)

            lock_key = _compose_lock_key(
                lock_prefix=lock_prefix,
                func=func,
                include_func_name=include_func_name,
                extra_key=extra_key,
                key_builder=key_builder,
                args=args,
                kwargs=kwargs,
            )

            wait_timeout = blocking_timeout_seconds if blocking_timeout_seconds is not None else timeout_seconds
            lock = redis_client.lock(lock_key, timeout=timeout_seconds)

            try:
                acquired = await lock.acquire(blocking=True, blocking_timeout=wait_timeout)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to acquire cluster lock %s: %s", lock_key, exc)
                raise

            if not acquired:
                message = error_message or f"Resource is locked by another worker: {lock_key}"
                if on_fail:
                    return await on_fail(message, func, args, kwargs)
                raise ClusterLockError(message)

            try:
                return await func(*args, **kwargs)
            finally:
                if lock.locked():
                    try:
                        await lock.release()
                    except Exception as exc:  # noqa: BLE001
                        logger.error("Failed to release cluster lock %s: %s", lock_key, exc)

        return wrapper

    return decorator
