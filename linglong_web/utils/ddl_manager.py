"""Utilities for managing PostgreSQL schema from canonical DDL files.
用于根据规范 DDL 文件管理 PostgreSQL 模式的实用工具。

This module scans the ``ddl`` directory, groups statements by database, and
provides helpers to ensure databases and tables exist, rebuild selected
artifacts, and report schema drift against the canonical SQL definitions.
本模块扫描 ``ddl`` 目录，按数据库对语句进行分组，并提供帮助程序以确保数据库和表存在、
重建选定的工件，并报告针对规范 SQL 定义的模式漂移。

The entrypoint for external callers is :class:`DDLManager` which exposes the
following high-level methods:
外部调用者的入口点是 :class:`DDLManager`，它暴露了以下高级方法：

* :meth:`DDLManager.ensure_schema` – create missing databases/tables and
  execute ancillary statements such as indexes and triggers in an idempotent
  fashion.
  创建缺失的数据库/表，并以幂等方式执行辅助语句（如索引和触发器）。
* :meth:`DDLManager.rebuild_database` – drop and recreate a whole database
  using the canonical DDL files.
  使用规范 DDL 文件删除并重建整个数据库。
* :meth:`DDLManager.rebuild_tables` – drop and recreate selected tables.
  删除并重建选定的表。
* :meth:`DDLManager.diff_schema` – compute schema drift (columns, defaults,
  comments) without making changes.
  计算模式漂移（列、默认值、注释）而不进行更改。

The design keeps the DDL files as the single source of truth while storing the
canonical hash of each definition in a dedicated ``ddl_registry`` table and, if
possible, in the table comment.  The hash comparison allows the caller to
understand whether a deployed table still matches its canonical definition.
该设计将 DDL 文件作为唯一的真实来源，同时将每个定义的规范哈希存储在专用的 ``ddl_registry`` 表中，
如果是表，尽可能存储在表注释中。哈希比较允许调用者了解已部署的表是否仍与其规范定义匹配。
"""
import hashlib
import json
import re
from pydantic import (
    BaseModel,
    Field,
)
from dataclasses import dataclass
from datetime import (
    datetime,
    timezone,
)
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Coroutine,
)

import asyncpg
from asyncpg import Connection
from asyncpg.exceptions import (
    DuplicateObjectError,
    DuplicateTableError,
    UniqueViolationError,
)

from .log import logger

# ---------------------------------------------------------------------------
# Regular expressions used for parsing DDL statements
# ---------------------------------------------------------------------------

DOLLAR_QUOTE_PATTERN = re.compile(r"\$[A-Za-z0-9_]*\$")
CREATE_TABLE_PATTERN = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[\w\.\"]+)",
    re.IGNORECASE,
)
CREATE_INDEX_PATTERN = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[\w\"]+)",
    re.IGNORECASE,
)
CREATE_TRIGGER_PATTERN = re.compile(
    r"CREATE\s+TRIGGER\s+(?P<name>[\w\"]+)\s+.*?\s+ON\s+(?P<table>[\w\.\"]+)",
    re.IGNORECASE | re.DOTALL,
)
COMMENT_ON_TABLE_PATTERN = re.compile(
    r"COMMENT\s+ON\s+TABLE\s+(?P<name>[\w\.\"]+)\s+IS",
    re.IGNORECASE,
)

DDL_COMMENT_PREFIX = "DDL::"
DEFAULT_ADMIN_DATABASE = "postgres"
DEFAULT_SCHEMA = "public"


# ---------------------------------------------------------------------------
# Dataclasses representing the parsing output and execution reports
# ---------------------------------------------------------------------------


class Statement(BaseModel):
    """Represents a single SQL statement extracted from a DDL file.
    表示从 DDL 文件中提取的单个 SQL 语句。
    """

    raw: str = Field(description="Raw SQL statement text (原始 SQL 语句文本)")
    kind: str = Field(description="Type of SQL statement (e.g., CREATE, ALTER, etc.) (SQL 语句类型)")
    name: Optional[str] = Field(default=None, description="Name of the object being operated on (被操作对象的名称)")
    target_table: Optional[str] = Field(default=None, description="Target table for the statement (语句的目标表)")

    def to_report(self, action: str, message: str | None = None) -> "StatementReport":
        return StatementReport(kind=self.kind, name=self.name, action=action, message=message)


class StatementReport(BaseModel):
    """Execution result for a single SQL statement.
    单个 SQL 语句的执行结果。
    """

    kind: str = Field(description="Type of SQL statement (SQL 语句类型)")
    name: Optional[str] = Field(description="Name of the object (对象名称)")
    action: str = Field(description="Action performed on the statement (对语句执行的操作)")
    message: Optional[str] = Field(default=None, description="Additional message about the execution (关于执行的附加消息)")

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "kind": self.kind,
            "action": self.action,
        }
        if self.name:
            payload["name"] = self.name
        if self.message:
            payload["message"] = self.message
        return payload


