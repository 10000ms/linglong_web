#!/usr/bin/env python3
"""Linglong Web 使用示例 / Quick usage example."""
import asyncio
from typing import (
    Any,
    Dict,
)
import http

from linglong_web import (
    BaseRoute,
    LinglongAppServer,
    LinglongConfigBase,
    ServerRouter,
    build_success_response,
)


class DemoConfig(LinglongConfigBase):
    """示例配置 / Demo configuration."""

    DEBUG = True
    SERVICE_NAME = "linglong-demo"
    LOGGING_ENABLE_FILE_HANDLER = False


async def main() -> None:
    """构建并运行一个最小可用的 Linglong 应用 / Build a minimal Linglong application."""

    router = ServerRouter()

    async def _ping_handler() -> Dict[str, Any]:
        """简单的健康检查接口 / Simple health endpoint."""

        return build_success_response({"pong": True}).model_dump()

    router.initialize([
        BaseRoute(path="/ping", method=http.HTTPMethod.GET, handler=_ping_handler),
    ])

    server = LinglongAppServer()
    await server.initialize(
        service_name="linglong-demo",
        router=router.get_router(),
        config_dict={"dev": DemoConfig},
    )

    # 本示例只展示初始化过程，不真正启动 uvicorn 以保持脚本可直接运行。
    # This example only demonstrates initialization and does not call server.start().
    print("Linglong demo server initialized successfully ✅")


if __name__ == "__main__":
    asyncio.run(main())
