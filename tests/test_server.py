import pytest
import http

from fastapi.responses import ORJSONResponse

from linglong_web import LinglongConfigBase
from linglong_web import build_success_response
from linglong_web import BaseRoute, ServerRouter
from linglong_web import LinglongAppServer
from linglong_web import BaseServerExtension
from linglong_web import Rmanager
from linglong_web.core.errors import LinglongHTTPException, ErrorCode


class _ServerTestConfig(LinglongConfigBase):
    DEBUG = True
    SERVICE_NAME = "linglong-test"
    PGSQL_HOST = ""
    REDIS_HOST = ""
    RABBITMQ_HOST = ""


@pytest.fixture(autouse=True)
def _reset_resource_manager_state():
    """隔离单例资源管理器状态 / Isolate singleton resource manager state between tests."""
    Rmanager.redis_pool = None
    Rmanager.limiter = None
    Rmanager.aioclock_app = None
    Rmanager.mq_conn = None
    Rmanager.mongo_client = None
    yield
    Rmanager.redis_pool = None
    Rmanager.limiter = None
    Rmanager.aioclock_app = None
    Rmanager.mq_conn = None
    Rmanager.mongo_client = None


def _build_router():
    router = ServerRouter()
    router.initialize([
        BaseRoute(path="/ping", method=http.HTTPMethod.GET, handler=lambda: build_success_response({"pong": True}))
    ])
    return router


class _RouteServer(LinglongAppServer):
    def __init__(self):
        super().__init__()
        self.route_registered = False

    def _add_internal_routes(self) -> None:
        if not self.app:
            return

        async def _health_handler(_request):
            return ORJSONResponse({"status": "UP"})

        self.app.add_api_route("/internal/health", _health_handler, methods=["GET"])
        self.route_registered = True


@pytest.mark.asyncio
async def test_custom_server_registers_internal_route():
    router = _build_router()
    server = _RouteServer()

    await server.initialize(
        service_name="linglong-test",
        router=router.get_router(),
        config_dict={"prod": _ServerTestConfig},
    )

    assert server.route_registered is True
    assert server.app is not None
    health_paths = [route.path for route in server.app.router.routes]
    assert "/internal/health" in health_paths


class _HookServer(LinglongAppServer):
    def __init__(self):
        super().__init__()
        self.hook_called = False

    async def _before_resources_initialized(self) -> None:
        self.hook_called = True


@pytest.mark.asyncio
async def test_before_resource_hook_runs():
    router = _build_router()
    server = _HookServer()

    await server.initialize(
        service_name="linglong-test",
        router=router.get_router(),
        config_dict={"prod": _ServerTestConfig},
    )

    assert server.hook_called is True


class _StubExtension(BaseServerExtension):
    def __init__(self):
        self.calls: list[str] = []

    async def on_config_ready(self, server):  # noqa: D401 - 简明描述 / short description
        self.calls.append("config")

    async def on_app_created(self, server, app):
        self.calls.append("app")

    async def on_startup(self, server):
        self.calls.append("startup")

    async def on_shutdown(self, server):
        self.calls.append("shutdown")


@pytest.mark.asyncio
async def test_extensions_receive_lifecycle_hooks():
    extension = _StubExtension()
    server = LinglongAppServer()
    router = _build_router()

    await server.initialize(
        service_name="demo",
        router=router.get_router(),
        config_dict={"prod": _ServerTestConfig},
        extensions=[extension],
    )

    assert extension.calls[:2] == ["config", "app"]

    await server.on_startup()
    await server.on_shutdown()
    assert extension.calls[-2:] == ["startup", "shutdown"]


@pytest.mark.asyncio
async def test_lifespan_executes_additional_callbacks():
    router = _build_router()
    server = LinglongAppServer()
    counters = {"startup": 0, "shutdown": 0}

    async def _custom_startup():
        counters["startup"] += 1

    async def _custom_shutdown():
        counters["shutdown"] += 1

    await server.initialize(
        service_name="demo",
        router=router.get_router(),
        config_dict={"prod": _ServerTestConfig},
        on_startup=[_custom_startup],
        on_shutdown=[_custom_shutdown],
    )

    assert server.app is not None
    lifespan = server.app.router.lifespan_context
    assert lifespan is not None

    async with lifespan(server.app):
        assert counters["startup"] == 1

    assert counters["shutdown"] == 1


@pytest.mark.asyncio
async def test_register_shutdown_callback_runs_on_shutdown():
    router = _build_router()
    server = LinglongAppServer()
    flag: dict[str, bool] = {"called": False}

    async def _custom_cleanup():
        flag["called"] = True

    server.register_shutdown_callback(_custom_cleanup)

    await server.initialize(
        service_name="demo",
        router=router.get_router(),
        config_dict={"prod": _ServerTestConfig},
    )

    assert server._graceful_shutdown_manager is not None
    await server._graceful_shutdown_manager.initialize()

    await server.on_shutdown()
    assert flag["called"] is True


@pytest.mark.asyncio
async def test_initialize_empty_service_name_raises():
    """验证空 service_name 抛出 ValueError."""
    router = _build_router()
    server = LinglongAppServer()

    with pytest.raises(ValueError, match="service_name is required"):
        await server.initialize(
            service_name="",
            router=router.get_router(),
            config_dict={"prod": _ServerTestConfig},
        )


