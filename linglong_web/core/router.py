"""Linglong Web 路由工具 / Router utilities."""
import http
from typing import (
    Callable,
    List,
    Type,
)

from fastapi import APIRouter
from fastapi.responses import ORJSONResponse
from starlette.responses import Response

from .constants import LinglongConst


class BaseRoute:
    """路由配置描述 / Simple route descriptor."""

    def __init__(
            self,
            path: str,
            method: http.HTTPMethod,
            handler: Callable,
            response_model=None,
            response_class: Type[Response] = ORJSONResponse,
    ) -> None:
        self.path = path
        self.method = method
        self.handler = handler
        self.response_model = response_model
        self.response_class = response_class


class ServerRouter:
    """APIRouter 初始化器 / APIRouter initializer."""

    def __init__(self) -> None:
        self.router = APIRouter()

    def initialize(self, router_list: List[BaseRoute]) -> None:
        """批量注册路由 / Register routes in bulk."""

        for route in router_list:
            if not LinglongConst.is_http_method_supported(route.method):
                raise ValueError(f"HTTP method {route.method} is not supported")
            self.router.add_api_route(
                path=route.path,
                endpoint=route.handler,
                methods=[route.method],
                response_model=route.response_model,
                response_class=route.response_class,
            )

    def get_router(self) -> APIRouter:
        """获取底层 FastAPI Router / Get underlying FastAPI router."""

        return self.router
