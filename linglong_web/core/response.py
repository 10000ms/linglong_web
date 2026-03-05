"""Linglong Web API 响应模型 / Response helpers."""

from typing import (
    Generic,
    Optional,
)

from pydantic import (
    BaseModel,
    Field,
)

from .types import T


class APIError(BaseModel):
    """API 错误模型 / API error payload."""

    code: str = Field(default="0", description="错误编码 / Error code")
    msg: str = Field(default="", description="错误信息 / Error message")


class APIResponse(BaseModel, Generic[T]):
    """API 统一响应结构 / Unified API response envelope."""

    success: bool = Field(..., description="是否成功 / Whether request succeeded")
    error: APIError = Field(default_factory=APIError, description="错误详情 / Error details")
    data: Optional[T] = Field(default=None, description="响应数据 / Response payload")

    @classmethod
    def create(
            cls,
            data: Optional[T] = None,
            code: str = "0",
            msg: str = "",
            error: Optional[APIError] = None,
            success: Optional[bool] = None,
    ) -> "APIResponse[Optional[T]]":
        """构建响应对象 / Build a response object."""

        resolved_error = error or APIError(code=str(code), msg=str(msg))
        resolved_success = success if success is not None else resolved_error.code == "0"
        return cls(success=resolved_success, error=resolved_error, data=data)

    @classmethod
    def success_resp(cls, data: Optional[T] = None) -> "APIResponse[Optional[T]]":
        """快速构建成功响应 / Build success response."""

        return cls.create(data=data, code="0", msg="", success=True)

    @classmethod
    def error_resp(cls, code: str, msg: str) -> "APIResponse[Optional[T]]":
        """快速构建失败响应 / Build error response."""

        return cls.create(data=None, code=code, msg=msg, success=False)


class MessageResp(BaseModel):
    """通用消息响应 / Generic message response."""

    message: str = Field(..., description="消息内容 / Message content")


class ErrorMessage(BaseModel):
    """错误消息响应 / Error message payload."""

    message: str = Field(..., description="错误描述 / Error message")
    detail: Optional[str] = Field(default=None, description="错误详情 / Error detail")


def build_api_response(*args, **kwargs) -> APIResponse:
    """APIResponse 工厂函数 / APIResponse factory."""

    return APIResponse.create(*args, **kwargs)


def build_success_response(data=None) -> APIResponse:
    """成功响应构造器 / Success response helper."""

    return APIResponse.success_resp(data=data)


def build_error_response(code: str, msg: str) -> APIResponse:
    """错误响应构造器 / Error response helper."""

    return APIResponse.error_resp(code=code, msg=msg)
