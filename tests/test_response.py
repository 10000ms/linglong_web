import pytest

from linglong_web import (
    APIError,
    APIResponse,
    build_api_response,
    build_error_response,
    build_success_response,
)


def test_api_response_success():
    resp = APIResponse.success_resp(data={"foo": "bar"})
    assert resp.success is True
    assert resp.data == {"foo": "bar"}
    assert resp.error.code == "0"


def test_api_response_error():
    resp = APIResponse.error_resp(code="4000", msg="invalid")
    assert resp.success is False
    assert resp.error.code == "4000"
    assert resp.error.msg == "invalid"


def test_build_api_response():
    resp = build_api_response(data=123)
    assert isinstance(resp, APIResponse)
    assert resp.data == 123


def test_build_success_response():
    resp = build_success_response(data="ok")
    assert resp.success is True
    assert resp.data == "ok"


def test_build_error_response():
    resp = build_error_response(code="5000", msg="error")
    assert resp.success is False
    assert resp.error.code == "5000"


def test_api_error_default():
    err = APIError()
    assert err.code == "0"
    assert err.msg == ""
