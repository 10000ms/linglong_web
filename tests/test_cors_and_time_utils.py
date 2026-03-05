"""Tests for small utility modules (CORS + time).

These modules are pure and should be fully covered by unit tests.
这些模块是纯逻辑模块，应该用单元测试覆盖核心分支。
"""
from datetime import datetime

import pytest

from starlette.requests import Request
from starlette.responses import Response

from linglong_web.core.cors import allow_cors_specific
from linglong_web.utils.time import to_server_tz_iso


def test_to_server_tz_iso_handles_none() -> None:
    assert to_server_tz_iso(None) is None


def test_to_server_tz_iso_normalizes_naive_datetime_to_utc_then_target() -> None:
    # naive dt should be treated as UTC in current implementation
    dt = datetime(2026, 1, 1, 0, 0, 0)
    iso = to_server_tz_iso(dt)
    assert iso is not None
    assert "+08:00" in iso or "+08" in iso  # default ServerTargetTZ is Asia/Shanghai


@pytest.mark.asyncio
async def test_allow_cors_specific_handles_options_preflight() -> None:
    @allow_cors_specific
    async def handler(request: Request) -> Response:
        return Response("ok")

    async def _receive():  # noqa: ANN001
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "OPTIONS",
        "path": "/",
        "headers": [(b"origin", b"https://example.com")],
        "query_string": b"",
        "scheme": "http",
        "server": ("test", 80),
        "client": ("test", 12345),
        "root_path": "",
        "http_version": "1.1",
    }
    request = Request(scope, _receive)

    resp = await handler(request)
    assert resp.status_code == 204
    assert resp.headers["Access-Control-Allow-Origin"] == "https://example.com"


@pytest.mark.asyncio
async def test_allow_cors_specific_injects_headers_and_strips_restrictive_headers() -> None:
    @allow_cors_specific
    async def handler(request: Request) -> Response:
        return Response(
            "ok",
            headers={
                "Content-Security-Policy": "default-src 'self'",
                "X-Frame-Options": "DENY",
            },
        )


    async def _receive():  # noqa: ANN001
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"origin", b"https://example.com")],
        "query_string": b"",
        "scheme": "http",
        "server": ("test", 80),
        "client": ("test", 12345),
        "root_path": "",
        "http_version": "1.1",
    }
    request = Request(scope, _receive)

    resp = await handler(request)
    assert resp.status_code == 200
    assert resp.headers["Access-Control-Allow-Origin"] == "https://example.com"
    assert "content-security-policy" not in resp.headers
    assert "x-frame-options" not in resp.headers

    # default fallback
    scope2 = dict(scope)
    scope2["headers"] = []
    resp2 = await handler(Request(scope2, _receive))
    assert resp2.headers["Access-Control-Allow-Origin"] == "*"