class ColumnDefinition(BaseModel):
    """Simplified representation of a table column from the canonical DDL.
    来自规范 DDL 的表列的简化表示。
    """

    name: str = Field(description="Column name (列名)")
    data_type: str = Field(description="Column data type (列数据类型)")
    not_null: bool = Field(description="Whether the column has a NOT NULL constraint (列是否有 NOT NULL 约束)")
    default: Optional[str] = Field(description="Default value for the column (列的默认值)")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "data_type": self.data_type,
            "not_null": self.not_null,
            "default": self.default,
        }


class ColumnDiff(BaseModel):
    """Describes differences between canonical and actual column definitions.
    描述规范列定义与实际列定义之间的差异。
    """

    missing: List[str] = Field(default_factory=list, description="List of missing column names (缺失列名的列表)")
    extras: List[str] = Field(default_factory=list, description="List of extra column names (多余列名的列表)")
    mismatched: List[Dict[str, Any]] = Field(default_factory=list, description="List of mismatched column details (不匹配列详情的列表)")

    def is_clean(self) -> bool:
        return not (self.missing or self.extras or self.mismatched)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "missing_columns": self.missing,
            "extra_columns": self.extras,
            "mismatched_columns": self.mismatched,
        }


class TableDiff(BaseModel):
    """Aggregated difference information for a table.
    表的聚合差异信息。
    """

    exists: bool = Field(description="Whether the table exists (表是否存在)")
    column_diff: ColumnDiff = Field(default_factory=ColumnDiff, description="Column differences (列差异)")
    comment_hash_matches: bool = Field(default=True, description="Whether the comment hash matches (注释哈希是否匹配)")

    def is_clean(self) -> bool:
        return self.exists and self.column_diff.is_clean() and self.comment_hash_matches

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table_exists": self.exists,
            "column_diff": self.column_diff.to_dict(),
            "comment_hash_matches": self.comment_hash_matches,
        }


class TableDefinition(BaseModel):
    """Canonical representation for a single table.
    单个表的规范表示。
    """

    table_name: str = Field(description="Name of the table (表名)")
    file_path: Path = Field(description="Path to the DDL file (DDL 文件路径)")
    statements: List[Statement] = Field(description="List of SQL statements in the DDL (DDL 中的 SQL 语句列表)")
    file_hash: str = Field(description="Hash of the file content (文件内容的哈希值)")
    columns: Dict[str, ColumnDefinition] = Field(description="Dictionary of column definitions (列定义的字典)")
    database: str = Field(description="Database name (数据库名称)")

    @property
    def relative_path(self) -> str:
        return str(self.file_path.as_posix())


class TableApplyResult(BaseModel):
    """Result of applying a table definition to the database.
    将表定义应用到数据库的结果。
    """

    table: TableDefinition = Field(description="Table definition that was applied (已应用的表定义)")
    status: str = Field(description="Status of the application (e.g., 'created', 'updated', 'skipped') (应用状态)")
    statements: List[StatementReport] = Field(description="Results of individual statement executions (单个语句执行的结果)")
    diff: TableDiff = Field(description="Differences between canonical and actual table (规范表与实际表之间的差异)")
    warnings: List[str] = Field(default_factory=list, description="List of warnings generated during application (应用过程中产生的警告列表)")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table": self.table.table_name,
            "ddl_path": self.table.relative_path,
            "hash": self.table.file_hash,
            "status": self.status,
            "statements": [s.to_dict() for s in self.statements],
            "diff": self.diff.to_dict(),
            "warnings": self.warnings,
        }

    @property
    def is_successful(self) -> bool:
        return self.diff.is_clean() or self.status in {"created", "recreated"}


class DatabaseApplyResult(BaseModel):
    """Result of applying table definitions to a database.
    将表定义应用到数据库的结果。
    """

    database: str = Field(description="Name of the database (数据库名称)")
    database_created: bool = Field(description="Whether the database was created (是否创建了数据库)")
    table_results: List[TableApplyResult] = Field(description="Results of applying individual tables (应用单个表的结果)")
    warnings: List[str] = Field(default_factory=list, description="List of warnings generated during application (应用过程中产生的警告列表)")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "database": self.database,
            "database_created": self.database_created,
            "warnings": self.warnings,
            "tables": [t.to_dict() for t in self.table_results],
        }


