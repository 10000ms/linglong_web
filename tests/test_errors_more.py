import http

from linglong_web.core.errors import (
    ClusterLockError,
    ErrorCode,
    ErrorMsg,
)


def test_http_status_to_error_code_defaults_to_system_error() -> None:
    assert ErrorCode.http_status_to_error_code(418) == ErrorCode.SYSTEM_ERROR


def test_http_status_to_error_code_gateway_timeout_maps_to_network_error() -> None:
    assert ErrorCode.http_status_to_error_code(http.HTTPStatus.GATEWAY_TIMEOUT.value) == ErrorCode.NETWORK_ERROR


def test_error_msg_accepts_http_status_digit_phrase() -> None:
    assert ErrorMsg.get_msg(500) == http.HTTPStatus.INTERNAL_SERVER_ERROR.phrase


def test_error_msg_unknown_string_falls_back_to_common_error() -> None:
    assert ErrorMsg.get_msg("not-a-code") == ErrorMsg.COMMON_ERROR


def test_error_msg_none_returns_success() -> None:
    assert ErrorMsg.get_msg(None) == ErrorMsg.SUCCESS


def test_cluster_lock_error_defaults() -> None:
    err = ClusterLockError()
    assert err.status_code == http.HTTPStatus.CONFLICT.value
    assert err.error_code == ErrorCode.SYSTEM_ERROR
