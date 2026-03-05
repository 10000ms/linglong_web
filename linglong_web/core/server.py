"""Linglong Web AppServer 基础实现 / AppServer abstraction."""
import asyncio
import http
import os
import signal
import time
from contextlib import asynccontextmanager
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
)

import uvicorn
from aioclock import Group
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from nanoid import generate

from .config import LinglongConfig, LinglongConfigBase, init_config
from .constants import LinglongConst
from .errors import ErrorCode, ErrorMsg, LinglongHTTPException
from .http import http_client
from .resource import ResourceManager, close_resources, init_resources
from .response import build_error_response
from .scheduler import SchedulerGroup
from .server_extensions import BaseServerExtension
from ..utils.context import get_request_id, set_request_id
from ..utils.log import init_logger, logger
from ..utils.signal_handler import ServiceGracefulShutdown


class LinglongAppServer:
    """Linglong Web 通用服务启动器 / Generic Linglong service bootstrapper."""

    def __init__(self) -> None:
        self.app: FastAPI | None = None
        self.aioclock_group: Group | None = None
        self.initialized: bool = False
        self.service_name: str | None = None
        self.instance_id: str | None = None
        self.host: str | None = None
        self.port: int | None = None
        self._graceful_shutdown_manager: ServiceGracefulShutdown | None = None
        self._uvicorn_server: uvicorn.Server | None = None
        self._resource_manager = ResourceManager()
        self._extensions: List[BaseServerExtension] = []
        self._pending_shutdown_callbacks: List[Callable[[], Any]] = []
        self._startup_callbacks: List[Callable[[], Any]] = []
        self._shutdown_callbacks: List[Callable[[], Any]] = []

    async def initialize(
            self,
            service_name: str,
            router: APIRouter,
            config_dict: Dict[str, type[LinglongConfigBase]],
            scheduler_group: Group | SchedulerGroup | None = None,
            middleware: List[Callable[[Request, Callable[[Request], Awaitable[Any]]], Awaitable[Any]]] | None = None,
            on_startup: Optional[Sequence[Callable[[], Any]]] = None,
            on_shutdown: Optional[Sequence[Callable[[], Any]]] = None,
            extensions: Sequence[BaseServerExtension] | None = None,
            ) -> "LinglongAppServer":
        if self.initialized:
            return self
        if not service_name:
            raise ValueError("service_name is required")

        self.service_name = service_name
        self.instance_id = generate(size=8)

        init_config(config_dict)
        logger.info("Linglong Config initialized for service: %s", self.service_name)

        init_logger(
            level=LinglongConfig.LOGGING_LEVEL,
            enable_file_handler=LinglongConfig.LOGGING_ENABLE_FILE_HANDLER,
            file_addr=LinglongConfig.LOGGING_FILE_ADDR_FORMAT.format(self.service_name),
            max_bytes=LinglongConfig.LOGGING_FILE_MAX_BYTES,
            backup_count=LinglongConfig.LOGGING_FILE_BACKUP_COUNT,
        )
        self._extensions = list(extensions or [])
        await self._dispatch_extension_hook("on_config_ready")

        docs_url = "/docs" if LinglongConfig.DEBUG else None

        self._startup_callbacks = list(on_startup or [])
        self._shutdown_callbacks = list(on_shutdown or [])
        lifespan_handler = self._build_lifespan_handler(
            startup_callbacks=self._startup_callbacks,
            shutdown_callbacks=self._shutdown_callbacks,
        )

        self.app = FastAPI(
            docs_url=docs_url,
            lifespan=lifespan_handler,
        )
        await self._dispatch_extension_hook("on_app_created", self.app)

        self.app.include_router(router)
        self._add_error_handler()
        self._add_internal_routes()

        await self._before_resources_initialized()

        from .resource import init_resources_from_conf
        await init_resources_from_conf(LinglongConfig, resource=self._resource_manager)

        if isinstance(scheduler_group, SchedulerGroup):
            scheduler = scheduler_group.get_group()
        else:
            scheduler = scheduler_group

        if scheduler:
            self.aioclock_group = scheduler
            if self._resource_manager.AioClockAPP:
                self._resource_manager.AioClockAPP.include_group(scheduler)
            else:  # pragma: no cover - defensive guard
                logger.warning("AioClockAPP not initialized; scheduler group skipped.")

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=LinglongConfig.CORS_ALLOWED_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self.app.middleware('http')(self.middleware_handle_log)
        self.app.middleware('http')(self.middleware_handle_operate_id)
        self.app.middleware('http')(self.middleware_handle_inner_system_error_log)
        if middleware:
            for m in middleware:
                self.app.middleware('http')(m)

        self.initialized = True

        self._graceful_shutdown_manager = ServiceGracefulShutdown(
            service_name=self.service_name,
            shutdown_timeout=LinglongConfig.GRACEFUL_SHUTDOWN_TIMEOUT,
        )
        for callback in self._pending_shutdown_callbacks:
            self._graceful_shutdown_manager.add_cleanup_resource(callback)
        self._pending_shutdown_callbacks.clear()
        self._graceful_shutdown_manager.add_cleanup_resource(self._cleanup_resources)

        return self

    def _add_error_handler(self) -> None:
        self.app.add_exception_handler(http.HTTPStatus.NOT_FOUND, self.error_404)
        self.app.add_exception_handler(http.HTTPStatus.METHOD_NOT_ALLOWED, self.error_405)
        self.app.add_exception_handler(http.HTTPStatus.INTERNAL_SERVER_ERROR, self.error_500)
        self.app.add_exception_handler(LinglongHTTPException, self.http_exception)

    async def error_500(self, request: Request, exc: Exception):  # noqa: D401 - FastAPI handler
        s = http.HTTPStatus.INTERNAL_SERVER_ERROR
        response_model = build_error_response(
            code=ErrorCode.http_status_to_error_code(s),
            msg=ErrorMsg.get_msg(str(s.value)),
        )
        return ORJSONResponse(response_model.model_dump(), status_code=s.value)

    async def error_404(self, request: Request, exc: Exception):
        s = http.HTTPStatus.NOT_FOUND
        response_model = build_error_response(
            code=ErrorCode.http_status_to_error_code(s.value),
            msg=ErrorMsg.get_msg(str(s.value)),
        )
        return ORJSONResponse(response_model.model_dump(), status_code=s.value)

    async def error_405(self, request: Request, exc: Exception):
        s = http.HTTPStatus.METHOD_NOT_ALLOWED
        response_model = build_error_response(
            code=ErrorCode.http_status_to_error_code(s.value),
            msg=ErrorMsg.get_msg(str(s.value)),
        )
        return ORJSONResponse(response_model.model_dump(), status_code=s.value)

    async def http_exception(self, request: Request, exc: Exception):
        if isinstance(exc, LinglongHTTPException):
            status_code = getattr(exc, "status_code", http.HTTPStatus.INTERNAL_SERVER_ERROR.value)
            error_code = getattr(exc, "error_code", ErrorCode.SYSTEM_ERROR)
            message = getattr(exc, "message", ErrorMsg.get_msg(error_code))
        else:
            status_code = http.HTTPStatus.INTERNAL_SERVER_ERROR.value
            error_code = ErrorCode.SYSTEM_ERROR
            message = ErrorMsg.COMMON_ERROR

        response_model = build_error_response(code=error_code, msg=message)
        return ORJSONResponse(response_model.model_dump(), status_code=status_code)

    async def _before_resources_initialized(self) -> None:  # pragma: no cover - default hook
        """在初始化资源前执行，可由子类覆盖 / Hook before resource initialization."""
        pass

    def _add_internal_routes(self) -> None:  # pragma: no cover - default hook
        """供子类覆写以注册内部路由 / Allow subclasses to extend internal routes."""
        pass

    @staticmethod
    async def middleware_handle_operate_id(request: Request, call_next):
        key = LinglongConst.OID_HEADER_KEY
        incoming_request_id = request.headers.get(key)
        set_request_id(incoming_request_id)
        response = await call_next(request)
        response.headers[key] = get_request_id()
        return response

    @staticmethod
    async def middleware_handle_inner_system_error_log(request: Request, call_next):
        try:
            response = await call_next(request)
        except BaseException as exc:
            if not isinstance(exc, LinglongHTTPException):
                logger.error("inner system error: %s", exc, exc_info=True)
            raise exc
        return response

    @staticmethod
    async def middleware_handle_log(request: Request, call_next):
        start_time_nano = time.time_ns()
        logger.info("HTTP request: <%s> to <%s>", request.method, request.url)
        response = await call_next(request)
        logger.info(
            "HTTP handle time consuming: <%.2f> ms, response code: <%s>",
            (time.time_ns() - start_time_nano) / 1e6,
            response.status_code,
        )
        return response

    async def on_startup(self):
        await self._dispatch_extension_hook("on_startup")
        self._setup_signal_handlers()

    async def on_shutdown(self):
        await self._dispatch_extension_hook("on_shutdown")
        if self._graceful_shutdown_manager:
            await self._graceful_shutdown_manager.shutdown()

    async def start(self, **kwargs):
        default_config = dict(
            port=8080,
            host="127.0.0.1",
            log_level="info",
            loop="uvloop",
            access_log=False,
            reload=False,
            server_header=False,
        )

        config = dict(default_config, **kwargs)
        self.host = config.get("host", "127.0.0.1")
        self.port = config.get("port", 8080)

        if self._graceful_shutdown_manager:
            await self._graceful_shutdown_manager.initialize()

        server = uvicorn.Server(config=uvicorn.Config(self.app, **config))
        self._uvicorn_server = server

        api = asyncio.create_task(server.serve())
        task_list: List[asyncio.Task[Optional[bool]]] = [api]
        if self._resource_manager.aioclock_app and self.aioclock_group:
            sched = asyncio.create_task(self._resource_manager.aioclock_app.serve())
            task_list.append(sched)

        if self._graceful_shutdown_manager:
            shutdown_task = asyncio.create_task(self._graceful_shutdown_manager.wait_for_shutdown_signal())
            task_list.append(shutdown_task)

        done, pending = await asyncio.wait(task_list, return_when=asyncio.FIRST_COMPLETED)

        if self._graceful_shutdown_manager and self._graceful_shutdown_manager.is_shutting_down():
            logger.info("Shutdown signal received, initiating graceful shutdown...")

            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            await self._graceful_shutdown_manager.shutdown()

            if self._uvicorn_server and not self._uvicorn_server.should_exit:
                self._uvicorn_server.should_exit = True
                logger.info("Uvicorn server shutdown signal sent")

            await asyncio.sleep(1)
            logger.info("Exiting process...")
            os._exit(0)
        else:
            await asyncio.gather(*task_list)

    async def _cleanup_resources(self):
        try:
            await http_client.graceful_close()
            await close_resources(resource=self._resource_manager)
        except Exception as exc:  # pragma: no cover
            logger.error("Error during resource cleanup: %s", exc)

    def _setup_signal_handlers(self):
        def signal_handler(signum, frame):  # noqa: ARG001
            sig_name = signal.Signals(signum).name
            logger.info("Received signal %s (%s), initiating graceful shutdown...", sig_name, signum)
            loop = asyncio.get_event_loop()
            if loop.is_running() and self._graceful_shutdown_manager:
                loop.create_task(self._graceful_shutdown_manager.shutdown())

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        logger.info("Signal handlers registered for SIGTERM and SIGINT")

    def register_shutdown_callback(self, callback: Callable[[], Any]) -> None:
        """注册自定义清理协程 / Register a custom shutdown cleanup coroutine."""

        if self._graceful_shutdown_manager:
            self._graceful_shutdown_manager.add_cleanup_resource(callback)
        else:
            self._pending_shutdown_callbacks.append(callback)

    async def _dispatch_extension_hook(self, hook_name: str, *extra_args: Any) -> None:
        """依次触发扩展钩子 / Dispatch extension hooks in order."""

        for extension in self._extensions:
            hook = getattr(extension, hook_name, None)
            if not hook:
                continue
            result = hook(self, *extra_args)
            if asyncio.iscoroutine(result):
                await result

    def _build_lifespan_handler(
            self,
            startup_callbacks: Sequence[Callable[[], Any]],
            shutdown_callbacks: Sequence[Callable[[], Any]],
            ):
        """创建 FastAPI lifespan 处理器 / Build FastAPI lifespan handler."""

        startup_chain = list(startup_callbacks)
        shutdown_chain = list(shutdown_callbacks)

        @asynccontextmanager
        async def _lifespan(_app: FastAPI):  # noqa: D401 - FastAPI lifespan signature
            await self.on_startup()
            await self._run_lifecycle_callbacks(startup_chain)
            try:
                yield
            finally:
                await self.on_shutdown()
                await self._run_lifecycle_callbacks(shutdown_chain)

        return _lifespan

    async def _run_lifecycle_callbacks(self, callbacks: Sequence[Callable[[], Any]]) -> None:
        """顺序执行生命周期回调 / Execute lifecycle callbacks sequentially."""

        for callback in callbacks:
            result = callback()
            if asyncio.iscoroutine(result):
                await result