class SchemaApplySummary(BaseModel):
    """Summary of applying schema changes across multiple databases.
    跨多个数据库应用模式更改的摘要。
    """

    databases: List[DatabaseApplyResult] = Field(description="List of database application results (数据库应用结果列表)")

    def to_dict(self) -> Dict[str, Any]:
        created_tables = sum(
            1 for db in self.databases for tbl in db.table_results if tbl.status in {"created", "recreated"})
        skipped_tables = sum(1 for db in self.databases for tbl in db.table_results if tbl.status == "skipped")
        drift_tables = sum(1 for db in self.databases for tbl in db.table_results if not tbl.diff.is_clean())

        return {
            "summary": {
                "databases": len(self.databases),
                "created_tables": created_tables,
                "skipped_tables": skipped_tables,
                "tables_with_drift": drift_tables,
            },
            "databases": [db.to_dict() for db in self.databases],
        }


# ---------------------------------------------------------------------------
# Helper functions for SQL parsing and normalization
# ---------------------------------------------------------------------------


def _strip_semicolon(statement: str) -> str:
    return statement[:-1] if statement.endswith(';') else statement


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _normalize_type(type_name: str) -> str:
    normalized = _normalize_whitespace(type_name.upper())
    normalized = normalized.replace("CHARACTER VARYING", "VARCHAR")
    normalized = normalized.replace("WITHOUT TIME ZONE", "")
    normalized = normalized.replace("WITH TIME ZONE", "TZ")
    normalized = normalized.replace("DOUBLE PRECISION", "DOUBLE")
    normalized = normalized.replace("TIMESTAMP TZ", "TIMESTAMP WITH TIME ZONE")
    normalized = normalized.replace("TIMESTAMP ", "TIMESTAMP ")  # ensure consistent spacing
    return normalized.strip()


def _normalize_default(default_value: Optional[str]) -> Optional[str]:
    if default_value is None:
        return None
    text = default_value.strip()
    if not text:
        return None
    # Drop PostgreSQL casting noise (e.g. ::character varying)
    text = re.sub(r"::[\w\s]+", "", text)
    return _normalize_whitespace(text)


def _split_sql_statements(sql_text: str) -> List[str]:
    """Split a raw SQL file into individual statements.
    将原始 SQL 文件拆分为单独的语句。

    This parser is intentionally lightweight but handles nested parentheses,
    comments, standard quoted strings, and PostgreSQL dollar-quoted bodies so
    that function definitions are preserved as single statements.
    该解析器故意设计得很轻量级，但能处理嵌套的括号、注释、标准引用字符串和 PostgreSQL 美元引用体，
    以便将函数定义保留为单个语句。
    """
    statements: List[str] = []
    buffer: List[str] = []
    depth = 0
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    current_dollar_quote: Optional[str] = None

    sql_text = sql_text.replace('\r\n', '\n')
    length = len(sql_text)
    index = 0

    while index < length:
        ch = sql_text[index]
        next_two = sql_text[index:index + 2]

        # Handle dollar quoted bodies
        if current_dollar_quote:
            if sql_text.startswith(current_dollar_quote, index):
                buffer.append(current_dollar_quote)
                index += len(current_dollar_quote)
                current_dollar_quote = None
                continue
            buffer.append(ch)
            index += 1
            continue

        # Handle block comments
        if not in_single and not in_double and not in_line_comment:
            dq_match = DOLLAR_QUOTE_PATTERN.match(sql_text, index)
            if dq_match:
                current_dollar_quote = dq_match.group(0)
                buffer.append(current_dollar_quote)
                index += len(current_dollar_quote)
                continue

            if not in_block_comment and next_two == '/*':
                in_block_comment = True
                index += 2
                continue
            if in_block_comment:
                if next_two == '*/':
                    in_block_comment = False
                    index += 2
                else:
                    index += 1
                continue
            if not in_line_comment and next_two == '--':
                in_line_comment = True
                index += 2
                continue

        if in_line_comment:
            if ch == '\n':
                in_line_comment = False
                buffer.append(ch)
            index += 1
            continue

        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == '(' and not in_single and not in_double:
            depth += 1
        elif ch == ')' and not in_single and not in_double and depth > 0:
            depth -= 1

        if ch == ';' and not in_single and not in_double and not in_block_comment and depth == 0:
            statement = ''.join(buffer).strip()
            buffer.clear()
            if statement:
                statements.append(statement)
            index += 1
            continue

        buffer.append(ch)
        index += 1

    tail = ''.join(buffer).strip()
    if tail:
        statements.append(tail)

    cleaned: List[str] = []
    for stmt in statements:
        upper = stmt.strip().upper()
        if upper in {"BEGIN", "COMMIT"}:
            continue
        cleaned.append(stmt.strip())
    return cleaned


def _extract_table_name(statement: str) -> Optional[str]:
    match = CREATE_TABLE_PATTERN.search(statement)
    if not match:
        return None
    return match.group('name').strip('"')


