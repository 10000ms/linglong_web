from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from linglong_web.utils.ddl_manager import (
    _split_sql_statements,
    DDLLoader,
    DDLManager,
    DatabaseConnectionConfig,
    Statement,
    TableDefinition,
    ColumnDefinition,
)

# ---------------------------------------------------------------------------
# Tests for SQL Parsing Logic
# ---------------------------------------------------------------------------

def test_split_sql_statements_basic():
    sql = "CREATE TABLE foo (id int); INSERT INTO foo VALUES (1);"
    statements = _split_sql_statements(sql)
    assert len(statements) == 2
    assert statements[0] == "CREATE TABLE foo (id int)"
    assert statements[1] == "INSERT INTO foo VALUES (1)"

def test_split_sql_statements_whitespace():
    sql = "  SELECT 1 ;   SELECT 2;  "
    statements = _split_sql_statements(sql)
    assert len(statements) == 2
    assert statements[0] == "SELECT 1"
    assert statements[1] == "SELECT 2"

def test_split_sql_statements_comments():
    sql = """
    -- This is a comment
    SELECT 1; -- inline comment
    /* Block 
       Comment */
    SELECT 2;
    """
    statements = _split_sql_statements(sql)
    assert len(statements) == 2
    assert statements[0] == "SELECT 1"
    assert statements[1] == "SELECT 2"

def test_split_sql_statements_quotes():
    sql = "SELECT ';'; SELECT \"a;b\";"
    statements = _split_sql_statements(sql)
    assert len(statements) == 2
    assert statements[0] == "SELECT ';'"
    assert statements[1] == 'SELECT "a;b"'

def test_split_sql_statements_dollar_quotes():
    sql = """
    CREATE FUNCTION foo() RETURNS void AS $$
    BEGIN
        SELECT ';';
    END;
    $$ LANGUAGE plpgsql;
    SELECT 1;
    """
    statements = _split_sql_statements(sql)
    assert len(statements) == 2
    assert statements[0].startswith("CREATE FUNCTION")
    assert statements[1] == "SELECT 1"

def test_split_sql_statements_nested_dollar_quotes():
    # PostgreSQL allows nested dollar quotes with different tags
    sql = """
    DO $outer$
    BEGIN
        PERFORM $inner$ func; $inner$;
    END;
    $outer$;
    """
    statements = _split_sql_statements(sql)
    assert len(statements) == 1
    assert statements[0].startswith("DO $outer$")

# ---------------------------------------------------------------------------
# Tests for DDLLoader
# ---------------------------------------------------------------------------

@pytest.fixture
def ddl_root(tmp_path):
    # Setup a dummy DDL directory structure
    root = tmp_path / "ddl"
    root.mkdir()
    
    # Common file
    (root / "common.sql").write_text("CREATE EXTENSION IF NOT EXISTS uuid-ossp;")
    (root / "create_db.sql").write_text("ignored content") # Should be ignored
    
    # Database dir
    db_dir = root / "test_db"
    db_dir.mkdir()
    
    # Table file
    table_sql = """
    CREATE TABLE users (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX idx_users_name ON users(name);
    """
    (db_dir / "users.sql").write_text(table_sql)
    
    return root

def test_ddl_loader_discovery(ddl_root):
    loader = DDLLoader(ddl_root)
    
    # Check common files
    assert len(loader.common_files) == 1
    assert loader.common_files[0].raw == "CREATE EXTENSION IF NOT EXISTS uuid-ossp"
    
    # Check databases
    assert "test_db" in loader.databases
    tables = loader.databases["test_db"]
    assert len(tables) == 1
    
    table_def = tables[0]
    assert table_def.table_name == "users"
    assert table_def.database == "test_db"
    assert len(table_def.statements) == 2
    assert table_def.statements[0].kind == "create_table"
    assert table_def.statements[1].kind == "create_index"
    
    # Check column extraction
    cols = table_def.columns
    assert "id" in cols
    assert "name" in cols
    assert "created_at" in cols
    
    assert cols["name"].data_type == "VARCHAR(100)"
    assert cols["name"].not_null is True
    assert cols["created_at"].default == "NOW()"

