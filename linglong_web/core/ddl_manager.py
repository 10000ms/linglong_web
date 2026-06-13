"""SQL 文件回放式 DDL 自管理模块（公开 API）。
SQL-script-replay DDL auto-initialization (public API).

本模块基于「目录下的 .sql 文件」做幂等建表，依赖 SQLAlchemy + ``Rmanager.pg_session()``。
另有 ``linglong_web.utils.ddl_manager``：基于「模型 + schema diff + ddl_registry 哈希」的
独立实现（直接用 asyncpg），定位不同、未在顶层导出——两者是有意为之的不同工具，并非重复，请勿混用。
A separate model/diff-based implementation lives in ``linglong_web.utils.ddl_manager``;
the two are intentionally different tools, not duplicates.

需要 PostgreSQL extra：``pip install "linglong-web[postgres]"``。
"""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Dict,
    List,
    Mapping,
    Sequence,
    Set,
    Tuple,
)

try:
    from sqlalchemy import text
except ImportError:  # pragma: no cover - optional dependency
    text = None

from .resource import Rmanager
from linglong_web.utils import logger

DEFAULT_STANDARD_COLUMNS: Dict[str, str] = {
    "flag": "SMALLINT DEFAULT 0",
    "created_time": "TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP",
    "update_time": "TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP",
}


@dataclass(slots=True)
class DDLManagerConfig:
    """DDL 管理配置
    Configuration object for the reusable DDL manager
    """

    script_path: Path | str
    enable_auto_init: bool = True
    trigger_sql_paths: Sequence[Path | str] | None = None
    required_extensions: Sequence[str] | None = None
    standard_columns: Mapping[str, str] | Sequence[Tuple[str, str]] | None = None
    abort_on_trigger_failure: bool = False

    def __post_init__(self) -> None:
        self.script_path = Path(self.script_path).resolve()

        triggers: Sequence[Path | str] = self.trigger_sql_paths or ()
        self.trigger_sql_paths = tuple(Path(path).resolve() for path in triggers)

        extensions = self.required_extensions or ()
        self.required_extensions = tuple(
            str(ext).strip()
            for ext in extensions
            if str(ext).strip()
        )

        if isinstance(self.standard_columns, Mapping):
            columns = {name: definition for name, definition in self.standard_columns.items()}
        elif self.standard_columns:
            columns = {name: definition for name, definition in self.standard_columns}
        else:
            columns = DEFAULT_STANDARD_COLUMNS.copy()
        self.standard_columns = columns


