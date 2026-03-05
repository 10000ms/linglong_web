import http

import pytest
from fastapi import APIRouter

from linglong_web import BaseRoute
from linglong_web import ServerRouter


async def _dummy_handler():
    return {"ok": True}


def test_server_router_registers_routes():
    router_factory = ServerRouter()
    router_factory.initialize([
        BaseRoute(path="/ping", method=http.HTTPMethod.GET.value, handler=_dummy_handler),
    ])
    router: APIRouter = router_factory.get_router()
    assert any(route.path == "/ping" for route in router.routes)


def test_server_router_rejects_invalid_method():
    router_factory = ServerRouter()
    with pytest.raises(ValueError):
        router_factory.initialize([
            BaseRoute(path="/invalid", method="BOLT", handler=_dummy_handler),
        ])
