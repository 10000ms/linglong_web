"""Tests for linglong_web.core.resource mapping/orchestration helpers.

重点覆盖：
- init_resources_from_conf 的配置映射逻辑（不连接外部依赖）
- close_resources 的关闭顺序与资源清理

Focus on:
- init_resources_from_conf mapping logic without touching external systems
- close_resources shutdown ordering and cleanup
"""
from dataclasses import dataclass

import pytest

from linglong_web.core import resource as resource_mod
from linglong_web.core.constants import DEFAULT_DB_ALIAS


@dataclass
class _DummyConf:
    # PGSQL
    PGSQL_HOST: str = "pg.internal"
    PGSQL_PORT: int = 5432
    PGSQL_USER: str = "user"
    PGSQL_PASSWORD: str = "pass"
    PGSQL_DB: str = "main"
    PGSQL_DATABASES: dict[str, dict] | None = None
    PGSQL_POOL_SIZE: int = 5
    PGSQL_MAX_OVERFLOW: int = 10

    # Redis
    REDIS_HOST: str = "redis.internal"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = "redispass"
    REDIS_MAXSIZE: int = 10

    # RabbitMQ
    RABBITMQ_HOST: str = "rabbit.internal"
    RABBITMQ_PORT: int = 5672
    RABBITMQ_USERNAME: str = "rmq"
    RABBITMQ_PASSWORD: str = "rmqpass"
    RABBITMQ_VHOST: str = "vhost"
    SERVICE_NAME: str = "svc"

    # Mongo
    MONGODB_URI: str = ""

    # Celery
    ENABLE_WORKFLOW_CELERY: bool = True
    CELERY_BROKER_URL: str | None = None
    CELERY_RESULT_BACKEND: str | None = None
    CELERY_RESULT_BACKEND_DB: int = 3
    CELERY_APP_NAME: str = "celery_app"

    # misc
    DEBUG: bool = False


@pytest.mark.asyncio
async def test_init_resources_from_conf_builds_resource_init_config(monkeypatch):
    captured = {}

    async def _fake_init_resources(*, config, resource=None):  # noqa: ANN001
        captured["config"] = config
        captured["resource"] = resource

    monkeypatch.setattr(resource_mod, "init_resources", _fake_init_resources)

    conf = _DummyConf(
        PGSQL_DATABASES={
            "analytics": {
                "database": "analytics",
                "host": "pg2.internal",
            },
        }
    )

    dummy_resource = object()
    await resource_mod.init_resources_from_conf(conf, resource=dummy_resource)

    cfg = captured["config"]
    assert cfg.enable_aioclock is True
    assert cfg.enable_limiter is True

    # PGSQL: default + extra
    assert cfg.pgsql_configs
    aliases = [c.alias for c in cfg.pgsql_configs]
    assert DEFAULT_DB_ALIAS in aliases
    assert "analytics" in aliases

    default_conf = next(c for c in cfg.pgsql_configs if c.alias == DEFAULT_DB_ALIAS)
    assert default_conf.host == conf.PGSQL_HOST
    assert default_conf.database == conf.PGSQL_DB

    extra_conf = next(c for c in cfg.pgsql_configs if c.alias == "analytics")
    assert extra_conf.host == "pg2.internal"
    assert extra_conf.database == "analytics"

    # Redis
    assert cfg.redis is not None
    assert cfg.redis.host == conf.REDIS_HOST

    # RabbitMQ
    assert cfg.rabbitmq is not None
    assert cfg.rabbitmq.host == conf.RABBITMQ_HOST

    # Celery auto url build
    assert cfg.celery is not None
    assert cfg.celery.broker_url.startswith("amqp://")
    assert "/vhost" in cfg.celery.broker_url
    assert cfg.celery.backend_url.startswith("redis://")


@pytest.mark.asyncio
async def test_close_resources_closes_pgsql_redis_and_calls_closers(monkeypatch):
    calls: list[str] = []

    class _DummyRedisPool:
        async def aclose(self):
            calls.append("redis_aclose")

    class _DummyResource:
        def __init__(self):
            self.redis_pool = _DummyRedisPool()

        async def close_pgsql_engines(self):
            calls.append("close_pgsql")

    dummy = _DummyResource()

    async def _fake_close_rmq(resource):  # noqa: ANN001
        calls.append("close_rmq")

    async def _fake_close_mongo(resource):  # noqa: ANN001
        calls.append("close_mongo")

    def _fake_close_celery(resource):  # noqa: ANN001
        calls.append("close_celery")

    monkeypatch.setattr(resource_mod, "_close_rabbitmq", _fake_close_rmq)
    monkeypatch.setattr(resource_mod, "_close_mongodb", _fake_close_mongo)
    monkeypatch.setattr(resource_mod, "_close_celery", _fake_close_celery)

    await resource_mod.close_resources(resource=dummy)

    assert "close_pgsql" in calls
    assert "redis_aclose" in calls
    assert "close_rmq" in calls
    assert "close_mongo" in calls
    assert "close_celery" in calls
    assert dummy.redis_pool is None
