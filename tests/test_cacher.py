import asyncio
import importlib

import pytest
from linglong_web import cacher
from linglong_web import ResourceManager


cacher_module = importlib.import_module("linglong_web.core.cacher")


@pytest.mark.asyncio
async def test_cacher_hits_memory_when_redis_absent(monkeypatch):
    resource = ResourceManager()
    resource.RedisPool = None

    call_counter = {"count": 0}

    @cacher(expire_time=60)
    async def expensive_call(value: int) -> int:
        call_counter["count"] += 1
        await asyncio.sleep(0)
        return value * 2

    assert await expensive_call(2) == 4
    assert await expensive_call(2) == 4
    assert call_counter["count"] == 2  # 没有连接池直接执行函数


@pytest.mark.asyncio
async def test_cacher_uses_redis_pool(monkeypatch):
    class _FakeRedis:
        def __init__(self):
            self.store = {}

        async def get(self, key):
            return self.store.get(key)

        async def setex(self, key, expire_time, value):
            self.store[key] = value

    fake_pool = object()

    class _FakeRedisFactory:
        def __init__(self):
            self.client = _FakeRedis()

        def __call__(self, connection_pool):
            assert connection_pool is fake_pool
            return self.client

    factory = _FakeRedisFactory()
    resource = ResourceManager()
    resource.RedisPool = fake_pool
    monkeypatch.setattr(cacher_module.aioredis, "Redis", factory)

    call_counter = {"count": 0}

    @cacher(expire_time=60)
    async def expensive_call(value: int) -> int:
        call_counter["count"] += 1
        await asyncio.sleep(0)
        return value * 2

    assert await expensive_call(5) == 10
    assert await expensive_call(5) == 10
    assert call_counter["count"] == 1
