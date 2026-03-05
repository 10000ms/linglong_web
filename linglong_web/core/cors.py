"""CORS decorator helpers for proxy style endpoints.

为代理类接口提供动态 CORS 处理，自动回显请求来源并移除限制性响应头。
"""
import functools
from typing import (
    Callable,
    Awaitable,
)

from starlette.requests import Request
from starlette.responses import Response


def allow_cors_specific(func: Callable[..., Awaitable[Response]]):
    """Inject flexible CORS headers for reverse-proxy style handlers.

    动态根据请求头 ``Origin`` 设置允许来源，且在成功响应时移除可能阻断注入脚本的
    `Content-Security-Policy` 与 `X-Frame-Options`。
    """

    @functools.wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        request_origin = request.headers.get("Origin") or request.headers.get("origin")
        allow_origin = request_origin if request_origin else "*"

        cors_headers = {
            "Access-Control-Allow-Origin": allow_origin,
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
            "Access-Control-Allow-Headers": (
                "Authorization, Content-Type, X-Requested-With, x-forwarded-uri, "
                "x-forwarded-proto, x-forwarded-host, x-forwarded-port, x-original-uri"
            ),
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Max-Age": "86400",
        }

        if request.method == "OPTIONS":
            return Response(status_code=204, headers=cors_headers)

        response = await func(request, *args, **kwargs)

        if isinstance(response, Response):
            for key, value in cors_headers.items():
                response.headers[key] = value
            for header_name in ("content-security-policy", "Content-Security-Policy", "X-Frame-Options"):
                if header_name in response.headers:
                    del response.headers[header_name]

        return response

    return wrapper