def test_ddl_loader_missing_dir():
    with pytest.raises(FileNotFoundError):
        DDLLoader(Path("/non/existent/path"))

# ---------------------------------------------------------------------------
# Tests for DDLManager
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_loader():
    loader = MagicMock(spec=DDLLoader)
    loader.common_files = []
    loader.databases = {}
    return loader

@pytest.fixture
def mock_connection():
    conn = AsyncMock()
    # Mock transaction/connection context behavior if needed, 
    # but DDLManager uses connection objects directly mostly.
    return conn

@pytest.fixture
def ddl_manager(mock_loader):
    config = DatabaseConnectionConfig(
        host="localhost", port=5432, user="user", password="pwd"
    )
    return DDLManager(mock_loader, config)

@pytest.mark.asyncio
async def test_ensure_schema_creates_db(ddl_manager, mock_connection):
    # Mock admin connection
    mock_connection.execute.return_value = "OK"
    with patch("asyncpg.connect", new=AsyncMock(return_value=mock_connection)) as mock_connect:
        # Mock DB existence check (returns False -> create)
        mock_connection.fetchval.side_effect = [False] 
        
        ddl_manager.loader.databases = {"new_db": []}
        
        await ddl_manager.ensure_schema()
        
        # Verify CREATE DATABASE called on admin conn
        # First connect is admin, second is to the new db
        assert mock_connect.call_count >= 1
        
        # Check execution on admin conn
        mock_connection.execute.assert_any_call('CREATE DATABASE "new_db"')

@pytest.mark.asyncio
async def test_ensure_schema_applies_table(ddl_manager, mock_connection):
    # Setup table definition
    statement = Statement(raw="CREATE TABLE t (id int)", kind="create_table", name="t")
    table_def = TableDefinition(
        table_name="t",
        file_path=Path("t.sql"),
        statements=[statement],
        file_hash="abc",
        columns={"id": ColumnDefinition(name="id", data_type="INT", not_null=False, default=None)},
        database="test_db"
    )
    ddl_manager.loader.databases = {"test_db": [table_def]}

    mock_connection.execute.return_value = "OK"

    # DDLManager wraps asyncpg.connect in an internal async context that awaits the connect coroutine.
    # Therefore, patching asyncpg.connect to return the connection object is sufficient.
    # DDLManager 内部会 await asyncpg.connect(...)，因此这里直接让 connect 返回 connection 即可。
    with patch("asyncpg.connect", new=AsyncMock(return_value=mock_connection)):
        table_exists_calls = 0

        async def _fetchval(query: str, *args):
            nonlocal table_exists_calls
            if query.startswith("SELECT 1 FROM pg_database"):
                return 1
            if "information_schema.tables" in query:
                return True
            if query.startswith("SELECT to_regclass"):
                # First existence check: table does not exist; after CREATE TABLE, it exists.
                # 第一次检查：表不存在；CREATE TABLE 后，表存在。
                if args and args[0] == "t":
                    table_exists_calls += 1
                    return None if table_exists_calls == 1 else "t"
                return None
            if query.startswith("SELECT obj_description"):
                return None
            return None

        async def _fetch(query: str, *args):
            if "pg_catalog.format_type" in query:
                return [
                    {"column_name": "id", "data_type": "INT", "not_null": False, "default": None},
                ]
            return []

        mock_connection.fetchval.side_effect = _fetchval
        mock_connection.fetch.side_effect = _fetch

        summary = await ddl_manager.ensure_schema()
        
        assert len(summary.databases) == 1
        db_res = summary.databases[0]
        assert db_res.database == "test_db"
        assert len(db_res.table_results) == 1
        tbl_res = db_res.table_results[0]
        
        assert tbl_res.status == "created"
        mock_connection.execute.assert_any_call(statement.raw)
        # Verify metadata update
        assert any("COMMENT ON TABLE" in str(c) for c in mock_connection.execute.call_args_list)
        assert any("INSERT INTO ddl_registry" in str(c) for c in mock_connection.execute.call_args_list)

