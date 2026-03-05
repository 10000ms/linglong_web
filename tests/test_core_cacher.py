import orjson
import pytest

import importlib
from linglong_web.core.cacher import cacher
from linglong_web.core.resource import Rmanager


class _FakeRedis:
    def __init__(self):
        self._get_result = None
        self._get_exc: Exception | None = None
        self.get_keys: list[str] = []
        self.setex_calls: list[tuple[str, int, bytes]] = []

    async def get(self, key: str):
        self.get_keys.append(key)
        if self._get_exc is not None:
            raise self._get_exc
        return self._get_result

    async def setex(self, key: str, ttl: int, value: bytes):
        self.setex_calls.append((key, ttl, value))


@pytest.mark.asyncio
async def test_cacher_cache_hit_skips_func(monkeypatch):
    cacher_mod = importlib.import_module("linglong_web.core.cacher")
    fake_redis = _FakeRedis()
    fake_redis._get_result = orjson.dumps({"ok": True, "from": "cache"})

    monkeypatch.setattr(Rmanager, "RedisPool", object())
    monkeypatch.setattr(cacher_mod.aioredis, "Redis", lambda **_: fake_redis)

    called = {"count": 0}

    async def _func():
        called["count"] += 1
        return {"ok": True, "from": "func"}

    wrapped = cacher(expire_time=10)(_func)
    result = await wrapped()

    assert result == {"ok": True, "from": "cache"}
    assert called["count"] == 0


@pytest.mark.asyncio
async def test_cacher_redis_error_fallback_to_func(monkeypatch):
    cacher_mod = importlib.import_module("linglong_web.core.cacher")
    fake_redis = _FakeRedis()
    fake_redis._get_exc = RuntimeError("boom")

    monkeypatch.setattr(Rmanager, "RedisPool", object())
    monkeypatch.setattr(cacher_mod.aioredis, "Redis", lambda **_: fake_redis)

    called = {"count": 0}

    async def _func():
        called["count"] += 1
        return {"ok": True, "from": "func"}

    wrapped = cacher(expire_time=10)(_func)
    result = await wrapped()

    assert result == {"ok": True, "from": "func"}
    assert called["count"] == 1
