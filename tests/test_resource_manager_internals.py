"""Focused unit tests for ResourceManager internals.

这些测试覆盖纯逻辑分支：
- URL 构造 / identifier quoting
- PGSQL engine per-event-loop 缓存/清理

All tests avoid real network connections.
"""
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock

from linglong_web.core import resource as resource_mod
from linglong_web.core.resource import ResourceManager
from linglong_web.core.schemas import PgsqlConfig


def test_build_amqp_url_normalizes_vhost() -> None:
    url1 = resource_mod._build_amqp_url("u", "p", "h", 5672, "v")
    assert url1.endswith("/v")

    url2 = resource_mod._build_amqp_url("u", "p", "h", 5672, "/v")
    assert url2.endswith("/v")

    url3 = resource_mod._build_amqp_url("u", "p", "h", 5672, "")
    assert url3.endswith("/")


def test_build_redis_url_password_optional() -> None:
    assert resource_mod._build_redis_url("h", 6379, None, 0) == "redis://h:6379/0"
    assert resource_mod._build_redis_url("h", 6379, "pw", 2) == "redis://:pw@h:6379/2"


def test_quote_ident_escapes_double_quotes() -> None:
    assert resource_mod._quote_ident('a"b') == '"a""b"'


@pytest.mark.asyncio
async def test_get_pgsql_engine_recreates_engine_from_cached_params(monkeypatch):
    rm = resource_mod.ResourceManager()

    # snapshot & restore singleton state
    old_engines = rm._pgsql_engines
    old_loops = rm._pgsql_engine_loops
    old_params = rm._pgsql_engine_params

    rm._pgsql_engines = {}
    rm._pgsql_engine_loops = {}
    rm._pgsql_engine_params = {"main": {"url": "postgresql+asyncpg://x"}}

    try:
        monkeypatch.setattr(rm, "_current_loop_id", lambda: 123)

        created = object()

        def _fake_create_async_engine(**kwargs):  # noqa: ANN001
            assert kwargs["url"] == "postgresql+asyncpg://x"
            return created

        monkeypatch.setattr(resource_mod, "create_async_engine", _fake_create_async_engine)

        engine = rm.get_pgsql_engine("main")
        assert engine is created
        assert rm._pgsql_engines["main"][123] is created
    finally:
        rm._pgsql_engines = old_engines
        rm._pgsql_engine_loops = old_loops
        rm._pgsql_engine_params = old_params


@pytest.mark.asyncio
async def test_get_pgsql_engine_detaches_stale_loop_and_schedules_dispose(monkeypatch):
    rm = resource_mod.ResourceManager()

    old_engines = rm._pgsql_engines
    old_loops = rm._pgsql_engine_loops
    old_params = rm._pgsql_engine_params

    rm._pgsql_engines = {"main": {111: object()}}
    fake_loop = SimpleNamespace(is_closed=lambda: False, is_running=lambda: True, call_soon_threadsafe=lambda cb: cb())
    rm._pgsql_engine_loops = {"main": {111: fake_loop}}
    rm._pgsql_engine_params = {"main": {"url": "postgresql+asyncpg://x"}}

    scheduled = {"called": 0}

    def _fake_schedule(loop, engine, *, alias, loop_id):  # noqa: ANN001
        scheduled["called"] += 1
        assert alias == "main"
        assert loop_id == 111

    try:
        monkeypatch.setattr(rm, "_current_loop_id", lambda: 222)
        monkeypatch.setattr(rm, "_schedule_engine_dispose", _fake_schedule)

        created = object()

        monkeypatch.setattr(resource_mod, "create_async_engine", lambda **kw: created)

        engine = rm.get_pgsql_engine("main")
        assert engine is created
        assert scheduled["called"] == 1
        assert 111 not in rm._pgsql_engines["main"]
        assert 222 in rm._pgsql_engines["main"]
    finally:
        rm._pgsql_engines = old_engines
        rm._pgsql_engine_loops = old_loops
        rm._pgsql_engine_params = old_params


@pytest.mark.asyncio
async def test_close_pgsql_engines_disposes_current_loop_and_schedules_others(monkeypatch):
    rm = resource_mod.ResourceManager()

    old_engines = rm._pgsql_engines
    old_loops = rm._pgsql_engine_loops

    engine_current = MagicMock()
    engine_current.dispose = AsyncMock()
    engine_other = MagicMock()
    engine_other.dispose = AsyncMock()

    current_loop = SimpleNamespace()
    current_loop_id = id(current_loop)
    other_loop_id = current_loop_id + 1

    other_loop = SimpleNamespace(is_closed=lambda: False, is_running=lambda: True, call_soon_threadsafe=lambda cb: cb())

    rm._pgsql_engines = {"main": {current_loop_id: engine_current, other_loop_id: engine_other}}
    rm._pgsql_engine_loops = {"main": {other_loop_id: other_loop}}

    scheduled = {"called": 0}

    def _fake_schedule(loop, engine, *, alias, loop_id):  # noqa: ANN001
        scheduled["called"] += 1
        assert alias == "main"
        assert loop_id == other_loop_id

    monkeypatch.setattr(resource_mod.asyncio, "get_running_loop", lambda: current_loop)
    monkeypatch.setattr(rm, "_schedule_engine_dispose", _fake_schedule)

    try:
        await rm.close_pgsql_engines()

        engine_current.dispose.assert_awaited()
        assert scheduled["called"] == 1
        assert rm._pgsql_engines == {}
    finally:
        rm._pgsql_engines = old_engines
        rm._pgsql_engine_loops = old_loops


def test_schedule_engine_dispose_skips_when_loop_not_running():
    rm = resource_mod.ResourceManager()

    loop = SimpleNamespace(is_closed=lambda: False, is_running=lambda: False)
    engine = MagicMock()
    # should not raise
    rm._schedule_engine_dispose(loop, engine, alias="main", loop_id=1)


@pytest.mark.asyncio
async def test_ensure_database_exists_skips_when_disabled(monkeypatch):
    # If ensure_database is False, asyncpg.connect must not be invoked.
    monkeypatch.setattr(resource_mod.asyncpg, "connect", AsyncMock(side_effect=AssertionError("connect should not be called")))

    config = PgsqlConfig(
        alias="main",
        host="pg.internal",
        port=5432,
        user="user",
        password="pass",
        database="db",
        ensure_database=False,
    )

    await resource_mod._ensure_database_exists(config)


def test_quote_ident_handles_empty_string():
    assert resource_mod._quote_ident("") == '""'


def test_quote_ident_handles_normal_string():
    assert resource_mod._quote_ident("table_name") == '"table_name"'


def test_quote_ident_handles_special_chars():
    assert resource_mod._quote_ident('table"name') == '"table""name"'


@pytest.mark.asyncio
async def test_resource_manager_get_pgsql_engine_returns_none_when_not_initialized():
    resource = ResourceManager()
    resource._pgsql_engines = {}
    resource._pgsql_engine_params = {}
    resource._current_loop_id = lambda: None

    engine = resource.get_pgsql_engine("nonexistent")
    assert engine is None
