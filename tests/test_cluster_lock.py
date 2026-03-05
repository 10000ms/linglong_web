import asyncio
import importlib

import pytest

cluster_lock_module = importlib.import_module("linglong_web.core.cluster_lock")
from linglong_web import cluster_lock
from linglong_web import ResourceManager


class _FakeRedisLock:
    def __init__(self, should_acquire: bool = True):
        self.should_acquire = should_acquire
        self.released = False

    async def acquire(self, blocking=True, blocking_timeout=None):  # noqa: FBT001, FBT002
        await asyncio.sleep(0)
        return self.should_acquire

    async def release(self):
        self.released = True

    def locked(self):
        return not self.released


class _FakeRedisClient:
    def __init__(self, lock: _FakeRedisLock):
        self._lock = lock

    def lock(self, *_, **__):
        return self._lock


@pytest.mark.asyncio
async def test_cluster_lock_skips_when_no_pool():
    resource = ResourceManager()
    resource.RedisPool = None

    @cluster_lock("test-lock")
    async def handler():
        return "ok"

    assert await handler() == "ok"


@pytest.mark.asyncio
async def test_cluster_lock_acquires_and_releases(monkeypatch):
    lock = _FakeRedisLock(should_acquire=True)
    client = _FakeRedisClient(lock)

    resource = ResourceManager()
    resource.RedisPool = object()
    monkeypatch.setattr(cluster_lock_module.redis, "Redis", lambda **_: client)

    @cluster_lock("test-lock", timeout_seconds=1)
    async def handler():
        return "run"

    assert await handler() == "run"
    assert lock.released is True
