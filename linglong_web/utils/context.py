"""请求上下文管理 / Request-scoped context helpers."""

from contextvars import ContextVar
from datetime import datetime
from typing import Optional
import sys

from nanoid import generate

from .time import ServerTargetTZ

_request_id: ContextVar[str] = ContextVar(
    "Linglong-Request-ID",
)
_context_user_id: ContextVar[Optional[int]] = ContextVar(
    "linglong_user_id",
    default=None,
)


def set_request_id(request_id: Optional[str]) -> None:
    """设置/刷新请求 ID；为空时自动生成 / Set or refresh request id, auto-generate when missing."""

    if request_id:
        _request_id.set(request_id)
        return

    local_now = datetime.now(tz=ServerTargetTZ)
    formatted = local_now.strftime('%Y%m%d-%H%M%S')
    generated = f"{formatted}-{generate(size=8)}"
    _request_id.set(generated)


def get_request_id() -> str:
    """获取当前请求 ID（若为空则即时生成）/ Retrieve current request id, auto-generate if absent."""

    try:
        if sys.meta_path is None:
            return "default-oid"  # pragma: no cover - interpreter shutting down
        return _request_id.get()
    except LookupError:  # pragma: no cover - defensive fallback
        set_request_id(None)
        return _request_id.get()


def set_context_user_id(user_id: Optional[int]) -> None:
    """写入登录用户 ID（None 表示匿名）/ Attach current user id; None marks anonymous."""

    _context_user_id.set(user_id)


def get_context_user_id() -> Optional[int]:
    """获取上下文中的用户 ID / Fetch contextual user id."""

    try:
        return _context_user_id.get()
    except LookupError:
        return None
