from linglong_web.utils import (
    get_context_user_id,
    get_request_id,
    set_context_user_id,
    set_request_id,
)


def test_request_id_round_trip():
    """验证请求 ID 可写可读 / Ensure request id round-trips."""

    set_request_id("custom-req-id")
    assert get_request_id() == "custom-req-id"

    # 当传入 None 时会自动生成 / Auto-generate when None
    set_request_id(None)
    generated = get_request_id()
    assert generated.startswith("20")  # 时间戳前缀 / timestamp prefix guard


def test_context_user_id_helpers():
    """检查上下文用户 ID 读写能力 / Verify user id context helpers."""

    set_context_user_id(42)
    assert get_context_user_id() == 42

    set_context_user_id(None)
    assert get_context_user_id() is None
