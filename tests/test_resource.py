import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from linglong_web import ResourceManager


@pytest.mark.asyncio
async def test_resource_manager_pg_session():
    pytest.importorskip("aiosqlite")
    resource = ResourceManager()

    original_engines = resource._pgsql_engines
    original_params = resource._pgsql_engine_params
    resource._pgsql_engines = {}
    resource._pgsql_engine_params = {}

    try:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        params = {"url": "sqlite+aiosqlite:///:memory:"}
        resource.register_pgsql_engine("default", engine, params)

        async with resource.pg_session() as session:
            result = await session.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    finally:
        await resource.close_pgsql_engines()
        resource._pgsql_engines = original_engines
        resource._pgsql_engine_params = original_params
