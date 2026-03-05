"""Linglong Web 常量定义 / Linglong Web constants."""
import http
from enum import StrEnum


DEFAULT_DB_ALIAS = "default"

class HeaderKey(StrEnum):
    """请求头键常量 / HTTP header keys"""

    REQUEST_ID = "x-linglong-reqid"


class Environment(StrEnum):
    """运行环境常量 / Deployment environment constants"""

    DEVELOPMENT = "development"
    PRODUCTION = "production"


class LinglongConst:
    """框架级别常量集合 / Framework-wide constants."""

    OID_HEADER_KEY = HeaderKey.REQUEST_ID
    HTTP_METHODS = tuple(method.value for method in http.HTTPMethod)
    ENVIRONMENT = Environment

    @classmethod
    def is_http_method_supported(cls, method: str) -> bool:
        """判断 HTTP Method 是否被支持 / Check if HTTP method is allowed."""

        return method in cls.HTTP_METHODS

    # 注意：linglong 只维护与 Web 框架基础能力相关的常量。
    # Note: linglong keeps only core web-framework constants.
    #
    # 类似“服务注册 / 健康检查 / 远端配置 / 容器 hostname 判定”等微服务框架能力
    # 应由 cancan 统一内聚管理，禁止通过调用方反向注入到 linglong。
