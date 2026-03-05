"""In-memory rate limiter for single-node services.

提供基于内存的限流器装饰器，适用于 controllersrv 等单机服务。
"""
from functools import wraps
from typing import (
    Awaitable,
    Callable,
)

from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

from .errors import LimiterError
from .types import (
    P,
    R,
)
from linglong_web.utils import logger

_memory_storage = MemoryStorage()
_rate_limiter = MovingWindowRateLimiter(_memory_storage)


def limiter_local(
        rate_limit: str,
        add_str: str = "",
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Rate limit a coroutine using in-process memory storage.

    Args:
        rate_limit: 限流速率描述，例如 ``"10/minute"``。
        add_str: 附加的键后缀，用于区分不同的限流维度。
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            key_parts = [func.__name__]
            if add_str:
                key_parts.append(add_str)
            key = ":".join(key_parts)

            try:
                limit_rate = parse(rate_limit)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to parse rate limit '%s': %s", rate_limit, exc)
                return await func(*args, **kwargs)

            if not _rate_limiter.hit(limit_rate, key):
                logger.warning("Rate limit exceeded for %s: %s", key, rate_limit)
                raise LimiterError(f"Rate limit exceeded: {rate_limit} (key={key})")

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def reset_limiter() -> None:
    """Reset limiter state, mainly for tests.

    重置限流器内部存储，便于测试场景重新计数。
    """

    global _memory_storage, _rate_limiter  # noqa: PLW0603 - module level cache reset
    _memory_storage = MemoryStorage()
    _rate_limiter = MovingWindowRateLimiter(_memory_storage)
    logger.info("Local rate limiter reset")


def get_limiter_stats(key: str) -> dict[str, str]:
    """Return basic info about a limiter entry for diagnostics.

    由于 ``limits`` 的内存存储不提供详细指标，此处仅返回基础信息。
    """

    return {
        "key": key,
        "storage_type": "memory",
        "note": "Memory storage does not persist stats",
    }