def _extract_index_name(statement: str) -> Optional[str]:
    match = CREATE_INDEX_PATTERN.search(statement)
    if not match:
        return None
    return match.group('name').strip('"')


def _extract_trigger_info(statement: str) -> Tuple[Optional[str], Optional[str]]:
    match = CREATE_TRIGGER_PATTERN.search(statement)
    if not match:
        return None, None
    trigger = match.group('name').strip('"')
    target = match.group('table').strip('"')
    return trigger, target


def _extract_columns(statement: str) -> Dict[str, ColumnDefinition]:
    table_start = statement.find('(')
    table_end = statement.rfind(')')
    if table_start == -1 or table_end == -1 or table_end <= table_start:
        return {}

    body = statement[table_start + 1:table_end]
    columns: Dict[str, ColumnDefinition] = {}
    buffer: List[str] = []
    depth = 0
    in_single = False
    in_double = False
    current_dollar_quote: Optional[str] = None

    index = 0
    length = len(body)
    while index < length:
        ch = body[index]

        if current_dollar_quote:
            if body.startswith(current_dollar_quote, index):
                buffer.append(current_dollar_quote)
                index += len(current_dollar_quote)
                current_dollar_quote = None
                continue
            buffer.append(ch)
            index += 1
            continue

        dq_match = DOLLAR_QUOTE_PATTERN.match(body, index)
        if dq_match and not in_single and not in_double:
            current_dollar_quote = dq_match.group(0)
            buffer.append(current_dollar_quote)
            index += len(current_dollar_quote)
            continue

        if ch == "'" and not in_double:
            in_single = not in_single
            buffer.append(ch)
            index += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            buffer.append(ch)
            index += 1
            continue
        if ch == '(' and not in_single and not in_double:
            depth += 1
        elif ch == ')' and not in_single and not in_double and depth > 0:
            depth -= 1

        if ch == ',' and depth == 0 and not in_single and not in_double:
            entry = ''.join(buffer).strip()
            buffer.clear()
            if entry:
                _append_column_entry(entry, columns)
            index += 1
            continue

        buffer.append(ch)
        index += 1

    tail = ''.join(buffer).strip()
    if tail:
        _append_column_entry(tail, columns)
    return columns


def _append_column_entry(entry: str, columns: Dict[str, ColumnDefinition]) -> None:
    upper = entry.upper()
    if upper.startswith(('CONSTRAINT', 'PRIMARY KEY', 'UNIQUE', 'FOREIGN KEY', 'CHECK')):
        return

    parts = entry.split(None, 2)
    if len(parts) < 2:
        return

    name = parts[0].strip('"')
    col_type = parts[1]
    remainder = parts[2] if len(parts) > 2 else ''
    not_null = 'NOT NULL' in remainder.upper()

    default_value: Optional[str] = None
    default_idx = remainder.upper().find('DEFAULT')
    if default_idx != -1:
        default_value = remainder[default_idx + len('DEFAULT'):].strip()

    columns[name] = ColumnDefinition(
        name=name,
        data_type=_normalize_type(col_type),
        not_null=not_null,
        default=_normalize_default(default_value),
    )


# ---------------------------------------------------------------------------
# Loader responsible for discovering DDL files
# ---------------------------------------------------------------------------


