import types

import pytest
from aio_pika.exceptions import AMQPConnectionError

from linglong_web.core.resource import (
    ResourceManager,
    _close_mongodb,
    _close_rabbitmq,
    _init_limiter,
    _init_mongodb,
    _init_rabbitmq,
    close_resources,
)
from linglong_web.core.schemas import (
    MongoConfig,
    RabbitMQConfig,
)


class _DummyRedisPool:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _DummyMQConn:
    def __init__(self) -> None:
        self.is_closed = False
        self.closed_called = False

    async def close(self) -> None:
        self.closed_called = True
        self.is_closed = True


class _DummyMongo:
    def __init__(self) -> None:
        self.closed = False
        self.admin = types.SimpleNamespace(command=self._admin_command)

    async def _admin_command(self, _cmd: str) -> None:
        return None

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_init_limiter_requires_redis_pool() -> None:
    resource = ResourceManager()
    resource.redis_pool = None
    resource.limiter = None

    with pytest.raises(RuntimeError, match="RedisPool is not initialized"):
        _init_limiter(resource)


@pytest.mark.asyncio
async def test_init_rabbitmq_skips_without_host(monkeypatch) -> None:
    resource = ResourceManager()

    called = {"n": 0}

    async def _connect_robust(**kwargs):  # noqa: ANN001
        called["n"] += 1
        return _DummyMQConn()

    monkeypatch.setattr("linglong_web.core.resource.aio_pika.connect_robust", _connect_robust)

    conf = RabbitMQConfig(host="", port=5672, username="u", password="p", vhost="/", service_name="svc")
    await _init_rabbitmq(resource, conf)

    assert called["n"] == 0
    assert resource.mq_conn is None


@pytest.mark.asyncio
async def test_init_rabbitmq_propagates_amqp_connection_error(monkeypatch) -> None:
    resource = ResourceManager()

    async def _connect_robust(**kwargs):  # noqa: ANN001
        raise AMQPConnectionError("boom")

    monkeypatch.setattr("linglong_web.core.resource.aio_pika.connect_robust", _connect_robust)

    conf = RabbitMQConfig(host="rabbit", port=5672, username="u", password="p", vhost="/", service_name="svc")
    with pytest.raises(AMQPConnectionError):
        await _init_rabbitmq(resource, conf)


@pytest.mark.asyncio
async def test_init_rabbitmq_success_sets_connection(monkeypatch) -> None:
    resource = ResourceManager()

    conn = _DummyMQConn()

    async def _connect_robust(**kwargs):  # noqa: ANN001
        return conn

    monkeypatch.setattr("linglong_web.core.resource.aio_pika.connect_robust", _connect_robust)

    conf = RabbitMQConfig(host="rabbit", port=5672, username="u", password="p", vhost="/", service_name="svc")
    await _init_rabbitmq(resource, conf)
    assert resource.mq_conn is conn


@pytest.mark.asyncio
async def test_init_mongodb_skips_without_uri(monkeypatch) -> None:
    resource = ResourceManager()

    called = {"n": 0}

    def _motor_client(_uri: str):
        called["n"] += 1
        return _DummyMongo()

    monkeypatch.setattr("linglong_web.core.resource.AsyncIOMotorClient", _motor_client)

    await _init_mongodb(resource, MongoConfig(uri=""))
    assert called["n"] == 0
    assert resource.mongo_client is None


@pytest.mark.asyncio
async def test_init_mongodb_propagates_errors(monkeypatch) -> None:
    resource = ResourceManager()

    class _BadMongo(_DummyMongo):
        async def _admin_command(self, _cmd: str) -> None:
            raise RuntimeError("nope")

    def _motor_client(_uri: str):
        return _BadMongo()

    monkeypatch.setattr("linglong_web.core.resource.AsyncIOMotorClient", _motor_client)

    with pytest.raises(RuntimeError, match="nope"):
        await _init_mongodb(resource, MongoConfig(uri="mongodb://x"))


@pytest.mark.asyncio
async def test_init_mongodb_success_sets_client(monkeypatch) -> None:
    resource = ResourceManager()

    mongo = _DummyMongo()

    def _motor_client(_uri: str):
        return mongo

    monkeypatch.setattr("linglong_web.core.resource.AsyncIOMotorClient", _motor_client)

    await _init_mongodb(resource, MongoConfig(uri="mongodb://x"))
    assert resource.mongo_client is mongo


@pytest.mark.asyncio
async def test_close_resources_closes_everything() -> None:
    resource = ResourceManager()

    resource.redis_pool = _DummyRedisPool()
    resource.mq_conn = _DummyMQConn()
    resource.mongo_client = _DummyMongo()
    resource.celery_app = object()  # any truthy marker

    await close_resources(resource=resource)

    assert resource.redis_pool is None
    assert resource.mq_conn is None
    assert resource.mongo_client is None
    assert resource.celery_app is None


@pytest.mark.asyncio
async def test_close_rabbitmq_noop_when_closed() -> None:
    resource = ResourceManager()
    conn = _DummyMQConn()
    conn.is_closed = True
    resource.mq_conn = conn

    await _close_rabbitmq(resource)

    assert resource.mq_conn is conn


@pytest.mark.asyncio
async def test_close_mongodb_noop_when_missing() -> None:
    resource = ResourceManager()
    resource.mongo_client = None
    await _close_mongodb(resource)
    assert resource.mongo_client is None
