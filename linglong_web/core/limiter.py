"""Linglong Web 限流器 / Limiter utilities."""
from functools import wraps
from typing import (
    Awaitable,
    Callable,
)

from limits import parse

from .errors import LimiterError
from .resource import ResourceManager
from .types import P, R
from ..utils.context import get_context_user_id
from ..utils.log import logger


class LimiterGuard:
    """限流装饰器 / Rate limit decorator."""

    def __init__(self, resource_manager: ResourceManager | None = None) -> None:
        self._resource_manager = resource_manager or ResourceManager()

    def __call__(
            self,
            rate_limit: str,
            add_str: str = "",
            limit_by_user: bool = False,
    ) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
        def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
            @wraps(func)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                limiter = self._resource_manager.limiter
                if limiter is None:
                    logger.warning("Limiter is not initialized in ResourceManager")
                    return await func(*args, **kwargs)

                key_list = [func.__name__]
                if add_str:
                    key_list.append(add_str)
                if limit_by_user:
                    user_id = get_context_user_id()
                    if user_id is not None:
                        key_list.append(str(user_id))

                limit_rate = parse(rate_limit)
                if not await limiter.hit(limit_rate, *key_list):
                    raise LimiterError()
                return await func(*args, **kwargs)

            return wrapper

        return decorator


limiter = LimiterGuard()
