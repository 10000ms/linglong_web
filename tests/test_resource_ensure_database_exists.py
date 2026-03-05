import asyncpg
import pytest

from linglong_web.core.resource import _ensure_database_exists
from linglong_web.core.schemas import PgsqlConfig


class _DummyConn:
    def __init__(self, *, exists: bool, duplicate: bool = False) -> None:
        self._exists = exists
        self._duplicate = duplicate
        self.closed = False
        self.executed_sql: list[str] = []

    async def fetchval(self, _sql: str, _db_name: str):  # noqa: ANN001
        return 1 if self._exists else None

    async def execute(self, sql: str) -> None:
        self.executed_sql.append(sql)
        if self._duplicate:
            raise asyncpg.DuplicateDatabaseError("duplicate")

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_ensure_database_exists_returns_when_already_exists(monkeypatch) -> None:
    conn = _DummyConn(exists=True)

    async def _connect(**kwargs):  # noqa: ANN001
        return conn

    monkeypatch.setattr("linglong_web.core.resource.asyncpg.connect", _connect)

    config = PgsqlConfig(
        alias="a",
        host="h",
        port=5432,
        user="u",
        password="p",
        database="db",
        ensure_database=True,
        bootstrap_database="postgres",
    )

    await _ensure_database_exists(config)

    assert conn.closed is True
    assert conn.executed_sql == []


@pytest.mark.asyncio
async def test_ensure_database_exists_creates_database(monkeypatch) -> None:
    conn = _DummyConn(exists=False)

    async def _connect(**kwargs):  # noqa: ANN001
        return conn

    monkeypatch.setattr("linglong_web.core.resource.asyncpg.connect", _connect)

    config = PgsqlConfig(
        alias="a",
        host="h",
        port=5432,
        user="u",
        password="p",
        database="db",
        ensure_database=True,
        bootstrap_database="postgres",
        create_db_owner="owner",
    )

    await _ensure_database_exists(config)

    assert conn.closed is True
    assert len(conn.executed_sql) == 1
    assert "CREATE DATABASE" in conn.executed_sql[0]
    assert "OWNER" in conn.executed_sql[0]


@pytest.mark.asyncio
async def test_ensure_database_exists_handles_duplicate_database(monkeypatch) -> None:
    conn = _DummyConn(exists=False, duplicate=True)

    async def _connect(**kwargs):  # noqa: ANN001
        return conn

    monkeypatch.setattr("linglong_web.core.resource.asyncpg.connect", _connect)

    config = PgsqlConfig(
        alias="a",
        host="h",
        port=5432,
        user="u",
        password="p",
        database="db",
        ensure_database=True,
        bootstrap_database="postgres",
    )

    await _ensure_database_exists(config)

    assert conn.closed is True
    assert len(conn.executed_sql) == 1
