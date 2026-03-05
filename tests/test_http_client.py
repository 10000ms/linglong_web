import pytest
from aiohttp import web

from linglong_web import LinglongConst
from linglong_web import LinglongHTTPException
from linglong_web import HTTPClientConfig, http_client
from linglong_web.utils import set_request_id


async def _start_app(port: int, handler):
    app = web.Application()
    app.router.add_route("*", "/echo", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=port)
    await site.start()
    return runner


@pytest.mark.asyncio
async def test_http_client_injects_request_id(unused_tcp_port):
    async def handler(request):
        return web.json_response({"headers": dict(request.headers)})

    runner = await _start_app(unused_tcp_port, handler)
    try:
        set_request_id("test-oid")
        resp = await http_client.get(
            f"http://127.0.0.1:{unused_tcp_port}/echo",
            format_type="json",
            timeout=HTTPClientConfig.INTERNAL_SERVICE_TIMEOUT,
        )
        data = resp.json_data
        header_name = LinglongConst.OID_HEADER_KEY
        assert data["headers"].get(header_name) == "test-oid"
    finally:
        await runner.cleanup()
        await http_client.graceful_close()


@pytest.mark.asyncio
async def test_http_client_raises_on_server_error(unused_tcp_port):
    async def handler(request):
        return web.Response(status=500, text="boom")

    runner = await _start_app(unused_tcp_port, handler)
    try:
        with pytest.raises(LinglongHTTPException):
            await http_client.get(
                f"http://127.0.0.1:{unused_tcp_port}/echo",
                timeout=HTTPClientConfig.INTERNAL_SERVICE_TIMEOUT,
                max_retries=0,
                passthrough_errors=False,
            )
    finally:
        await runner.cleanup()
        await http_client.graceful_close()


@pytest.mark.asyncio
async def test_http_client_retries_on_5xx_then_succeeds(unused_tcp_port):
    attempts = {"count": 0}

    async def handler(request):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return web.json_response({"error": "temporary"}, status=500)
        return web.json_response({"ok": True, "attempt": attempts["count"]})

    runner = await _start_app(unused_tcp_port, handler)
    try:
        resp = await http_client.get(
            f"http://127.0.0.1:{unused_tcp_port}/echo",
            format_type="json",
            timeout=HTTPClientConfig.INTERNAL_SERVICE_TIMEOUT,
            max_retries=1,
            retry_delay=0,
            passthrough_errors=False,
        )
        assert resp.status == 200
        assert resp.json_data["ok"] is True
        assert attempts["count"] == 2
    finally:
        await runner.cleanup()
        await http_client.graceful_close()
