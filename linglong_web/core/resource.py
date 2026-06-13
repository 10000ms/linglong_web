"""Linglong Web 资源管理器 / Resource manager."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import (
    Any,
    AsyncGenerator,
    Dict,
)

# 核心依赖（始终可用）/ Core deps (always available)
from aioclock import AioClock
from limits.aio.storage import RedisStorage
from limits.aio.strategies import MovingWindowRateLimiter
from redis import asyncio as aioredis

# 可选后端依赖：缺失时降级为 None，仅在真正使用对应能力时才友好报错。
# Optional backend deps: degrade to None when absent; a friendly error is raised
# only when the corresponding capability is actually used.
try:
    import asyncpg
except ImportError:  # pragma: no cover - optional dependency
    asyncpg = None

try:
    from sqlalchemy.ext.asyncio import (
        AsyncEngine,
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
except ImportError:  # pragma: no cover - optional dependency
    AsyncEngine = AsyncSession = async_sessionmaker = create_async_engine = None

try:
    import aio_pika
    from aio_pika.exceptions import AMQPConnectionError
    from aio_pika.robust_connection import RobustConnection
except ImportError:  # pragma: no cover - optional dependency
    aio_pika = None
    AMQPConnectionError = None
    RobustConnection = None

try:
    from celery import Celery
except ImportError:  # pragma: no cover - optional dependency
    Celery = None

try:
    from pymongo import AsyncMongoClient
except ImportError:  # pragma: no cover - optional dependency
    AsyncMongoClient = None

from ..core.constants import DEFAULT_DB_ALIAS
from ..core.schemas import (
    CeleryConfig,
    MongoConfig,
    PgsqlConfig,
    RabbitMQConfig,
    RedisConfig,
    ResourceInitConfig,
)
from ..utils.log import logger
from ..utils.pj_struct import Singleton


def _require(dep: object, extra: str, feature: str) -> None:
    """缺失可选依赖时给出可操作的报错。
    Raise an actionable error when an optional backend dependency is missing.
    """
    if dep is None:
        raise ImportError(
            f"{feature} requires the '{extra}' extra. "
            f'Install it with: pip install "linglong-web[{extra}]"'
        )


class ResourceManager(Singleton):
    """统一的资源管理器 / Unified resource orchestrator."""

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._pgsql_engines: Dict[str, Dict[int, AsyncEngine]] = {}
        self._pgsql_engine_loops: Dict[str, Dict[int, asyncio.AbstractEventLoop]] = {}
        self._pgsql_engine_params: Dict[str, Dict[str, Any]] = {}
        self.redis_pool: aioredis.ConnectionPool | None = None
        self.aioclock_app: AioClock | None = None
        self.limiter: MovingWindowRateLimiter | None = None
        self.celery_app: Celery | None = None
        self.mq_conn: RobustConnection | None = None
        self.mongo_client: AsyncMongoClient | None = None
        self._initialized = True

    # --- Attribute aliases ----------------------------------------------------------------

    @property
    def PGSQLAsyncEngine(self) -> AsyncEngine | None:
        return self.get_pgsql_engine(DEFAULT_DB_ALIAS)

    @PGSQLAsyncEngine.setter
    def PGSQLAsyncEngine(self, engine: AsyncEngine | None) -> None:
        loop_id = self._current_loop_id()
        if loop_id is None:
            return
        alias_engines = self._pgsql_engines.setdefault(DEFAULT_DB_ALIAS, {})
        if engine is None:
            alias_engines.pop(loop_id, None)
        else:
            alias_engines[loop_id] = engine

    @property
    def RedisPool(self) -> aioredis.ConnectionPool | None:
        return self.redis_pool

    @RedisPool.setter
    def RedisPool(self, pool: aioredis.ConnectionPool | None) -> None:
        self.redis_pool = pool

    @property
    def AioClockAPP(self) -> AioClock | None:
        return self.aioclock_app

    @AioClockAPP.setter
    def AioClockAPP(self, app: AioClock | None) -> None:
        self.aioclock_app = app

    @property
    def Limiter(self) -> MovingWindowRateLimiter | None:
        return self.limiter

    @Limiter.setter
    def Limiter(self, limiter: MovingWindowRateLimiter | None) -> None:
        self.limiter = limiter

    @property
    def CeleryApp(self) -> Celery | None:
        return self.celery_app

    @CeleryApp.setter
    def CeleryApp(self, app: Celery | None) -> None:
        self.celery_app = app

    @property
    def MQConn(self) -> RobustConnection | None:
        return self.mq_conn

    @MQConn.setter
    def MQConn(self, conn: RobustConnection | None) -> None:
        self.mq_conn = conn

    @property
    def MongoClient(self) -> AsyncMongoClient | None:
        return self.mongo_client

    @MongoClient.setter
    def MongoClient(self, client: AsyncMongoClient | None) -> None:
        self.mongo_client = client

    def _current_loop_id(self) -> int | None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None
        return id(loop)

    def _current_loop(self) -> asyncio.AbstractEventLoop | None:
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

    @staticmethod
    def _schedule_engine_dispose(loop: asyncio.AbstractEventLoop, engine: AsyncEngine, *, alias: str, loop_id: int) -> None:
        """在 engine 所属的 event loop 上触发 dispose。
        Schedule dispose on the engine's own event loop.

        说明 / Notes:
        - AsyncEngine/asyncpg 连接对象与创建它的 event loop 强绑定。
          AsyncEngine/asyncpg connections are bound to the loop that created them.
        - 在错误的 loop 上 await dispose() 会触发 "Future attached to a different loop"。
          Disposing on a different loop can raise cross-loop RuntimeError.
        """

        if loop.is_closed() or not loop.is_running():
            logger.warning(
                "skip disposing pgsql engine because its loop is not running - alias=%s loop_id=%s",
                alias,
                loop_id,
            )
            return

        def _create_task() -> None:
            try:
                loop.create_task(engine.dispose())
            except Exception as exc:  # pragma: no cover - best effort cleanup
                logger.warning(
                    "failed to schedule pgsql engine dispose - alias=%s loop_id=%s err=%s",
                    alias,
                    loop_id,
                    exc,
                )

        try:
            loop.call_soon_threadsafe(_create_task)
        except Exception as exc:  # pragma: no cover - best effort cleanup
            logger.warning(
                "failed to call_soon_threadsafe for pgsql engine dispose - alias=%s loop_id=%s err=%s",
                alias,
                loop_id,
                exc,
            )

    def register_pgsql_engine(self, alias: str, engine: AsyncEngine, params: Dict[str, Any]) -> None:
        self._pgsql_engine_params[alias] = params
        loop = self._current_loop()
        if loop is None:
            return

        loop_id = id(loop)
        self._pgsql_engines.setdefault(alias, {})[loop_id] = engine
        self._pgsql_engine_loops.setdefault(alias, {})[loop_id] = loop

    def get_pgsql_engine(self, alias: str) -> AsyncEngine | None:
        loop_id = self._current_loop_id()
        if loop_id is None:
            return None

        alias_engines = self._pgsql_engines.setdefault(alias, {})
        engine = alias_engines.get(loop_id)
        if engine:
            return engine

        # 如果同一个进程里 event loop 被替换（例如某些运行方式/线程场景），
        # 旧 loop 的 engine 可能不会被 close_resources() 及时释放，从而累积连接。
        # 注意：AsyncEngine 必须在创建它的 loop 上 dispose，否则会触发 cross-loop 异常。
        #
        # If the event loop changes within the same process, engines bound to the old loop
        # may linger. IMPORTANT: dispose must run on the engine's own loop to avoid cross-loop errors.
        if alias_engines:
            loops_map = self._pgsql_engine_loops.setdefault(alias, {})
            for other_loop_id, other_engine in list(alias_engines.items()):
                if other_loop_id == loop_id:
                    continue
                alias_engines.pop(other_loop_id, None)
                other_loop = loops_map.pop(other_loop_id, None)
                if other_loop is not None:
                    self._schedule_engine_dispose(other_loop, other_engine, alias=alias, loop_id=other_loop_id)
                logger.info(
                    "stale pgsql engine detached - alias=%s old_loop_id=%s new_loop_id=%s",
                    alias,
                    other_loop_id,
                    loop_id,
                )

        params = self._pgsql_engine_params.get(alias)
        if not params:
            return None

        engine = create_async_engine(**params)
        alias_engines[loop_id] = engine
        return engine

    def _get_pgsql_engine(self, alias: str) -> AsyncEngine:
        engine = self.get_pgsql_engine(alias)
        if engine is None:
            raise RuntimeError(f"PGSQL engine '{alias}' is not initialized")
        return engine

    @asynccontextmanager
    async def pg_session(self, db_alias: str = DEFAULT_DB_ALIAS) -> AsyncGenerator[AsyncSession, None]:
        engine = self._get_pgsql_engine(db_alias)
        session = async_sessionmaker(engine, expire_on_commit=False)()
        try:
            yield session
        finally:
            await session.close()

    async def close_pgsql_engines(self) -> None:
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        current_loop_id = id(current_loop) if current_loop is not None else None

        for alias, engines in list(self._pgsql_engines.items()):
            loops_map = self._pgsql_engine_loops.get(alias, {})
            for engine_loop_id, engine in list(engines.items()):
                engine_loop = loops_map.get(engine_loop_id)
                if current_loop_id is not None and engine_loop_id == current_loop_id:
                    await engine.dispose()
                    logger.info("close pgsql success - alias=%s loop_id=%s", alias, engine_loop_id)
                elif engine_loop is not None:
                    self._schedule_engine_dispose(engine_loop, engine, alias=alias, loop_id=engine_loop_id)
                    logger.info("scheduled pgsql close - alias=%s loop_id=%s", alias, engine_loop_id)
                else:
                    logger.warning("skip pgsql close due to missing loop ref - alias=%s loop_id=%s", alias, engine_loop_id)

            engines.clear()

        self._pgsql_engines.clear()
        self._pgsql_engine_loops.clear()


async def _init_pgsql(
        resource: ResourceManager,
        config: PgsqlConfig,
) -> None:
    _require(asyncpg, "postgres", "PostgreSQL support")
    _require(create_async_engine, "postgres", "PostgreSQL support")
    await _ensure_database_exists(config)
    engine_params = dict(
        url=f"postgresql+asyncpg://{config.user}:{config.password}@{config.host}:{config.port}/{config.database}",
        echo=config.echo,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_recycle=3600,
        pool_timeout=60,
        pool_pre_ping=True,
        future=True,
    )
    engine = create_async_engine(**engine_params)
    resource.register_pgsql_engine(config.alias, engine, engine_params)
    logger.info("init pgsql success - alias=%s, database=%s", config.alias, config.database)


async def _init_redis(
        resource: ResourceManager,
        config: RedisConfig,
) -> None:
    resource.redis_pool = aioredis.ConnectionPool.from_url(
        f"redis://{config.host}:{config.port}/?password={config.password}",
        max_connections=config.maxsize,
        encoding='utf-8',
    )
    logger.info("init redis success")


def _init_aioclock(resource: ResourceManager) -> None:
    resource.AioClockAPP = AioClock()
    logger.info("init aioclock success")


def _init_limiter(resource: ResourceManager) -> None:
    if resource.limiter:
        return
    if not resource.redis_pool:
        raise RuntimeError("RedisPool is not initialized")
    aio_redis_storage = RedisStorage(
        uri="redis://",
        implementation="redispy",
        connection_pool=resource.redis_pool,  # type: ignore[arg-type]
    )
    resource.limiter = MovingWindowRateLimiter(aio_redis_storage)


async def _init_rabbitmq(
        resource: ResourceManager,
        config: RabbitMQConfig,
) -> None:
    if not config.host:
        return
    _require(aio_pika, "rabbitmq", "RabbitMQ support")
    try:
        connection = await aio_pika.connect_robust(
            host=config.host,
            port=config.port,
            login=config.username,
            password=config.password,
            virtualhost=config.vhost,
            client_properties={"connection_name": f"linglong-{config.service_name}"},
            heartbeat=30,
            timeout=15,
        )
        resource.mq_conn = connection
        logger.info("init rabbitmq success")
    except AMQPConnectionError as e:
        logger.error("Failed to connect to RabbitMQ: %s", e)
        raise


async def _close_rabbitmq(resource: ResourceManager) -> None:
    if resource.mq_conn and not resource.mq_conn.is_closed:
        await resource.mq_conn.close()
        resource.mq_conn = None
        logger.info("close rabbitmq success")


async def _init_mongodb(resource: ResourceManager, config: MongoConfig) -> None:
    if not config.uri:
        logger.warning("MONGODB_URI is not configured, skipping MongoDB initialization.")
        return
    _require(AsyncMongoClient, "mongo", "MongoDB support")
    try:
        client = AsyncMongoClient(config.uri)
        await client.admin.command('hello')
        resource.mongo_client = client
        logger.info("init mongodb success")
    except Exception as e:
        logger.error("Failed to connect to MongoDB: %s", e)
        raise


async def _close_mongodb(resource: ResourceManager) -> None:
    if resource.mongo_client:
        await resource.mongo_client.close()
        resource.mongo_client = None
        logger.info("close mongodb success")


def _build_amqp_url(user: str, password: str, host: str, port: int | str, vhost: str) -> str:
    normalized_vhost = vhost or "/"
    if not normalized_vhost.startswith("/"):
        normalized_vhost = f"/{normalized_vhost}"
    return f"amqp://{user}:{password}@{host}:{port}{normalized_vhost}"


def _build_redis_url(host: str, port: int | str, password: str | None, db: int) -> str:
    auth = f":{password}@" if password else ""
    return f"redis://{auth}{host}:{port}/{db}"


def _init_celery(
        resource: ResourceManager,
        config: CeleryConfig,
) -> None:
    _require(Celery, "celery", "Celery support")
    celery_app = Celery(config.app_name, broker=config.broker_url, backend=config.backend_url)
    celery_app.conf.update(**config.config_options)
    
    # Ensure standard worker logging is configured as per previous logic
    celery_app.conf.update(
        worker_hijack_root_logger=False,
    )

    if config.beat_schedule:
        celery_app.conf.beat_schedule = config.beat_schedule

    resource.celery_app = celery_app
    logger.info("init celery success")


def _close_celery(resource: ResourceManager) -> None:
    if resource.celery_app:
        resource.celery_app = None
        logger.info("close celery success")


Rmanager = ResourceManager()


def _quote_ident(value: str) -> str:
    """转义数据库标识符，防止 SQL 注入
    Quote identifier to avoid SQL injection issues."""
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


async def _ensure_database_exists(config: PgsqlConfig) -> None:
    """在初始化 ORM 之前确保数据库已创建
    Ensure target database exists before creating ORM engine."""
    if not config.ensure_database:
        logger.info(
            "skip ensure database because ensure_database flag disabled - alias=%s db=%s",
            config.alias,
            config.database,
        )
        return

    bootstrap_db = config.bootstrap_database or "postgres"
    owner = config.create_db_owner or config.user
    conn = await asyncpg.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=bootstrap_db,
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", config.database)
        if exists:
            logger.info(
                "database already exists - alias=%s db=%s",
                config.alias,
                config.database,
            )
            return

        create_sql = f"CREATE DATABASE {_quote_ident(config.database)} WITH TEMPLATE template0 ENCODING 'UTF8'"
        if owner:
            create_sql = f"{create_sql} OWNER {_quote_ident(owner)}"

        try:
            await conn.execute(create_sql)
            logger.info(
                "database created automatically - alias=%s db=%s owner=%s",
                config.alias,
                config.database,
                owner,
            )
        except asyncpg.DuplicateDatabaseError:
            logger.info(
                "database simultaneously created by other worker - alias=%s db=%s",
                config.alias,
                config.database,
            )
    finally:
        await conn.close()


async def init_resources(
        config: ResourceInitConfig,
        resource: ResourceManager | None = None,
) -> None:
    logger.info("start init resources")
    resource = resource or Rmanager

    if config.pgsql_configs:
        for pg_conf in config.pgsql_configs:
            await _init_pgsql(resource, pg_conf)

    if config.redis:
        await _init_redis(resource, config.redis)

    if config.rabbitmq:
        await _init_rabbitmq(resource, config.rabbitmq)

    if config.mongodb:
        await _init_mongodb(resource, config.mongodb)

    if config.enable_aioclock:
        _init_aioclock(resource)

    if config.enable_limiter and resource.redis_pool:
        _init_limiter(resource)

    if config.celery:
        _init_celery(resource, config.celery)
    
    logger.info("init resources success")


async def init_resources_from_conf(conf: Any, resource: ResourceManager | None = None) -> None:
    """Helper to initialize resources from a configuration object."""
    
    pgsql_configs = []
    if (conf.PGSQL_HOST and conf.PGSQL_USER) or conf.PGSQL_DATABASES:
        # Default DB
        if conf.PGSQL_HOST and conf.PGSQL_USER:
            pgsql_configs.append(PgsqlConfig(
                alias=DEFAULT_DB_ALIAS,
                host=conf.PGSQL_HOST,
                port=int(conf.PGSQL_PORT),
                user=conf.PGSQL_USER,
                password=conf.PGSQL_PASSWORD,
                database=conf.PGSQL_DB,
                pool_size=getattr(conf, "PGSQL_POOL_SIZE", 5),
                max_overflow=getattr(conf, "PGSQL_MAX_OVERFLOW", 10),
                echo=getattr(conf, "DEBUG", False),
            ))
        
        # Extra DBs
        db_dict = getattr(conf, "PGSQL_DATABASES", {}) or {}
        for alias, db_info in db_dict.items():
            if alias == DEFAULT_DB_ALIAS and pgsql_configs:
                continue # Already added default
            
            # Use default values as base if available, otherwise strict requirement from override
            base_host = conf.PGSQL_HOST
            base_port = int(conf.PGSQL_PORT) if conf.PGSQL_PORT else 5432
            base_user = conf.PGSQL_USER
            base_pass = conf.PGSQL_PASSWORD
            base_db = conf.PGSQL_DB
            
            # This logic mimics the old `_merge_db_config` somewhat but cleanly maps to model
            pgsql_configs.append(PgsqlConfig(
                alias=alias,
                host=db_info.get("host", base_host),
                port=int(db_info.get("port", base_port)),
                user=db_info.get("user", base_user),
                password=db_info.get("password", base_pass),
                database=db_info.get("database", base_db),
                pool_size=db_info.get("pool_size", getattr(conf, "PGSQL_POOL_SIZE", 5)),
                max_overflow=db_info.get("max_overflow", getattr(conf, "PGSQL_MAX_OVERFLOW", 10)),
                echo=db_info.get("echo", getattr(conf, "DEBUG", False)),
            ))

    redis_config = None
    if conf.REDIS_HOST and conf.REDIS_PORT:
        maxsize = getattr(conf, "REDIS_MAXSIZE", None)
        if maxsize is None:
            maxsize = 10
        redis_config = RedisConfig(
            host=conf.REDIS_HOST,
            port=int(conf.REDIS_PORT),
            password=conf.REDIS_PASSWORD or "",
            maxsize=int(maxsize),
        )

    rabbitmq_config = None
    if conf.RABBITMQ_HOST:
        rabbitmq_config = RabbitMQConfig(
            host=conf.RABBITMQ_HOST,
            port=int(conf.RABBITMQ_PORT),
            username=conf.RABBITMQ_USERNAME,
            password=conf.RABBITMQ_PASSWORD,
            vhost=conf.RABBITMQ_VHOST or "/",
            service_name=getattr(conf, "SERVICE_NAME", "unknown"),
        )

    mongodb_config = None
    if conf.MONGODB_URI:
        mongodb_config = MongoConfig(uri=conf.MONGODB_URI)

    celery_config = None
    if getattr(conf, "ENABLE_WORKFLOW_CELERY", False):
        broker_url = getattr(conf, "CELERY_BROKER_URL", None) or _build_amqp_url(
            conf.RABBITMQ_USERNAME,
            conf.RABBITMQ_PASSWORD,
            conf.RABBITMQ_HOST,
            conf.RABBITMQ_PORT,
            conf.RABBITMQ_VHOST,
        )
        backend_url = getattr(conf, "CELERY_RESULT_BACKEND", None) or _build_redis_url(
            conf.REDIS_HOST,
            conf.REDIS_PORT,
            conf.REDIS_PASSWORD,
            getattr(conf, "CELERY_RESULT_BACKEND_DB", 0),
        )

        celery_config = CeleryConfig(
            app_name=getattr(conf, "CELERY_APP_NAME", "celery_app"),
            broker_url=broker_url,
            backend_url=backend_url,
            config_options={
                "task_serializer": getattr(conf, "CELERY_TASK_SERIALIZER", "json"),
                "accept_content": getattr(conf, "CELERY_ACCEPT_CONTENT", ["json"]),
                "result_serializer": getattr(conf, "CELERY_RESULT_SERIALIZER", "json"),
                "timezone": getattr(conf, "CELERY_TIMEZONE", "UTC"),
                "enable_utc": getattr(conf, "CELERY_ENABLE_UTC", True),
                "worker_log_format": getattr(conf, "CELERY_WORKER_LOG_FORMAT", None),
                "worker_task_log_format": getattr(conf, "CELERY_WORKER_TASK_LOG_FORMAT", None),
            },
            beat_schedule=getattr(conf, "CELERY_BEAT_SCHEDULE", None),
        )

    resource_init_config = ResourceInitConfig(
        pgsql_configs=pgsql_configs,
        redis=redis_config,
        rabbitmq=rabbitmq_config,
        mongodb=mongodb_config,
        celery=celery_config,
        enable_aioclock=True,
        enable_limiter=True
    )

    await init_resources(config=resource_init_config, resource=resource)


async def close_resources(resource: ResourceManager | None = None) -> None:
    logger.info("start close resources")
    resource = resource or Rmanager

    await resource.close_pgsql_engines()

    if resource.redis_pool:
        await resource.redis_pool.aclose()
        resource.redis_pool = None
        logger.info("close redis success")

    await _close_rabbitmq(resource)
    await _close_mongodb(resource)
    _close_celery(resource)
    logger.info("close resources success")
