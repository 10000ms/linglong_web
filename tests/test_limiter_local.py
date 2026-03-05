"""Tests for linglong_web.core.limiter_local.

该模块应可在无外部依赖的情况下稳定测试。
This module should be testable without external services.
"""
import pytest

from linglong_web.core.errors import LimiterError
from linglong_web.core.limiter_local import (
    get_limiter_stats,
    limiter_local,
    reset_limiter,
)


@pytest.mark.asyncio
async def test_limiter_local_allows_within_limit_and_blocks_when_exceeded() -> None:
    reset_limiter()

    calls = {"count": 0}

    @limiter_local("1/minute")
    async def f():
        calls["count"] += 1
        return "ok"

    assert await f() == "ok"
    with pytest.raises(LimiterError):
        await f()


@pytest.mark.asyncio
async def test_limiter_local_invalid_rate_limit_falls_back_to_function() -> None:
    reset_limiter()

    @limiter_local("not-a-rate")
    async def f():
        return "ok"

    assert await f() == "ok"


@pytest.mark.asyncio
async def test_limiter_local_add_str_is_part_of_key() -> None:
    reset_limiter()

    @limiter_local("1/minute", add_str="user:42")
    async def f():
        return "ok"

    assert await f() == "ok"
    with pytest.raises(LimiterError) as exc_info:
        await f()

    assert "key=f:user:42" in str(exc_info.value)


def test_get_limiter_stats_returns_basic_info() -> None:
    stats = get_limiter_stats("key")
    assert stats["key"] == "key"
    assert stats["storage_type"] == "memory"
