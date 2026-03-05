"""Tests for AutoDDLManager.check_and_init_tables without real DB.

We patch Rmanager.pg_session with an in-memory async session double.
通过替换 Rmanager.pg_session 为内存中的 async session double，避免真实数据库依赖。
"""
from pathlib import Path
from typing import Any

import pytest

from linglong_web.core.ddl_manager import AutoDDLManager, DDLManagerConfig


class _DummyResult:
    def __init__(self, scalar_value: Any = None, rows: list[tuple] | None = None) -> None:
        self._scalar_value = scalar_value
        self._rows = rows or []

    def scalar(self) -> Any:
        return self._scalar_value

    def fetchall(self) -> list[tuple]:
        return list(self._rows)


class _DummyBegin:
    async def __aenter__(self) -> "_DummyBegin":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None


class _DummySession:
    def __init__(self, table_exists: dict[str, bool]) -> None:
        self._table_exists = table_exists
        self.executed: list[tuple[str, Any]] = []

    def begin(self) -> _DummyBegin:
        return _DummyBegin()

    async def execute(self, stmt, params=None):  # noqa: ANN001
        stmt_text = str(stmt)
        self.executed.append((stmt_text, params))

        if params and isinstance(params, dict) and params.get("table_name"):
            table_name = params["table_name"]
            if "information_schema.tables" in stmt_text:
                return _DummyResult(bool(self._table_exists.get(table_name, False)))
            if "information_schema.columns" in stmt_text:
                # pretend table has no columns so standard columns are added
                return _DummyResult(rows=[])

        return _DummyResult(None)


class _DummyPgSessionCM:
    def __init__(self, session: _DummySession) -> None:
        self._session = session

    async def __aenter__(self) -> _DummySession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None


@pytest.mark.asyncio
async def test_check_and_init_tables_disabled_does_not_touch_db(tmp_path: Path) -> None:
    ddl_dir = tmp_path / "ddl"
    ddl_dir.mkdir()

    manager = AutoDDLManager(
        DDLManagerConfig(
            script_path=ddl_dir,
            enable_auto_init=False,
        )
    )

    assert await manager.check_and_init_tables() is True


@pytest.mark.asyncio
async def test_check_and_init_tables_runs_extensions_triggers_and_creates_tables(monkeypatch, tmp_path: Path) -> None:
    ddl_dir = tmp_path / "ddl"
    ddl_dir.mkdir()

    # DDL scripts
    (ddl_dir / "a.sql").write_text("BEGIN;\nCREATE TABLE a(id INT);\nCOMMIT;\n", encoding="utf-8")
    (ddl_dir / "b.sql").write_text("CREATE TABLE b(id INT, a_id INT REFERENCES a(id));", encoding="utf-8")

    trigger_file = tmp_path / "trigger_helpers.sql"
    trigger_file.write_text("CREATE FUNCTION f() RETURNS void AS $$ BEGIN END; $$ LANGUAGE plpgsql;", encoding="utf-8")

    config = DDLManagerConfig(
        script_path=ddl_dir,
        required_extensions=["uuid-ossp"],
        trigger_sql_paths=[trigger_file],
    )
    manager = AutoDDLManager(config)

    dummy_session = _DummySession(table_exists={"a": False, "b": False})

    from linglong_web.core import ddl_manager as ddl_mod

    def _pg_session_factory():
        return _DummyPgSessionCM(dummy_session)

    monkeypatch.setattr(ddl_mod.Rmanager, "pg_session", _pg_session_factory)

    # Avoid testing ALTER column behavior in depth here; just ensure the flow runs.
    async def _noop_columns(_table_name: str) -> None:
        return None

    monkeypatch.setattr(manager, "_ensure_required_columns_exist", _noop_columns)

    ok = await manager.check_and_init_tables()
    assert ok is True

    executed_sql = "\n".join(text for text, _ in dummy_session.executed)

    assert "CREATE EXTENSION IF NOT EXISTS" in executed_sql
    assert "CREATE FUNCTION" in executed_sql
    assert "CREATE TABLE a" in executed_sql
    assert "CREATE TABLE b" in executed_sql
