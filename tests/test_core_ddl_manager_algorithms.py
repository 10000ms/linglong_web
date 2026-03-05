"""Tests for linglong_web.core.ddl_manager pure algorithms.

These tests intentionally avoid real database connections.
这些测试刻意避免真实数据库依赖，仅覆盖纯算法逻辑。
"""
from pathlib import Path

import pytest

from linglong_web.core.ddl_manager import (
    AutoDDLManager,
    DDLManagerConfig,
)


def test_config_post_init_normalizes_paths_and_defaults(tmp_path: Path) -> None:
    ddl_dir = tmp_path / "ddl"
    ddl_dir.mkdir()

    config = DDLManagerConfig(
        script_path=ddl_dir,
        trigger_sql_paths=[ddl_dir / "triggers.sql"],
        required_extensions=["  uuid-ossp  ", ""],
    )

    assert isinstance(config.script_path, Path)
    assert config.script_path == ddl_dir.resolve()
    assert tuple(config.trigger_sql_paths or ()) == (ddl_dir / "triggers.sql",)
    assert config.required_extensions == ("uuid-ossp",)
    assert "flag" in config.standard_columns


def test_strip_transaction_wrappers_removes_begin_commit(tmp_path: Path) -> None:
    ddl_dir = tmp_path / "ddl"
    ddl_dir.mkdir()
    manager = AutoDDLManager(DDLManagerConfig(script_path=ddl_dir))

    sql = "BEGIN;\nSELECT 1;\nCOMMIT;\n"
    assert manager._strip_transaction_wrappers(sql).strip() == "SELECT 1;"


def test_split_sql_statements_respects_dollar_quoted_functions(tmp_path: Path) -> None:
    ddl_dir = tmp_path / "ddl"
    ddl_dir.mkdir()
    manager = AutoDDLManager(DDLManagerConfig(script_path=ddl_dir))

    sql = """
    BEGIN;
    CREATE TABLE t1(id INT);
    CREATE FUNCTION f() RETURNS void AS $$
    BEGIN
      PERFORM 1;
    END;
    $$ LANGUAGE plpgsql;
    -- comment line
    CREATE INDEX idx_t1_id ON t1(id);
    COMMIT;
    """.strip()

    statements = manager._split_sql_statements(sql)

    assert any(stmt.lower().startswith("create table") for stmt in statements)
    assert any("create function" in stmt.lower() for stmt in statements)
    assert any(stmt.lower().startswith("create index") for stmt in statements)
    assert all("--" not in stmt for stmt in statements)


def test_extract_table_references_and_toposort(tmp_path: Path) -> None:
    ddl_dir = tmp_path / "ddl"
    ddl_dir.mkdir()

    # a references b, b references c
    (ddl_dir / "a.sql").write_text(
        "CREATE TABLE a(id INT, b_id INT REFERENCES b(id));",
        encoding="utf-8",
    )
    (ddl_dir / "b.sql").write_text(
        "CREATE TABLE b(id INT, c_id INT REFERENCES c(id));",
        encoding="utf-8",
    )
    (ddl_dir / "c.sql").write_text(
        "CREATE TABLE c(id INT);",
        encoding="utf-8",
    )

    manager = AutoDDLManager(DDLManagerConfig(script_path=ddl_dir))
    graph = manager._build_dependency_graph(["a", "b", "c"])

    assert graph["a"] == {"b"}
    assert graph["b"] == {"c"}
    assert graph["c"] == set()

    ordered = manager._topological_sort(graph)
    assert ordered.index("c") < ordered.index("b") < ordered.index("a")


def test_toposort_detects_circular_dependency(tmp_path: Path) -> None:
    ddl_dir = tmp_path / "ddl"
    ddl_dir.mkdir()

    (ddl_dir / "a.sql").write_text(
        "CREATE TABLE a(id INT, b_id INT REFERENCES b(id));",
        encoding="utf-8",
    )
    (ddl_dir / "b.sql").write_text(
        "CREATE TABLE b(id INT, a_id INT REFERENCES a(id));",
        encoding="utf-8",
    )

    manager = AutoDDLManager(DDLManagerConfig(script_path=ddl_dir))
    graph = manager._build_dependency_graph(["a", "b"])

    with pytest.raises(RuntimeError):
        manager._topological_sort(graph)
