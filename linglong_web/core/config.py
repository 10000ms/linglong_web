"""Linglong Web 配置代理 / Configuration proxy."""

import logging
import os
from typing import (
    Any,
    Dict,
)

from ..utils.pj_struct import Singleton
from ..utils.async_read_write_lock import AsyncReadWriteLock
from ..utils.log import logger


class LinglongConfigBase:
    """框架默认配置 / Default Linglong configuration."""

    DEBUG = False
    ENV_MODE = "prod"

    PGSQL_USER = "postgres"
    PGSQL_PASSWORD = "postgres123"
    PGSQL_DB = ""
    PGSQL_HOST = "postgres.internal"
    PGSQL_PORT = "5432"
    PGSQL_POOL_SIZE = 1
    PGSQL_MAX_OVERFLOW = 5
    PGSQL_DATABASES: Dict[str, Dict[str, Any]] | None = None
    DDL_REQUIRED_EXTENSIONS = ("pgcrypto",)

    MONGODB_URI = ""
    MONGODB_DB = ""
    MONGODB_COLLECTION = ""

    REDIS_HOST = "redis.internal"
    REDIS_PORT = 6379
    REDIS_PASSWORD = ""
    REDIS_MAXSIZE = None

    ENABLE_WORKFLOW_CELERY = False
    CELERY_BROKER_URL = None
    CELERY_RESULT_BACKEND = None
    CELERY_RESULT_BACKEND_DB = 0
    CELERY_APP_NAME = "linglong_app"
    CELERY_TASK_SERIALIZER = "json"
    CELERY_ACCEPT_CONTENT = ["json"]
    CELERY_RESULT_SERIALIZER = "json"
    CELERY_TIMEZONE = "UTC"
    CELERY_ENABLE_UTC = True
    CELERY_WORKER_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    CELERY_WORKER_TASK_LOG_FORMAT = (
        "%(asctime)s - %(name)s - %(levelname)s - task_id=%(task_id)s task_name=%(task_name)s - %(message)s"
    )

    LOGGING_LEVEL = logging.DEBUG
    LOGGING_ENABLE_FILE_HANDLER = False
    LOGGING_FILE_ADDR_FORMAT = "/opt/logs/server_app/app-{}.log"
    LOGGING_FILE_MAX_BYTES = 10 * 1024 * 1024
    LOGGING_FILE_BACKUP_COUNT = 10
    LOG_CONFIG = {"exchange_name": "log.topic.exchange"}

    LOG_PIPELINE_ENABLED = None
    LOG_PIPELINE_IGNORE_LEVELS = []
    LOG_RETENTION_DAYS = 7
    LOG_RETENTION_BATCH_LIMIT = 2000

    RABBITMQ_HOST = ""
    RABBITMQ_PORT = 5672
    RABBITMQ_VHOST = "/"
    RABBITMQ_USERNAME = ""
    RABBITMQ_PASSWORD = ""
    RABBITMQ_LOG_EXCHANGE = "logs.topic.exchange"
    RABBITMQ_LOG_QUEUE = "logs.business.infra.q"
    RABBITMQ_LOG_BINDING_KEY = "logs.business.#"
    RABBITMQ_LOG_PREFETCH = 200
    RABBITMQ_LOG_ROUTING_TEMPLATE = "logs.business.{service}.{level}"
    RABBITMQ_LOG_CONNECTION_NAME = ""

    CORS_ALLOWED_ORIGINS = ["http://localhost"]

    CELERY_WORKER_AUTOSTART = True
    CELERY_WORKER_LOG_LEVEL = "INFO"
    CELERY_WORKER_CONCURRENCY = 4
    CELERY_WORKER_POOL = None
    CELERY_WORKER_ENABLE_BEAT = True
    CELERY_WORKER_HOSTNAME_SUFFIX = ".inline"
    WORKFLOW_INLINE_MAX_CONCURRENCY = 4
    WORKFLOW_INLINE_QUEUE_LIMIT = 1024

    GRACEFUL_SHUTDOWN_TIMEOUT = 30


