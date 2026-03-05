import pytest
from aioclock import Every

from linglong_web import BaseScheduler
from linglong_web import to_group
from linglong_web.core.scheduler import _wrap_task


@pytest.mark.asyncio
async def test_base_scheduler_wraps_function():
    calls = []

    async def _task():
        calls.append("ok")

    scheduler = BaseScheduler("demo", Every(seconds=1, first_run_strategy="wait"), _task)
    await scheduler.func()
    assert calls == ["ok"]


def test_to_group_accepts_base_scheduler_instances():
    async def _noop():
        return None

    scheduler = BaseScheduler("noop", Every(seconds=1, first_run_strategy="wait"), _noop)
    group = to_group([scheduler])
    assert group is not None


@pytest.mark.asyncio
async def test_wrap_task_swallows_exceptions_and_does_not_raise():
    """任务异常应被包装层吞掉并记录，避免调度器中断。
    Wrapped task exceptions should be swallowed to avoid scheduler crash.
    """

    async def _boom():
        raise RuntimeError("boom")

    wrapped = _wrap_task("boom-task", _boom)
    await wrapped()


@pytest.mark.asyncio
async def test_wrap_task_resets_request_id_before_each_run(monkeypatch):
    """每次调度执行前都应重置 reqid，避免跨任务污染。
    Request id should be reset before each task run to avoid context leakage.
    """

    reset_calls = []
    monkeypatch.setattr("linglong_web.core.scheduler.set_request_id", lambda value: reset_calls.append(value))

    async def _ok():
        return None

    wrapped = _wrap_task("ok-task", _ok)
    await wrapped()

    assert reset_calls and reset_calls[0] is None
