"""服务器扩展钩子协议 / Server extension hook definitions."""
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 类型检查辅助 / typing helper only
    from fastapi import FastAPI

    from .server import LinglongAppServer


class BaseServerExtension:
    """扩展 Linglong Web 生命周期的基础类 / TableBase class for Linglong Web lifecycle extensions."""

    async def on_config_ready(self, server: "LinglongAppServer") -> None:
        """配置初始化完成后的钩子 / Triggered right after config initialization."""

    async def on_app_created(self, server: "LinglongAppServer", app: "FastAPI") -> None:
        """FastAPI 实例创建完成后的钩子 / Triggered once the FastAPI app is created."""

    async def on_startup(self, server: "LinglongAppServer") -> None:
        """服务启动回调前置钩子 / Runs before the application's startup callbacks."""

    async def on_shutdown(self, server: "LinglongAppServer") -> None:
        """服务关闭阶段钩子 / Runs during the shutdown sequence before cleanup."""
