"""Linglong Web 通用类型定义 / Common type definitions for Linglong Web core components."""
from typing import (
    Any,
    Callable,
    Coroutine,
    ParamSpec,
    TypeVar,
)

# 装饰器通用类型变量 / Generic type variables for decorators
P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")

# 分布式锁特定类型 / Cluster lock specific types
LockKeyBuilder = Callable[[Callable[..., Any], tuple[Any, ...], dict[str, Any]], str | None]
OnLockFail = Callable[[str, Callable[..., Any], tuple[Any, ...], dict[str, Any]], Coroutine[Any, Any, R]]