@pytest.mark.asyncio
async def test_diff_schema_detects_drift(ddl_manager, mock_connection):
    # Setup table definition with one column 'id'
    table_def = TableDefinition(
        table_name="t",
        file_path=Path("t.sql"),
        statements=[],
        file_hash="hash_123",
        columns={"id": ColumnDefinition(name="id", data_type="INT", not_null=False, default=None)},
        database="test_db"
    )
    ddl_manager.loader.databases = {"test_db": [table_def]}
    
    mock_connection.execute.return_value = "OK"
    with patch("asyncpg.connect", new=AsyncMock(return_value=mock_connection)):
        # Admin: DB exists -> True
        # DB: Registry exists -> True (skipped in diff_schema actually? No, ensure_schema dry_run=True still calls select_databases)
        # Actually ensure_schema with dry_run=True DOES NOT call ensure_registry_table
        
        # DB: Table exists -> True
        # DB: Comment hash matches? -> False (simulate drift)
        mock_connection.fetchval.side_effect = [
            True,  # admin: database exists
            True,  # db: registry exists
            True,  # table exists
            'DDL::{"hash":"old_hash"}',  # table comment hash differs
        ]
        
        # DB: Fetch columns -> returns different type for 'id' to simulate mismatch
        mock_connection.fetch.return_value = [
            {"column_name": "id", "data_type": "TEXT", "not_null": False, "default": None}
        ]
        
        summary = await ddl_manager.diff_schema()
        
        tbl_res = summary.databases[0].table_results[0]
        assert tbl_res.status == "dry-run"
        assert tbl_res.diff.exists is True
        assert tbl_res.diff.comment_hash_matches is False
        
        # Check column diff
        mismatches = tbl_res.diff.column_diff.mismatched
        assert len(mismatches) == 1
        assert mismatches[0]['column'] == "id"
        assert mismatches[0]['expected_type'] == "INT"
        assert mismatches[0]['actual_type'] == "TEXT"

@pytest.mark.asyncio
async def test_rebuild_tables(ddl_manager, mock_connection):
    table_def = TableDefinition(
        table_name="t",
        file_path=Path("t.sql"),
        statements=[Statement(raw="CREATE TABLE t...", kind="create_table", name="t")],
        file_hash="abc",
        columns={}, 
        database="test_db"
    )
    ddl_manager.loader.databases = {"test_db": [table_def]}
    
    mock_connection.execute.return_value = "OK"
    with patch("asyncpg.connect", new=AsyncMock(return_value=mock_connection)):
        # Table exists -> True, registry exists -> True, comment hash check -> absent
        mock_connection.fetchval.side_effect = [
            True,  # to_regclass(table)
            True,  # to_regclass(ddl_registry)
            None,  # obj_description
        ]
        mock_connection.fetch.return_value = []
        
        await ddl_manager.rebuild_tables("test_db", ["t"])
        
        # Verify Drop
        assert any("DROP TABLE IF EXISTS" in str(c) for c in mock_connection.execute.call_args_list)
        # Verify Create
        assert any("CREATE TABLE t" in str(c) for c in mock_connection.execute.call_args_list)

@pytest.mark.asyncio
async def test_rebuild_database(ddl_manager, mock_connection):
    ddl_manager.loader.databases = {"test_db": []}
    
    mock_connection.execute.return_value = "OK"
    with patch("asyncpg.connect", new=AsyncMock(return_value=mock_connection)):
        mock_connection.fetchval.return_value = True  # DB exists initially
        
        await ddl_manager.rebuild_database("test_db")
        
        # Verify Drop Database
        assert any("DROP DATABASE IF EXISTS" in str(c) for c in mock_connection.execute.call_args_list)
        # Verify Create Database
        assert any("CREATE DATABASE" in str(c) for c in mock_connection.execute.call_args_list)