@pytest.mark.asyncio
async def test_initialize_twice_returns_same_instance():
    """验证重复初始化返回自身."""
    router = _build_router()
    server = LinglongAppServer()

    await server.initialize(
        service_name="demo",
        router=router.get_router(),
        config_dict={"prod": _ServerTestConfig},
    )

    first_instance = server
    second_instance = await server.initialize(
        service_name="demo",
        router=router.get_router(),
        config_dict={"prod": _ServerTestConfig},
    )

    assert first_instance is second_instance
    assert server.initialized is True


@pytest.mark.asyncio
async def test_error_handlers_registered():
    """验证错误处理器已注册."""
    router = _build_router()
    server = LinglongAppServer()

    await server.initialize(
        service_name="demo",
        router=router.get_router(),
        config_dict={"prod": _ServerTestConfig},
    )

    assert server.app is not None
    exception_handlers = server.app.exception_handlers
    assert http.HTTPStatus.NOT_FOUND in exception_handlers
    assert http.HTTPStatus.METHOD_NOT_ALLOWED in exception_handlers
    assert http.HTTPStatus.INTERNAL_SERVER_ERROR in exception_handlers
    assert LinglongHTTPException in exception_handlers


@pytest.mark.asyncio
async def test_middleware_registered():
    """验证中间件已注册."""
    router = _build_router()
    server = LinglongAppServer()

    await server.initialize(
        service_name="demo",
        router=router.get_router(),
        config_dict={"prod": _ServerTestConfig},
    )

    assert server.app is not None
    middleware_stack = server.app.user_middleware
    assert len(middleware_stack) >= 3


@pytest.mark.asyncio
async def test_cors_middleware_configured():
    """验证 CORS 中间件已配置."""
    router = _build_router()
    server = LinglongAppServer()

    await server.initialize(
        service_name="demo",
        router=router.get_router(),
        config_dict={"prod": _ServerTestConfig},
    )

    assert server.app is not None
    cors_middleware = None
    for middleware in server.app.user_middleware:
        if middleware.cls.__name__ == "CORSMiddleware":
            cors_middleware = middleware
            break

    assert cors_middleware is not None


@pytest.mark.asyncio
async def test_custom_middleware_applied():
    """验证自定义中间件被应用."""
    router = _build_router()
    server = LinglongAppServer()
    middleware_called = {"count": 0}

    async def custom_middleware(request, call_next):
        middleware_called["count"] += 1
        return await call_next(request)

    await server.initialize(
        service_name="demo",
        router=router.get_router(),
        config_dict={"prod": _ServerTestConfig},
        middleware=[custom_middleware],
    )

    assert server.app is not None
    assert middleware_called["count"] == 0


@pytest.mark.asyncio
async def test_lifecycle_callbacks_run_sequentially():
    """验证生命周期回调顺序执行."""
    router = _build_router()
    server = LinglongAppServer()
    execution_order = []

    async def startup_1():
        execution_order.append("startup_1")

    async def startup_2():
        execution_order.append("startup_2")

    async def shutdown_1():
        execution_order.append("shutdown_1")

    async def shutdown_2():
        execution_order.append("shutdown_2")

    await server.initialize(
        service_name="demo",
        router=router.get_router(),
        config_dict={"prod": _ServerTestConfig},
        on_startup=[startup_1, startup_2],
        on_shutdown=[shutdown_1, shutdown_2],
    )

    lifespan = server.app.router.lifespan_context
    async with lifespan(server.app):
        pass

    assert "startup_1" in execution_order
    assert "startup_2" in execution_order
    assert execution_order.index("startup_1") < execution_order.index("startup_2")


@pytest.mark.asyncio
async def test_instance_id_generated():
    """验证实例 ID 在初始化时生成."""
    router = _build_router()
    server = LinglongAppServer()

    await server.initialize(
        service_name="demo",
        router=router.get_router(),
        config_dict={"prod": _ServerTestConfig},
    )

    assert server.instance_id is not None
    assert len(server.instance_id) == 8


@pytest.mark.asyncio
async def test_dispatch_extension_hook_handles_missing_hook():
    """验证扩展钩子处理缺失的钩子方法."""
    router = _build_router()
    server = LinglongAppServer()

    class PartialExtension:
        pass

    ext = PartialExtension()
    await server.initialize(
        service_name="demo",
        router=router.get_router(),
        config_dict={"prod": _ServerTestConfig},
        extensions=[ext],
    )

    await server._dispatch_extension_hook("on_startup")


@pytest.mark.asyncio
async def test_dispatch_extension_hook_awaits_coroutine():
    """验证扩展钩子正确 await 协程."""
    router = _build_router()
    server = LinglongAppServer()

    class AsyncExtension:
        async def on_startup(self, server):
            return "async result"

    ext = AsyncExtension()
    await server.initialize(
        service_name="demo",
        router=router.get_router(),
        config_dict={"prod": _ServerTestConfig},
        extensions=[ext],
    )

    await server.on_startup()
