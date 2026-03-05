import asyncio
import time
import types

import pytest
from yarl import URL

from linglong_web.core.errors import ErrorCode
from linglong_web.core.http import (
    AsyncHTTPClient,
    LinglongHTTPError,
)


class _DummyResponse:
    def __init__(self, *, status: int, url: str = "http://example.com/api") -> None:
        self.status = status
        self.url = URL(url)
        self.headers = {"content-type": "text/plain"}
        self.request_info = types.SimpleNamespace(headers={"x-test": "1", "authorization": "secret"})
        self._released = False

    async def text(self) -> str:
        return f"dummy-status={self.status}"

    async def json(self, content_type=None):  # noqa: ANN001
        return {"status": self.status}

    def release(self) -> None:
        self._released = True


class _DummySession:
    connector = None

    async def request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("request should be monkeypatched via AsyncHTTPClient._execute_request")


@pytest.mark.asyncio
async def test_generate_curl_command_merges_params_and_json() -> None:
    client = AsyncHTTPClient()
    curl = client._generate_curl_command(
        "http://example.com/api?existing=1",
        "post",
        {"x-a": "b"},
        {"params": {"k": "v"}, "json": {"hello": "world"}},
    )
    assert "curl" in curl
    assert "-X POST" in curl
    assert "existing=1" in curl
    assert "k=v" in curl
    assert "--json" in curl


@pytest.mark.asyncio
async def test_fetch_retries_on_5xx_and_raises() -> None:
    client = AsyncHTTPClient()

    async def _ensure_session():
        return _DummySession()

    call_count = {"n": 0}

    async def _execute_request(session, method: str, url: str, **kwargs):  # noqa: ANN001
        call_count["n"] += 1
        return _DummyResponse(status=500, url=url)

    async def _sleep(_delay: float) -> None:
        return None

    client.ensure_session = _ensure_session  # type: ignore[method-assign]
    client._execute_request = _execute_request  # type: ignore[method-assign]
    client._last_conn_pool_log = float("inf")

    original_sleep = asyncio.sleep
    asyncio.sleep = _sleep  # type: ignore[assignment]
    try:
        with pytest.raises(LinglongHTTPError) as exc_info:
            await client.fetch(
                "GET",
                "http://example.com/api",
                format_type="text",
                max_retries=1,
                retry_delay=0.01,
            )
        assert exc_info.value.status_code == 500
        assert call_count["n"] == 2
    finally:
        asyncio.sleep = original_sleep


@pytest.mark.asyncio
async def test_fetch_401_maps_to_user_unlogin_error() -> None:
    client = AsyncHTTPClient()

    async def _ensure_session():
        return _DummySession()

    async def _execute_request(session, method: str, url: str, **kwargs):  # noqa: ANN001
        return _DummyResponse(status=401, url=url)

    client.ensure_session = _ensure_session  # type: ignore[method-assign]
    client._execute_request = _execute_request  # type: ignore[method-assign]
    client._last_conn_pool_log = float("inf")

    with pytest.raises(LinglongHTTPError) as exc_info:
        await client.fetch("GET", "http://example.com/api", format_type="text", max_retries=0)

    assert exc_info.value.status_code == 401
    assert exc_info.value.error_code == ErrorCode.USER_UNLOGIN
