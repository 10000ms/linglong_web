"""Linglong Web 错误定义 / Error definitions."""

import http
from enum import StrEnum
from typing import Optional


class ErrorCode(StrEnum):
    """通用错误编码 / Generic error codes."""

    SUCCESS = "0"
    INVALID_PARAM = "4000"
    USER_UNLOGIN = "4001"
    HANDLER_NOT_FOUND = "4004"
    SYSTEM_ERROR = "5000"
    NETWORK_ERROR = "5100"

    @classmethod
    def http_status_to_error_code(cls, status_code: int) -> "ErrorCode":
        """根据 HTTP 状态映射错误编码 / Map HTTP status to error code."""

        mapping = {
            http.HTTPStatus.OK.value: cls.SUCCESS,
            http.HTTPStatus.BAD_REQUEST.value: cls.INVALID_PARAM,
            http.HTTPStatus.UNAUTHORIZED.value: cls.USER_UNLOGIN,
            http.HTTPStatus.NOT_FOUND.value: cls.HANDLER_NOT_FOUND,
            http.HTTPStatus.INTERNAL_SERVER_ERROR.value: cls.SYSTEM_ERROR,
            http.HTTPStatus.GATEWAY_TIMEOUT.value: cls.NETWORK_ERROR,
        }
        return mapping.get(status_code, cls.SYSTEM_ERROR)


class ErrorMsg(StrEnum):
    """错误消息常量 / Error message constants."""

    SUCCESS = "success"
    COMMON_ERROR = "system error"
    INVALID_PARAM = "invalid request"
    USER_UNLOGIN = "user not login"
    HANDLER_NOT_FOUND = "resource not found"
    NETWORK_ERROR = "network error"

    @classmethod
    def get_msg(cls, code: str | int | None) -> str:
        """根据错误码获取描述 / Resolve message from error code."""

        if code is None or code == "":
            return cls.SUCCESS
        if isinstance(code, int):
            code = str(code)
        mapping = {
            ErrorCode.SUCCESS: cls.SUCCESS,
            ErrorCode.INVALID_PARAM: cls.INVALID_PARAM,
            ErrorCode.USER_UNLOGIN: cls.USER_UNLOGIN,
            ErrorCode.HANDLER_NOT_FOUND: cls.HANDLER_NOT_FOUND,
            ErrorCode.NETWORK_ERROR: cls.NETWORK_ERROR,
        }
        if code in mapping:
            return mapping[code]
        if code.isdigit() and int(code) in http.HTTPStatus:
            return http.HTTPStatus(int(code)).phrase
        return cls.COMMON_ERROR


class LinglongHTTPException(Exception):
    """Linglong Web HTTP 异常基类 / TableBase HTTP error for Linglong Web."""

    def __init__(
            self,
            status_code: int = http.HTTPStatus.INTERNAL_SERVER_ERROR.value,
            error_code: str = ErrorCode.SYSTEM_ERROR,
            message: Optional[str] = None,
            detail: Optional[str] = None,
    ) -> None:
        super().__init__(message or detail or "Linglong HTTP exception")
        self.status_code = status_code
        self.error_code = error_code
        self.message = message or ErrorMsg.get_msg(error_code)
        self.detail = detail or message or self.message

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"LinglongHTTPException(status_code={self.status_code}, "
            f"error_code={self.error_code}, message={self.message}, detail={self.detail})"
        )


class LoginRequiredError(LinglongHTTPException):
    """登录态缺失异常 / Raised when user authentication is missing."""

    def __init__(self, message: Optional[str] = None) -> None:
        super().__init__(
            status_code=http.HTTPStatus.UNAUTHORIZED.value,
            error_code=ErrorCode.USER_UNLOGIN,
            message=message or ErrorMsg.USER_UNLOGIN,
        )


class LimiterError(LinglongHTTPException):
    """限流异常 / Rate limit exceeded error."""

    def __init__(self, message: Optional[str] = None) -> None:
        super().__init__(
            status_code=http.HTTPStatus.TOO_MANY_REQUESTS.value,
            error_code=ErrorCode.SYSTEM_ERROR,
            message=message or ErrorMsg.NETWORK_ERROR,
        )


class ClusterLockError(LinglongHTTPException):
    """集群锁冲突异常 / Raised when a distributed lock cannot be acquired."""

    def __init__(self, message: Optional[str] = None) -> None:
        super().__init__(
            status_code=http.HTTPStatus.CONFLICT.value,
            error_code=ErrorCode.SYSTEM_ERROR,
            message=message or "Resource is locked by another worker",
        )
