"""Authentication helpers shared across Linglong services.

提供 Linglong 服务统一的认证装饰器工具。
"""
from functools import wraps
from typing import (
    Awaitable,
    Callable,
)

from .errors import LoginRequiredError
from .types import P, R
from ..utils.context import get_context_user_id
from ..utils.log import logger


def login_required(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Ensure the current request has a valid login user id.

    确保当前请求已经完成登录校验，如果缺少用户信息则抛出 ``LoginRequiredError``。
    """

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        user_id = get_context_user_id()
        if user_id is not None and isinstance(user_id, int):
            return await func(*args, **kwargs)
        logger.warning("user is not login")
        raise LoginRequiredError()

    return wrapper
