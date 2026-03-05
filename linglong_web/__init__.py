"""Linglong Web – 异步 FastAPI 工具集 / Asynchronous FastAPI toolkit."""
from .__version__ import (
    __author__,
    __description__,
    __license__,
    __version__,
)

from .core.auth import login_required
from .core.cacher import cacher
from .core.cluster_lock import cluster_lock
from .core.config import (
    LinglongConfigBase,
    LinglongConfig,
    init_config,
)
from .core.constants import LinglongConst
from .core.cors import allow_cors_specific
from .core.db import TableBase
from .core.ddl_manager import (
    AutoDDLManager,
    DDLManagerConfig,
)
from .core.http import (
    HTTPClientConfig,
    AsyncHTTPClient,
    LinglongHTTPError,
    http_client,
)
from .core.limiter import LimiterGuard, limiter
from .core.limiter_local import (
    limiter_local,
    reset_limiter,
    get_limiter_stats,
)
from .core.resource import (
    ResourceManager,
    Rmanager,
    DEFAULT_DB_ALIAS,
    init_resources,
    close_resources,
)
from .core.response import (
    APIError,
    APIResponse,
    build_api_response,
    build_success_response,
    build_error_response,
)
from .core.router import (
    BaseRoute,
    ServerRouter,
)
from .core.scheduler import (
    BaseScheduler,
    SchedulerGroup,
    to_group,
)
from .core.server import LinglongAppServer
from .core.server_extensions import BaseServerExtension
from .core.schemas import (
    PgsqlConfig,
    RedisConfig,
    RabbitMQConfig,
    MongoConfig,
    CeleryConfig,
    ResourceInitConfig,
)
from .core.errors import (
    ErrorCode,
    ErrorMsg,
    LinglongHTTPException,
    LoginRequiredError,
    LimiterError,
    ClusterLockError,
)

__all__ = [
    "login_required",
    "cacher",
    "cluster_lock",
    "LinglongConfigBase",
    "LinglongConfig",
    "LinglongConst",
    "init_config",
    "allow_cors_specific",
    "TableBase",
    "AutoDDLManager",
    "DDLManagerConfig",
    "BaseRoute",
    "ServerRouter",
    "APIError",
    "APIResponse",
    "build_api_response",
    "build_success_response",
    "build_error_response",
    "HTTPClientConfig",
    "AsyncHTTPClient",
    "LinglongHTTPError",
    "http_client",
    "LimiterGuard",
    "limiter",
    "limiter_local",
    "reset_limiter",
    "get_limiter_stats",
    "ResourceManager",
    "Rmanager",
    "DEFAULT_DB_ALIAS",
    "init_resources",
    "close_resources",
    "BaseScheduler",
    "SchedulerGroup",
    "to_group",
    "LinglongAppServer",
    "BaseServerExtension",
    "PgsqlConfig",
    "RedisConfig",
    "RabbitMQConfig",
    "MongoConfig",
    "CeleryConfig",
    "ResourceInitConfig",
    "ErrorCode",
    "ErrorMsg",
    "LinglongHTTPException",
    "LoginRequiredError",
    "LimiterError",
    "ClusterLockError",
    "__version__",
    "__author__",
    "__license__",
    "__description__",
]