class DDLLoader:
    """Load and normalise canonical DDL files from the project tree.
    从项目树中加载并标准化规范 DDL 文件。
    """

    def __init__(self, ddl_root: Path):
        if not ddl_root.exists():
            raise FileNotFoundError(f"DDL directory not found: {ddl_root}")
        self.ddl_root = ddl_root
        self.common_files: List[Statement] = []
        self.databases: Dict[str, List[TableDefinition]] = {}
        self._load()

    def _load(self) -> None:
        # Load root-level SQL files (shared across databases). ``create_db.sql`` is
        # purposely ignored because database creation is handled programmatically.
        for sql_file in sorted(self.ddl_root.glob('*.sql')):
            if sql_file.name == 'create_db.sql':
                continue
            statements = self._load_statements(sql_file)
            self.common_files.extend(statements)

        # Load per-database folders.
        for db_dir in sorted([p for p in self.ddl_root.iterdir() if p.is_dir()]):
            db_name = db_dir.name
            tables: List[TableDefinition] = []
            for sql_file in sorted(db_dir.glob('*.sql')):
                table_def = self._load_table(db_name, sql_file)
                tables.append(table_def)
            self.databases[db_name] = tables

    def _load_statements(self, sql_file: Path) -> List[Statement]:
        raw_text = sql_file.read_text(encoding='utf-8')
        statements: List[Statement] = []
        for stmt_text in _split_sql_statements(raw_text):
            kind, name, target = self._classify_statement(stmt_text)
            statements.append(Statement(raw=stmt_text, kind=kind, name=name, target_table=target))
        return statements

    def _load_table(self, database: str, sql_file: Path) -> TableDefinition:
        raw_text = sql_file.read_text(encoding='utf-8')
        statements: List[Statement] = []
        canonical_table_name: Optional[str] = None
        for stmt_text in _split_sql_statements(raw_text):
            kind, name, target = self._classify_statement(stmt_text)
            if kind == 'create_table' and canonical_table_name is None:
                canonical_table_name = name
            statements.append(Statement(raw=stmt_text, kind=kind, name=name, target_table=target))

        if canonical_table_name is None:
            raise ValueError(f"No CREATE TABLE statement found in {sql_file}")

        columns = {}
        for stmt in statements:
            if stmt.kind == 'create_table':
                columns = _extract_columns(stmt.raw)
                break

        normalized_text = _normalize_whitespace(raw_text)
        file_hash = hashlib.sha256(normalized_text.encode('utf-8')).hexdigest()

        return TableDefinition(
            table_name=canonical_table_name,
            file_path=sql_file,
            statements=statements,
            file_hash=file_hash,
            columns=columns,
            database=database,
        )

    def _classify_statement(self, statement: str) -> Tuple[str, Optional[str], Optional[str]]:
        upper = statement.lstrip().upper()
        if upper.startswith('CREATE TABLE'):
            table_name = _extract_table_name(statement)
            return 'create_table', table_name, None
        if upper.startswith('CREATE INDEX') or upper.startswith('CREATE UNIQUE INDEX'):
            index_name = _extract_index_name(statement)
            return 'create_index', index_name, None
        if upper.startswith('CREATE TRIGGER'):
            trig_name, target = _extract_trigger_info(statement)
            return 'create_trigger', trig_name, target
        if upper.startswith('COMMENT ON TABLE'):
            table_name = _extract_table_name(statement)
            return 'comment', table_name, None
        if upper.startswith('INSERT INTO'):
            return 'insert', None, None
        if upper.startswith('ALTER TABLE'):
            return 'alter_table', None, None
        if upper.startswith('DO $$') or upper.startswith('DO $'):
            return 'do_block', None, None
        if upper.startswith('CREATE OR REPLACE FUNCTION'):
            return 'function', None, None
        return 'other', None, None


# ---------------------------------------------------------------------------
# Core manager that executes statements against PostgreSQL
# ---------------------------------------------------------------------------


@dataclass
class DatabaseConnectionConfig:
    host: str
    port: int
    user: str
    password: str
    admin_database: str = DEFAULT_ADMIN_DATABASE


