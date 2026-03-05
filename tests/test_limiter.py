import pytest

from linglong_web import LimiterError
from linglong_web import LimiterGuard
from linglong_web.utils import set_context_user_id


class _DummyLimiter:
    def __init__(self):
        self.invocations = []
        self.fail_after = 1

    async def hit(self, limit, *keys):
        self.invocations.append((str(limit), keys))
        return len(self.invocations) <= self.fail_after


class _DummyResourceManager:
    def __init__(self):
        self.limiter = _DummyLimiter()


class _NoLimiterResourceManager:
    def __init__(self):
        self.limiter = None


@pytest.mark.asyncio
async def test_limiter_guard_enforces_limits():
    resource = _DummyResourceManager()
    guard = LimiterGuard(resource_manager=resource)

    set_context_user_id(7)

    @guard("1/second", add_str="demo", limit_by_user=True)
    async def _handler(value):
        return value

    assert await _handler("ok") == "ok"

    with pytest.raises(LimiterError):
        await _handler("should-fail")

    recorded_limit, keys = resource.limiter.invocations[0]
    assert recorded_limit == "1 per 1 second"
    assert "demo" in keys
    assert "7" in keys


@pytest.mark.asyncio
async def test_limiter_guard_falls_back_when_limiter_not_initialized():
    """当 limiter 未初始化时，装饰器应降级放行而不是抛错。
    When limiter is missing, guard should gracefully pass through.
    """

    guard = LimiterGuard(resource_manager=_NoLimiterResourceManager())
    calls = []

    @guard("1/second", add_str="demo", limit_by_user=True)
    async def _handler(value):
        calls.append(value)
        return value

    result = await _handler("ok-no-limiter")
    assert result == "ok-no-limiter"
    assert calls == ["ok-no-limiter"]


@pytest.mark.asyncio
async def test_limiter_guard_without_user_context_does_not_append_user_key():
    """limit_by_user=True 且无用户上下文时，不应附加空用户维度。
    With no user context, limiter key should not include a user fragment.
    """

    resource = _DummyResourceManager()
    guard = LimiterGuard(resource_manager=resource)
    set_context_user_id(None)

    @guard("2/second", add_str="api", limit_by_user=True)
    async def _handler():
        return "ok"

    assert await _handler() == "ok"
    recorded_limit, keys = resource.limiter.invocations[0]
    assert recorded_limit == "2 per 1 second"
    assert keys == ("_handler", "api")
