"""Linglong Web HTTP 客户端 / Async HTTP client."""
import asyncio
import functools
import time
from typing import (
    Any,
    Optional,
)
import http

import aiohttp
from yarl import URL

from .constants import LinglongConst
from .errors import (
    ErrorCode,
    ErrorMsg,
    LinglongHTTPException,
)
from ..utils.context import get_request_id
from ..utils.log import logger
from ..utils.pj_struct import Singleton


class HTTPClientConfig:
    """HTTP 客户端配置 / HTTP client tuning knobs."""

    DEFAULT_TIMEOUT = 60.0
    INTERNAL_SERVICE_TIMEOUT = 10.0
    DEFAULT_FORMAT = 'text'
    HAVING_MSG_STATUS_CODES = {401, 404}
    CONNECTION_POOL_LOG_INTERVAL = 10

    CONNECTION_POOL_SIZE = 100
    LIMIT_PER_HOST = 10
    SSL_VERIFICATION = False
    KEEPALIVE_TIMEOUT = 30


class LinglongHTTPError(LinglongHTTPException):
    """HTTP 调用失败异常 / HTTP invocation failure."""


class AsyncHTTPClient(Singleton):  # noqa: WPS338 - intentional Singleton
    """带请求ID注入的 aiohttp 客户端 / aiohttp client with request-id injection."""

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_conn_pool_log = 0.0

    async def graceful_close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _build_headers(self, existing: Optional[dict] = None) -> dict:
        headers = existing or {}
        headers.setdefault(LinglongConst.OID_HEADER_KEY, get_request_id())
        return headers

    def _get_connector_status(self, connector: aiohttp.BaseConnector | None) -> str:
        if connector is None:
            return "No connection pool"
        try:
            conns = connector._conns
            acquired = connector._acquired
            total_connections = sum(len(host_conns) for host_conns in conns.values())
            return (
                f"Total Connections: {total_connections}, "
                f"Acquired Connections: {acquired}, "
                f"Hosts: {list(conns.keys())}"
            )
        except AttributeError:  # pragma: no cover - aiohttp internals
            return "Connection pool status not available"

    def _generate_curl_command(self, url, method, headers, request_kwargs):
        from urllib.parse import urlparse, parse_qs, urlencode

        params = request_kwargs.get('params', {})
        parsed = urlparse(url)
        existing_params = parse_qs(parsed.query)
        for key, value in params.items():
            existing_params[key] = value
        new_query = urlencode(existing_params, doseq=True)
        curl_url = parsed._replace(query=new_query).geturl()

        curl_headers = ' '.join([f"-H '{k}: {v}'" for k, v in headers.items()])

        data = request_kwargs.get('data')
        json_data = request_kwargs.get('json')
        curl_data = ''
        if data is not None:
            escaped_data = str(data).replace("'", "'\\''")
            curl_data = f"-d '{escaped_data}'"
        elif json_data is not None:
            import json
            escaped_json = json.dumps(json_data).replace("'", "'\\''")
            curl_data = f"--json '{escaped_json}'"

        curl_parts = ['curl', f"-X {method.upper()}", curl_headers]
        if curl_data:
            curl_parts.append(curl_data)
        curl_parts.append(f"'{curl_url}'")

        return ' '.join(curl_parts)

    async def _execute_request(
            self,
            session: aiohttp.ClientSession,
            method: str,
            url: str,
            **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        current_time = time.monotonic()
        if current_time - self._last_conn_pool_log > HTTPClientConfig.CONNECTION_POOL_LOG_INTERVAL:
            logger.debug("Connection pool status: %s", self._get_connector_status(session.connector))
            self._last_conn_pool_log = current_time
        return await session.request(method, url, **kwargs)

    async def _parse_content(self, response: aiohttp.ClientResponse, fmt: str) -> aiohttp.ClientResponse:
        if fmt == 'text':
            response.text_data = await response.text()  # type: ignore[attr-defined]
        if fmt == 'json':
            response.json_data = await response.json(content_type=None)  # type: ignore[attr-defined]
        return response

    async def fetch(  # noqa: C901
            self,
            method: str,
            url: str,
            *,
            format_type: str = HTTPClientConfig.DEFAULT_FORMAT,
            timeout: float = HTTPClientConfig.DEFAULT_TIMEOUT,
            log_curl_command: bool = False,
            max_retries: int = 3,
            retry_delay: float = 1.0,
            retry_attempts: int = 0,
            passthrough_errors: bool = False,
            **kwargs: Any,
    ) -> aiohttp.ClientResponse | None:
        session = await self.ensure_session()
        request_kwargs = dict(kwargs)
        original_headers = request_kwargs.pop('headers', None)
        prepared_headers = self._build_headers(original_headers)

        if log_curl_command:
            logger.info(
                "请求: CURL Command: %s",
                self._generate_curl_command(url, method, prepared_headers, request_kwargs),
            )
        else:
            logger.info('请求: %s', url)

        last_exception = None

        while retry_attempts <= max_retries:
            try:
                start = time.monotonic()
                response = await self._execute_request(
                    session,
                    method.lower(),
                    url,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    headers=prepared_headers,
                    **request_kwargs,
                )

                result = await self._parse_content(response, format_type)
                elapsed = (time.monotonic() - start) * 1000

                logger.info(
                    "HTTP %s %s - %dms [%d] (Attempt: %d/%d)",
                    method.upper(),
                    url,
                    elapsed,
                    result.status,
                    retry_attempts + 1,
                    max_retries + 1,
                )

                if not passthrough_errors and 500 <= result.status < 600:
                    response_text = await result.text()
                    logger.warning(
                        "Server error (Attempt: %d/%d): HTTP %d %s://%s%s | Request Headers: %s | Response Headers: %s | Response Body: %.500s%s",
                        retry_attempts + 1,
                        max_retries + 1,
                        result.status,
                        result.url.scheme,
                        result.url.host,
                        result.url.path,
                        {k: v for k, v in result.request_info.headers.items() if
                         k.lower() not in {'authorization', 'cookie'}},
                        dict(result.headers),
                        response_text[:500],
                        " (truncated)" if len(response_text) > 500 else "",
                    )

                    result.release()

                    if retry_attempts < max_retries:
                        retry_attempts += 1
                        delay = retry_delay * (retry_attempts ** 0.5)
                        logger.info("Retrying in %.2f seconds...", delay)
                        await asyncio.sleep(delay)
                        continue
                    raise LinglongHTTPError(
                        status_code=result.status,
                        error_code=ErrorCode.SYSTEM_ERROR,
                        message=ErrorMsg.COMMON_ERROR,
                    )

                if (not passthrough_errors
                        and result.status in HTTPClientConfig.HAVING_MSG_STATUS_CODES):
                    error_code = ErrorCode.http_status_to_error_code(result.status)
                    raise LinglongHTTPError(
                        status_code=result.status,
                        error_code=error_code,
                        message=ErrorMsg.get_msg(error_code),
                    )

                return result

            except (asyncio.TimeoutError, aiohttp.ClientError, aiohttp.ServerTimeoutError) as exc:
                scheme, host, path = 'unknown', 'unknown', ''
                status: str | int = 'N/A'
                response_text = 'N/A'

                if hasattr(exc, 'request_info') and exc.request_info:
                    try:
                        scheme = exc.request_info.real_url.scheme
                        host = exc.request_info.real_url.host
                        path = exc.request_info.real_url.path
                    except Exception:  # pragma: no cover - defensive logging
                        pass

                if scheme == 'unknown' or host == 'unknown':
                    try:
                        u = URL(url) if isinstance(url, str) else url
                        scheme = getattr(u, 'scheme', scheme)
                        host = getattr(u, 'host', host)
                        path = getattr(u, 'path', path)
                    except Exception:  # pragma: no cover - defensive logging
                        pass

                if hasattr(exc, 'status') and exc.status is not None:
                    status = exc.status
                elif hasattr(exc, 'errno') and exc.errno is not None:
                    status = exc.errno

                if hasattr(exc, 'response') and exc.response:
                    try:
                        response_text = (await exc.response.text())[:500]
                    except Exception:  # pragma: no cover - defensive logging
                        response_text = '[Could not read response text]'

                logger.warning(
                    "Request failed (Attempt: %d/%d): %s %s://%s%s | Status: %s | Error: %s | Response: %.500s",
                    retry_attempts + 1,
                    max_retries + 1,
                    exc.__class__.__module__ + '.' + exc.__class__.__name__,
                    scheme,
                    host,
                    path,
                    status,
                    str(exc),
                    response_text,
                )
                last_exception = exc
                retry_attempts += 1

                if retry_attempts <= max_retries:
                    await asyncio.sleep(retry_delay)
                continue
            except LinglongHTTPException:
                raise
            except Exception as exc:
                raise LinglongHTTPError(
                    status_code=http.HTTPStatus.INTERNAL_SERVER_ERROR,
                    error_code=ErrorCode.SYSTEM_ERROR,
                    message=str(exc),
                ) from exc

        raise last_exception if last_exception else LinglongHTTPError()

    async def ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed or self._session._loop.is_closed():
            if self._session is not None:
                await self._session.close()
            connector = aiohttp.TCPConnector(
                limit=HTTPClientConfig.CONNECTION_POOL_SIZE,
                limit_per_host=HTTPClientConfig.LIMIT_PER_HOST,
                ssl=HTTPClientConfig.SSL_VERIFICATION,
                keepalive_timeout=HTTPClientConfig.KEEPALIVE_TIMEOUT,
            )
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    get = functools.partialmethod(fetch, http.HTTPMethod.GET.value)
    post = functools.partialmethod(fetch, http.HTTPMethod.POST.value)
    put = functools.partialmethod(fetch, http.HTTPMethod.PUT.value)
    delete = functools.partialmethod(fetch, http.HTTPMethod.DELETE.value)
    head = functools.partialmethod(fetch, http.HTTPMethod.HEAD.value)
    options = functools.partialmethod(fetch, http.HTTPMethod.OPTIONS.value)


http_client = AsyncHTTPClient()