class DDLManager:
    """Apply canonical DDL files to a PostgreSQL instance.
    将规范 DDL 文件应用到 PostgreSQL 实例。
    """

    def __init__(self, loader: DDLLoader, connection_config: DatabaseConnectionConfig):
        self.loader = loader
        self.connection_config = connection_config

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------

    async def ensure_schema(
            self,
            databases: Optional[Sequence[str]] = None,
            tables: Optional[Sequence[str]] = None,
            *,
            dry_run: bool = False,
    ) -> SchemaApplySummary:
        """Ensure the requested databases and tables exist.
        确保请求的数据库和表存在。

        Args:
            databases: Optional iterable of database names to process.  If
                omitted, all discovered databases are processed.
                可选的要处理的数据库名称的可迭代对象。如果省略，则处理所有发现的数据库。
            tables: Optional iterable of table names.  When provided the list is
                applied to each targeted database.
                可选的表名可迭代对象。提供时，该列表应用于每个目标数据库。
            dry_run: When ``True`` no changes are written to the database – the
                method only reports the actions that would be taken and the
                current drift status.
                当为 ``True`` 时，不向数据库写入任何更改——该方法仅报告将采取的操作和当前的漂移状态。
        """
        target_databases = self._select_databases(databases)
        results: List[DatabaseApplyResult] = []

        async with self._admin_connection() as admin_conn:
            for db_name, table_defs in target_databases:
                created = await self._ensure_database_exists(admin_conn, db_name, dry_run=dry_run)
                async with self._database_connection(db_name) as conn:
                    if not dry_run:
                        await self._ensure_registry_table(conn)
                    await self._execute_common_statements(conn, dry_run=dry_run)
                    table_results = []
                    for table_def in table_defs:
                        if tables and table_def.table_name not in tables:
                            continue
                        table_result = await self._apply_table(conn, table_def, dry_run=dry_run)
                        table_results.append(table_result)
                results.append(
                    DatabaseApplyResult(database=db_name, database_created=created, table_results=table_results))
        return SchemaApplySummary(databases=results)

    async def rebuild_database(self, database: str) -> SchemaApplySummary:
        """Drop and fully recreate a database using canonical DDL.
        使用规范 DDL 删除并完全重建数据库。
        """
        database = database.strip()
        if not database:
            raise ValueError("database name must not be empty")

        loader_tables = dict(self.loader.databases)
        if database not in loader_tables:
            raise ValueError(f"Unknown database '{database}' in DDL manifests")

        async with self._admin_connection() as admin_conn:
            await self._drop_database(admin_conn, database)
            await self._create_database(admin_conn, database)

        summary = await self.ensure_schema(databases=[database], dry_run=False)
        # Mark the single database result as recreated
        for db_result in summary.databases:
            if db_result.database == database:
                for table_result in db_result.table_results:
                    if table_result.status == 'created':
                        table_result.status = 'recreated'
        return summary

    async def rebuild_tables(
            self,
            database: str,
            tables: Sequence[str],
            *,
            cascade: bool = True,
    ) -> SchemaApplySummary:
        """Drop and recreate selected tables.
        删除并重建选定的表。
        """
        if not tables:
            raise ValueError("at least one table must be specified")
        table_set = {t.strip() for t in tables if t.strip()}
        if not table_set:
            raise ValueError("at least one table must be specified")

        target_defs = [tbl for tbl in self.loader.databases.get(database, []) if tbl.table_name in table_set]
        if len(target_defs) != len(table_set):
            missing = table_set.difference({tbl.table_name for tbl in target_defs})
            raise ValueError(f"Tables not found in canonical DDL for database '{database}': {sorted(missing)}")

        async with self._database_connection(database) as conn:
            for tbl in target_defs:
                qualified_name = self._format_qualified_name(tbl.table_name)
                drop_sql = f'DROP TABLE IF EXISTS {qualified_name} {"CASCADE" if cascade else ""}'.strip()
                await conn.execute(drop_sql)
            if target_defs and not await self._registry_exists(conn):
                await self._ensure_registry_table(conn)
            await self._execute_common_statements(conn, dry_run=False)
            table_results = []
            for tbl in target_defs:
                table_results.append(await self._apply_table(conn, tbl, dry_run=False))
        return SchemaApplySummary(
            databases=[DatabaseApplyResult(database=database, database_created=False, table_results=table_results)])

    async def diff_schema(
            self,
            databases: Optional[Sequence[str]] = None,
            tables: Optional[Sequence[str]] = None,
    ) -> SchemaApplySummary:
        """Produce a dry-run summary highlighting drift without making changes.
        生成一个突出显示漂移的预运行摘要，而不进行更改。
        """
        return await self.ensure_schema(databases=databases, tables=tables, dry_run=True)

    # ------------------------------------------------------------------
    # Internal helpers for database interactions
    # ------------------------------------------------------------------

    def _select_databases(self, databases: Optional[Sequence[str]]) -> List[Tuple[str, List[TableDefinition]]]:
        if databases is None:
            return sorted(self.loader.databases.items())
        selected: List[Tuple[str, List[TableDefinition]]] = []
        for name in databases:
            if name not in self.loader.databases:
                raise ValueError(f"Database '{name}' not found in DDL manifests")
            selected.append((name, self.loader.databases[name]))
        return selected

    async def _ensure_database_exists(self, admin_conn: Connection, database: str, *, dry_run: bool) -> bool:
        exists = await admin_conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", database)
        if exists:
            logger.debug("Database %s already exists", database)
            return False
        if dry_run:
            logger.info("[dry-run] Database %s would be created", database)
            return False
        await self._create_database(admin_conn, database)
        return True

    async def _create_database(self, admin_conn: Connection, database: str) -> None:
        logger.info("Creating database %s", database)
        await admin_conn.execute(f'CREATE DATABASE {self._quote_ident(database)}')

    async def _drop_database(self, admin_conn: Connection, database: str) -> None:
        logger.warning("Dropping database %s", database)
        await admin_conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1 AND pid <> pg_backend_pid()",
            database,
        )
        await admin_conn.execute(f'DROP DATABASE IF EXISTS {self._quote_ident(database)}')

    async def _ensure_registry_table(self, conn: Connection) -> None:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ddl_registry (
                id SERIAL PRIMARY KEY,
                object_type VARCHAR(32) NOT NULL,
                object_name VARCHAR(256) NOT NULL,
                ddl_hash VARCHAR(128) NOT NULL,
                ddl_path TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                extra JSONB DEFAULT '{}'::jsonb,
                UNIQUE(object_type, object_name)
            )
            """
        )

    async def _registry_exists(self, conn: Connection) -> bool:
        return bool(
            await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = $1 AND table_name = 'ddl_registry')",
                DEFAULT_SCHEMA,
            )
        )

    async def _execute_common_statements(self, conn: Connection, *, dry_run: bool) -> None:
        for idx, statement in enumerate(self.loader.common_files):
            report = await self._execute_statement(conn, statement, dry_run=dry_run)
            if report.action == 'failed':
                raise RuntimeError(f"Failed to execute common statement #{idx + 1}: {report.message}")

    async def _apply_table(self, conn: Connection, table_def: TableDefinition, *, dry_run: bool) -> TableApplyResult:
        table_existed = await self._table_exists(conn, table_def.table_name)
        table_created = False
        reports: List[StatementReport] = []
        warnings: List[str] = []

        for statement in table_def.statements:
            report = await self._execute_statement(conn, statement, dry_run=dry_run)
            reports.append(report)
            if statement.kind == 'create_table' and not dry_run:
                if report.action == 'executed':
                    table_created = True
                elif report.action == 'failed':
                    warnings.append('CREATE TABLE statement failed; see execution message for details.')

        diff = await self._compute_table_diff(conn, table_def)

        if dry_run:
            status = 'dry-run'
        elif table_created:
            status = 'created'
        elif not diff.exists:
            status = 'failed'
        elif table_existed:
            status = 'skipped'
        else:
            status = 'skipped'

        # 对于新建表，comment hash 还未写入时 `comment_hash_matches` 会为 False。
        # 为避免“先检查 comment 再写入 comment”的鸡生蛋问题，只要表存在且列结构一致，就写入元数据。
        # For newly created tables, the comment hash is not yet written, so `comment_hash_matches` may be False.
        # To avoid a chicken-and-egg issue, write metadata when the table exists and columns match.
        if not dry_run and diff.exists and diff.column_diff.is_clean():
            await self._update_table_metadata(conn, table_def)
        elif not diff.is_clean():
            warnings.append('Schema drift detected. Consider rebuilding the table or applying migrations.')

        return TableApplyResult(table=table_def, status=status, statements=reports, diff=diff, warnings=warnings)

    async def _execute_statement(self, conn: Connection, statement: Statement, *, dry_run: bool) -> StatementReport:
        if dry_run:
            return statement.to_report('pending', 'dry-run mode, statement not executed')

        try:
            if statement.kind == 'create_index' and statement.name:
                if await self._index_exists(conn, statement.name):
                    return statement.to_report('present', 'index already exists')
            elif statement.kind == 'create_trigger' and statement.name and statement.target_table:
                if await self._trigger_exists(conn, statement.name, statement.target_table):
                    return statement.to_report('present', 'trigger already exists')
            conn_result = await conn.execute(statement.raw)
            return statement.to_report('executed', conn_result)
        except UniqueViolationError as exc:
            return statement.to_report('skipped', f'unique constraint violation ignored: {exc}')
        except DuplicateTableError:
            return statement.to_report('present', 'table already exists')
        except DuplicateObjectError as exc:
            return statement.to_report('present', str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.error("Statement execution failed", exc_info=True)
            return statement.to_report('failed', str(exc))

    async def _compute_table_diff(self, conn: Connection, table_def: TableDefinition) -> TableDiff:
        exists = await self._table_exists(conn, table_def.table_name)
        if not exists:
            return TableDiff(exists=False, comment_hash_matches=False)

        actual_columns = await self._fetch_columns(conn, table_def.table_name)
        expected_columns = table_def.columns

        column_diff = ColumnDiff()
        for name, col_def in expected_columns.items():
            if name not in actual_columns:
                column_diff.missing.append(name)
                continue
            actual = actual_columns[name]
            if _normalize_type(actual['data_type']) != col_def.data_type:
                column_diff.mismatched.append(
                    {
                        'column': name,
                        'expected_type': col_def.data_type,
                        'actual_type': _normalize_type(actual['data_type']),
                    }
                )
            if bool(actual['not_null']) != col_def.not_null:
                column_diff.mismatched.append(
                    {
                        'column': name,
                        'expected_not_null': col_def.not_null,
                        'actual_not_null': bool(actual['not_null']),
                    }
                )
            expected_default = col_def.default
            actual_default = _normalize_default(actual['default'])
            if expected_default != actual_default:
                column_diff.mismatched.append(
                    {
                        'column': name,
                        'expected_default': expected_default,
                        'actual_default': actual_default,
                    }
                )

        for name in actual_columns:
            if name not in expected_columns:
                column_diff.extras.append(name)

        comment_ok = await self._comment_hash_matches(conn, table_def)
        return TableDiff(exists=True, column_diff=column_diff, comment_hash_matches=comment_ok)

    async def _update_table_metadata(self, conn: Connection, table_def: TableDefinition) -> None:
        comment_payload = {
            'hash': table_def.file_hash,
            'path': table_def.relative_path,
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
        comment_text = f"{DDL_COMMENT_PREFIX}{json.dumps(comment_payload, ensure_ascii=False)}"
        await conn.execute(
            f"COMMENT ON TABLE {self._format_qualified_name(table_def.table_name)} IS $1",
            comment_text,
        )
        await conn.execute(
            """
            INSERT INTO ddl_registry (object_type, object_name, ddl_hash, ddl_path, extra)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (object_type, object_name)
            DO UPDATE SET ddl_hash = EXCLUDED.ddl_hash,
                          ddl_path = EXCLUDED.ddl_path,
                          applied_at = CURRENT_TIMESTAMP,
                          extra = EXCLUDED.extra
            """,
            'table',
            table_def.table_name,
            table_def.file_hash,
            table_def.relative_path,
            json.dumps({'columns': list(table_def.columns)}),
        )

    async def _comment_hash_matches(self, conn: Connection, table_def: TableDefinition) -> bool:
        comment = await conn.fetchval("SELECT obj_description($1::regclass)", table_def.table_name)
        if not comment or not comment.startswith(DDL_COMMENT_PREFIX):
            return False
        try:
            payload = json.loads(comment[len(DDL_COMMENT_PREFIX):])
        except json.JSONDecodeError:
            return False
        return payload.get('hash') == table_def.file_hash

    async def _table_exists(self, conn: Connection, table_name: str) -> bool:
        return bool(await conn.fetchval('SELECT to_regclass($1)', table_name))

    async def _index_exists(self, conn: Connection, index_name: str) -> bool:
        return bool(await conn.fetchval('SELECT to_regclass($1)', index_name))

    async def _trigger_exists(self, conn: Connection, trigger_name: str, table_name: str) -> bool:
        return bool(
            await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = $1 AND tgrelid = $2::regclass)",
                trigger_name,
                table_name,
            )
        )

    async def _fetch_columns(self, conn: Connection, table_name: str) -> Dict[str, Dict[str, Any]]:
        schema_name, plain_table = self._split_table_name(table_name)
        rows = await conn.fetch(
            """
            SELECT a.attname AS column_name,
                   pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                   a.attnotnull AS not_null,
                   pg_catalog.pg_get_expr(ad.adbin, ad.adrelid) AS default
            FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_catalog.pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
            WHERE c.relname = $1
              AND n.nspname = $2
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
            """,
            plain_table,
            schema_name,
        )
        return {
            row['column_name']: {
                'data_type': row['data_type'],
                'not_null': row['not_null'],
                'default': row['default'],
            }
            for row in rows
        }

    def _admin_connection(self) -> "_AsyncConnectionContext":
        return _AsyncConnectionContext(
            asyncpg.connect(
                host=self.connection_config.host,
                port=self.connection_config.port,
                user=self.connection_config.user,
                password=self.connection_config.password,
                database=self.connection_config.admin_database,
            )
        )

    def _database_connection(self, database: str) -> "_AsyncConnectionContext":
        return _AsyncConnectionContext(
            asyncpg.connect(
                host=self.connection_config.host,
                port=self.connection_config.port,
                user=self.connection_config.user,
                password=self.connection_config.password,
                database=database,
            )
        )

    @staticmethod
    def _quote_ident(identifier: str) -> str:
        if not identifier:
            raise ValueError('identifier must not be empty')
        clean = identifier.strip('"')
        return f'"{clean}"'

    @staticmethod
    def _split_table_name(name: str) -> Tuple[str, str]:
        if '.' in name:
            schema, table = name.split('.', 1)
            return schema.strip('"'), table.strip('"')
        return DEFAULT_SCHEMA, name.strip('"')

    def _format_qualified_name(self, name: str) -> str:
        schema, table = self._split_table_name(name)
        return f'{self._quote_ident(schema)}.{self._quote_ident(table)}'


class _AsyncConnectionContext:
    """Async context helper wrapping an ``asyncpg.connect`` call.
    包装 ``asyncpg.connect`` 调用的异步上下文助手。
    """

    def __init__(self, connect_coro: Coroutine[Any, Any, Connection]):
        self._connect_coro = connect_coro
        self._conn: Optional[Connection] = None

    async def __aenter__(self) -> Connection:
        self._conn = await self._connect_coro
        return self._conn

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def build_manager_from_environment(ddl_root: Path, *, host: str, port: int, user: str, password: str,
                                   admin_database: str = DEFAULT_ADMIN_DATABASE) -> DDLManager:
    loader = DDLLoader(ddl_root)
    config = DatabaseConnectionConfig(host=host, port=port, user=user, password=password, admin_database=admin_database)
    return DDLManager(loader, config)
