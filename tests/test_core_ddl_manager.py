from pathlib import Path

import pytest


def _make_manager(tmp_path: Path):
    from linglong_web.core.ddl_manager import (
        AutoDDLManager,
        DDLManagerConfig,
    )

    config = DDLManagerConfig(
        script_path=tmp_path,
        enable_auto_init=True,
        trigger_sql_paths=(),
        required_extensions=(),
    )
    return AutoDDLManager(config)


def test_ddl_manager_config_normalizes_paths(tmp_path: Path):
    from linglong_web.core.ddl_manager import DDLManagerConfig

    ddl_dir = tmp_path / "ddl"
    ddl_dir.mkdir()
    trigger_dir = tmp_path / "triggers"
    trigger_dir.mkdir()
    trigger_file = trigger_dir / "trigger.sql"
    trigger_file.write_text("-- noop\n", encoding="utf-8")

    config = DDLManagerConfig(
        script_path=ddl_dir,
        trigger_sql_paths=[trigger_file],
        required_extensions=[" uuid-ossp ", ""],
    )

    assert isinstance(config.script_path, Path)
    assert config.script_path.is_absolute()
    assert all(isinstance(p, Path) and p.is_absolute() for p in (config.trigger_sql_paths or ()))
    assert config.required_extensions == ("uuid-ossp",)
    assert isinstance(config.standard_columns, dict)
    assert "flag" in config.standard_columns


def test_extract_table_references_ignores_public(tmp_path: Path):
    manager = _make_manager(tmp_path)
    refs = manager._extract_table_references(
        'CREATE TABLE a_tbl(id BIGINT);\n'
        'ALTER TABLE b_tbl ADD CONSTRAINT fk_a FOREIGN KEY (a_id) REFERENCES "a_tbl"(id);\n'
        'ALTER TABLE x_tbl ADD CONSTRAINT fk_p FOREIGN KEY (p_id) REFERENCES public(id);\n'
    )
    assert "a_tbl" in refs
    assert "public" not in refs


def test_topological_sort_orders_dependencies(tmp_path: Path):
    manager = _make_manager(tmp_path)
    ordered = manager._topological_sort(
        {
            "a_tbl": {"b_tbl"},
            "b_tbl": set(),
        }
    )
    assert ordered == ["b_tbl", "a_tbl"]


def test_topological_sort_detects_cycle(tmp_path: Path):
    manager = _make_manager(tmp_path)
    with pytest.raises(RuntimeError, match="Circular dependency detected"):
        manager._topological_sort(
            {
                "a_tbl": {"b_tbl"},
                "b_tbl": {"a_tbl"},
            }
        )


def test_build_dependency_graph_from_files(tmp_path: Path):
    ddl_dir = tmp_path / "ddl"
    ddl_dir.mkdir()

    (ddl_dir / "a_tbl.sql").write_text(
        """
        BEGIN;
        CREATE TABLE a_tbl(id BIGINT);
        ALTER TABLE a_tbl ADD CONSTRAINT fk_b FOREIGN KEY (b_id) REFERENCES b_tbl(id);
        COMMIT;
        """.strip(),
        encoding="utf-8",
    )
    (ddl_dir / "b_tbl.sql").write_text(
        """
        CREATE TABLE b_tbl(id BIGINT);
        """.strip(),
        encoding="utf-8",
    )

    manager = _make_manager(ddl_dir)
    graph = manager._build_dependency_graph(["a_tbl", "b_tbl"])

    assert graph["a_tbl"] == {"b_tbl"}
    assert graph["b_tbl"] == set()
    assert manager._topological_sort(graph) == ["b_tbl", "a_tbl"]


def test_strip_transaction_wrappers(tmp_path: Path):
    manager = _make_manager(tmp_path)
    stripped = manager._strip_transaction_wrappers("BEGIN;\nSELECT 1;\nCOMMIT;\n")
    assert "BEGIN" not in stripped.upper()
    assert "COMMIT" not in stripped.upper()
    assert "SELECT 1" in stripped


def test_split_sql_statements_respects_dollar_quotes(tmp_path: Path):
    manager = _make_manager(tmp_path)

    sql = """
    BEGIN;
    CREATE FUNCTION f_test() RETURNS void AS $$
    BEGIN
        PERFORM 1;
    END;
    $$ LANGUAGE plpgsql;

    -- comment line
    CREATE TABLE t_test(id BIGINT);
    COMMIT;
    """.strip()

    statements = manager._split_sql_statements(sql)

    assert len(statements) == 2
    assert statements[0].lower().startswith("create function")
    assert "perform 1;" in statements[0].lower()
    assert statements[1].lower().startswith("create table")


def test_remove_comments_drops_line_comments(tmp_path: Path):
    manager = _make_manager(tmp_path)
    cleaned = manager._remove_comments("-- a\nSELECT 1;\n-- b\n")
    assert cleaned == "SELECT 1;"


def test_parse_required_columns_from_sql_detects_standard_columns(tmp_path: Path):
    manager = _make_manager(tmp_path)
    sql = """
    CREATE TABLE x_tbl(
        id BIGSERIAL PRIMARY KEY,
        flag SMALLINT DEFAULT 0,
        created_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        update_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    """.strip()
    detected = manager._parse_required_columns_from_sql(sql)
    assert set(detected.keys()) == {"flag", "created_time", "update_time"}