class LinglongConfigProxy(Singleton):
    """配置代理，支持线程安全读写 / Config proxy with thread-safe caching."""

    def __init__(self) -> None:
        self._active_config_class: type[LinglongConfigBase] = LinglongConfigBase
        self._lock = AsyncReadWriteLock()
        self._config_cache: Dict[str, Any] = {}
        self._cache_initialized = False

    def _ensure_cache_initialized(self) -> None:
        if self._cache_initialized:
            return
        with self._lock.write_locked():
            if self._cache_initialized:
                return
            for key in dir(self._active_config_class):
                if not key.startswith('_') and key.isupper():
                    self._config_cache[key] = getattr(self._active_config_class, key)
            self._cache_initialized = True

    def _set_active_config_class(self, config_class: type[LinglongConfigBase]) -> None:
        with self._lock.write_locked():
            self._active_config_class = config_class
            self._config_cache.clear()
            self._cache_initialized = False
            self._ensure_cache_initialized()

    def get(self, name: str, default: Any = None) -> Any:
        """按名读取配置项，缺失时返回默认值（dict 风格，永不抛异常）。
        Read a config value by name, returning ``default`` when absent (dict-like, never raises).

        与 ``__getattr__`` 行为一致，但用于"取不到给默认值"的场景，避免调用方写
        ``getattr(LinglongConfig, name, default)``。
        Mirrors ``__getattr__`` but returns a default instead of raising AttributeError.
        """
        self._ensure_cache_initialized()
        with self._lock.read_locked():
            if name in self._config_cache:
                return self._config_cache[name]
        if hasattr(self._active_config_class, name):
            value = getattr(self._active_config_class, name)
            with self._lock.write_locked():
                self._config_cache[name] = value
            return value
        return default

    def __getattr__(self, name: str) -> Any:
        if name.startswith('_'):
            return object.__getattribute__(self, name)
        self._ensure_cache_initialized()
        with self._lock.read_locked():
            if name in self._config_cache:
                return self._config_cache[name]
        if hasattr(self._active_config_class, name):
            value = getattr(self._active_config_class, name)
            with self._lock.write_locked():
                self._config_cache[name] = value
            return value
        raise AttributeError(f"Config has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith('_'):
            object.__setattr__(self, name, value)
            return
        self._ensure_cache_initialized()
        with self._lock.write_locked():
            self._config_cache[name] = value
            setattr(self._active_config_class, name, value)

    def apply_updates(self, updates: Dict[str, Any]) -> None:
        """批量更新配置值 / Apply a batch of configuration updates."""

        if not updates:
            return

        self._ensure_cache_initialized()
        with self._lock.write_locked():
            for key, value in updates.items():
                self._config_cache[key] = value
                setattr(self._active_config_class, key, value)

    def snapshot(self) -> Dict[str, Any]:
        self._ensure_cache_initialized()
        with self._lock.read_locked():
            return self._config_cache.copy()

    def reset(self) -> None:
        with self._lock.write_locked():
            self._config_cache.clear()
            self._cache_initialized = False
            self._ensure_cache_initialized()

    def load_from_dict(self, config_dict: Dict[str, Any]) -> None:
        """从字典批量加载配置 / Load all config values from a dict."""

        with self._lock.write_locked():
            self._config_cache.clear()
            self._config_cache.update(config_dict)
            for key, value in config_dict.items():
                setattr(self._active_config_class, key, value)
            self._cache_initialized = True
        self._ensure_cache_initialized()


LinglongConfig = LinglongConfigProxy()


def init_config(config_dict: Dict[str, type[LinglongConfigBase]], mode_name: str | None = None) -> LinglongConfigProxy:
    """初始化配置 / Initialize config based on NE_CONFIG or provided mode."""

    if mode_name is None:
        mode_name = os.getenv('LINGLONG_CONFIG', 'prod')
        logger.info("Linglong config mode not specified, using NE_CONFIG: %s", mode_name)

    config_cls = config_dict.get(mode_name)
    if config_cls is None:
        raise ValueError(
            f"Config mode '{mode_name}' not found in config_dict. Available: {list(config_dict.keys())}"
        )

    LinglongConfig._set_active_config_class(config_cls)
    logger.info("Linglong Config initialized with mode: %s, class: %s", mode_name, config_cls.__name__)
    return LinglongConfig