class AutoDDLManager:
    """通用 DDL 管理器
    Generic DDL manager that can be reused by any service
    """

    def __init__(self, config: DDLManagerConfig) -> None:
        if text is None:
            raise ImportError(
                "AutoDDLManager requires the 'postgres' extra. "
                'Install it with: pip install "linglong-web[postgres]"'
            )
        self.config = config
        self._ddl_dir = self.config.script_path

    async def check_and_init_tables(self) -> bool:
        """检查并初始化数据库表 / Ensure schema exists by replaying SQL scripts"""
        if not self.config.enable_auto_init:
            logger.info("DDL auto-init is disabled")
            return True

        try:
            logger.info("Starting DDL auto-init run (path=%s)", self._ddl_dir)

            await self._ensure_required_extensions()
            await self._ensure_trigger_functions()

            required_tables = await self._get_required_tables()
            logger.info("Required tables: %s", required_tables)

            missing_tables = await self._check_missing_tables(required_tables)
            if not missing_tables:
                logger.info("All required tables exist")
                return True

            logger.warning("Missing tables detected: %s", missing_tables)
            success = await self._create_missing_tables(missing_tables)

            if success:
                logger.info("DDL auto-init completed successfully")
            else:
                logger.error("DDL auto-init completed with errors")

            return success
        except Exception as exc:  # noqa: BLE001
            logger.error("DDL auto-init error: %s", exc, exc_info=True)
            return False

    async def _ensure_required_extensions(self) -> None:
        """确保 PostgreSQL 扩展可用 / Ensure required PostgreSQL extensions exist"""
        extensions = self.config.required_extensions or ()
        if not extensions:
            return

        async with Rmanager.pg_session() as session:
            async with session.begin():
                for ext in extensions:
                    stmt = text(f'CREATE EXTENSION IF NOT EXISTS "{ext}" WITH SCHEMA public')
                    await session.execute(stmt)
                    logger.info("Ensured PostgreSQL extension: %s", ext)

    async def _ensure_trigger_functions(self) -> None:
        """确保触发器 SQL 已执行 / Replay shared trigger helpers if present"""
        trigger_files = self._resolve_trigger_files()
        if not trigger_files:
            logger.info("No trigger helper files detected")
            return

        executed_any = False
        for trigger_file in trigger_files:
            if not trigger_file.exists():
                logger.warning("Trigger file not found: %s", trigger_file)
                continue

            try:
                logger.info("Ensuring trigger helpers from %s", trigger_file)
                sql_content = trigger_file.read_text(encoding="utf-8")
                statements = self._split_sql_statements(sql_content)
                if not statements:
                    logger.warning("Trigger file %s contains no executable statements", trigger_file)
                    continue

                async with Rmanager.pg_session() as session:
                    async with session.begin():
                        for stmt in statements:
                            await session.execute(text(stmt))
                executed_any = True
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to ensure trigger helpers %s: %s", trigger_file, exc, exc_info=True)
                if self.config.abort_on_trigger_failure:
                    raise

        if executed_any:
            logger.info("Trigger helpers ensured successfully")

    def _resolve_trigger_files(self) -> Tuple[Path, ...]:
        """确定需要执行的 trigger.sql 文件列表 / Resolve trigger helper candidates"""
        resolved: List[Path] = []
        seen: Set[Path] = set()

        for path in self.config.trigger_sql_paths or ():
            candidate = Path(path)
            if candidate not in seen:
                resolved.append(candidate)
                seen.add(candidate)

        fallback = self._ddl_dir.parent / "trigger.sql"
        if fallback.exists() and fallback not in seen:
            resolved.append(fallback)
            seen.add(fallback)

        return tuple(resolved)

    async def _get_required_tables(self) -> List[str]:
        """读取 DDL 目录下的所有 SQL 文件名 / Collect table names from SQL files"""
        if not self._ddl_dir.exists():
            logger.warning("DDL directory not found: %s", self._ddl_dir)
            return []

        return sorted(sql_file.stem for sql_file in self._ddl_dir.glob("*.sql"))

    async def _check_missing_tables(self, required_tables: List[str]) -> List[str]:
        """检查缺失的表 / List tables that do not yet exist"""
        missing_tables: List[str] = []

        async with Rmanager.pg_session() as session:
            async with session.begin():
                for table_name in required_tables:
                    query = text(
                        """
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_schema = 'public'
                            AND table_name = :table_name
                        )
                        """
                    )
                    result = await session.execute(query, {"table_name": table_name})
                    exists = result.scalar()
                    if not exists:
                        missing_tables.append(table_name)

        return missing_tables

    async def _create_missing_tables(self, missing_tables: List[str]) -> bool:
        """创建缺失的表并处理依赖 / Create missing tables with dependency ordering"""
        dependency_graph = self._build_dependency_graph(missing_tables)
        ordered_tables = self._topological_sort(dependency_graph)
        logger.info("Creating tables in dependency order: %s", ordered_tables)

        success = True
        for table_name in ordered_tables:
            sql_file = self._ddl_dir / f"{table_name}.sql"
            if not sql_file.exists():
                logger.error("DDL script not found: %s", sql_file)
                success = False
                continue

            try:
                sql_content = sql_file.read_text(encoding="utf-8")
                table_exists = await self._table_exists(table_name)

                if not table_exists:
                    await self._create_table(table_name, sql_content)
                else:
                    logger.warning("Table already exists: %s, checking schema updates", table_name)
                    await self._update_existing_table_schema(table_name, sql_content)

                await self._ensure_required_columns_exist(table_name)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to create/update table %s: %s", table_name, exc, exc_info=True)
                success = False

        return success

    async def _create_table(self, table_name: str, sql_content: str) -> None:
        statements = self._split_sql_statements(sql_content)
        if not statements:
            logger.warning("No SQL statements found for %s", table_name)
            return

        async with Rmanager.pg_session() as session:
            async with session.begin():
                for idx, stmt in enumerate(statements, 1):
                    await session.execute(text(stmt))
                    logger.debug("[%s] Executed statement %s/%s", table_name, idx, len(statements))

        logger.info("Created table successfully: %s", table_name)

    async def _table_exists(self, table_name: str) -> bool:
        async with Rmanager.pg_session() as session:
            async with session.begin():
                query = text(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = :table_name
                    )
                    """
                )
                result = await session.execute(query, {"table_name": table_name})
                return bool(result.scalar())

    async def _update_existing_table_schema(self, table_name: str, sql_content: str) -> None:
        """为已有表添加缺失列 / Add missing columns for existing tables"""
        required_columns = self._parse_required_columns_from_sql(sql_content)
        existing_columns = await self._get_existing_columns(table_name)

        missing_columns = {
            name: definition
            for name, definition in required_columns.items()
            if name not in existing_columns
        }

        if not missing_columns:
            logger.info("Table %s already contains all required columns", table_name)
            return

        async with Rmanager.pg_session() as session:
            async with session.begin():
                for name, definition in missing_columns.items():
                    alter_stmt = f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {name} {definition}"
                    await session.execute(text(alter_stmt))
                    logger.info("Added column %s to %s", name, table_name)

    async def _get_existing_columns(self, table_name: str) -> Dict[str, str]:
        async with Rmanager.pg_session() as session:
            async with session.begin():
                query = text(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    AND table_name = :table_name
                    """
                )
                result = await session.execute(query, {"table_name": table_name})
                return {row[0]: row[1] for row in result.fetchall()}

    async def _ensure_required_columns_exist(self, table_name: str) -> None:
        standard_columns = self.config.standard_columns or DEFAULT_STANDARD_COLUMNS
        existing_columns = await self._get_existing_columns(table_name)
        missing_columns = {
            name: definition
            for name, definition in standard_columns.items()
            if name not in existing_columns
        }

        if not missing_columns:
            return

        async with Rmanager.pg_session() as session:
            async with session.begin():
                for name, definition in missing_columns.items():
                    alter_stmt = f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {name} {definition}"
                    await session.execute(text(alter_stmt))
                    logger.info("Added standard column %s to %s", name, table_name)

    def _parse_required_columns_from_sql(self, sql_content: str) -> Dict[str, str]:
        """解析 SQL 中常见的标准列定义 / Parse required columns from the DDL file"""
        detected: Dict[str, str] = {}
        lowered = sql_content.lower()

        for name, definition in (self.config.standard_columns or DEFAULT_STANDARD_COLUMNS).items():
            if name in lowered:
                detected[name] = definition

        return detected

    def _build_dependency_graph(self, table_names: List[str]) -> Dict[str, Set[str]]:
        graph: Dict[str, Set[str]] = {}
        for table_name in table_names:
            sql_file = self._ddl_dir / f"{table_name}.sql"
            if not sql_file.exists():
                graph[table_name] = set()
                continue

            content = sql_file.read_text(encoding="utf-8")
            references = self._extract_table_references(content)
            dependencies = {ref for ref in references if ref in table_names and ref != table_name}
            graph[table_name] = dependencies
        return graph

    def _extract_table_references(self, sql_content: str) -> Set[str]:
        pattern = r"REFERENCES\s+(?:\")?([a-zA-Z0-9_]+)(?:\")?"
        matches = re.findall(pattern, sql_content, re.IGNORECASE)
        return set(matches) - {"public"}

    def _topological_sort(self, dependency_graph: Dict[str, Set[str]]) -> List[str]:
        in_degree = {table: 0 for table in dependency_graph}
        for table, dependencies in dependency_graph.items():
            for dep in dependencies:
                if dep in in_degree:
                    in_degree[table] += 1

        queue = [table for table, degree in in_degree.items() if degree == 0]
        ordered: List[str] = []

        while queue:
            current = queue.pop(0)
            ordered.append(current)
            for table, dependencies in dependency_graph.items():
                if current in dependencies:
                    in_degree[table] -= 1
                    if in_degree[table] == 0:
                        queue.append(table)

        if len(ordered) != len(dependency_graph):
            remaining = set(dependency_graph.keys()) - set(ordered)
            raise RuntimeError(f"Circular dependency detected: {remaining}")

        return ordered

    def _strip_transaction_wrappers(self, sql_content: str) -> str:
        filtered_lines = []
        for line in sql_content.split("\n"):
            stripped = line.strip().upper()
            if stripped in {"BEGIN;", "COMMIT;"}:
                continue
            filtered_lines.append(line)
        return "\n".join(filtered_lines)

    def _split_sql_statements(self, sql_content: str) -> List[str]:
        """智能 SQL 分割，兼容 $$ 函数与注释
        Robust SQL splitter that respects $$ bodies and comments
        """
        content = self._strip_transaction_wrappers(sql_content)
        statements: List[str] = []
        current: List[str] = []
        in_single_quote = False
        in_double_quote = False
        dollar_tag: str | None = None
        idx = 0

        while idx < len(content):
            char = content[idx]

            if char == "'" and not in_double_quote and dollar_tag is None:
                escaped = idx > 0 and content[idx - 1] == "\\"
                if not escaped:
                    in_single_quote = not in_single_quote
                current.append(char)
            elif char == '"' and not in_single_quote and dollar_tag is None:
                in_double_quote = not in_double_quote
                current.append(char)
            elif char == '$' and not in_single_quote and not in_double_quote:
                match = re.match(r"\$[A-Za-z0-9_]*\$", content[idx:])
                if match:
                    tag = match.group(0)
                    if dollar_tag is None:
                        dollar_tag = tag
                    elif dollar_tag == tag:
                        dollar_tag = None
                    current.append(tag)
                    idx += len(tag) - 1
                else:
                    current.append(char)
            elif char == ';' and not in_single_quote and not in_double_quote and dollar_tag is None:
                statement = ''.join(current).strip()
                if statement:
                    cleaned = self._remove_comments(statement)
                    if cleaned:
                        statements.append(cleaned)
                current = []
            else:
                current.append(char)

            idx += 1

        trailing = ''.join(current).strip()
        if trailing:
            cleaned = self._remove_comments(trailing)
            if cleaned:
                statements.append(cleaned)

        return statements

    def _remove_comments(self, statement: str) -> str:
        lines = []
        for line in statement.split('\n'):
            stripped = line.strip()
            if stripped and not stripped.startswith('--'):
                lines.append(line)
        return '\n'.join(lines).strip()
