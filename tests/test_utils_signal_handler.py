import asyncio
import signal

import pytest

from linglong_web.utils import (
    ServiceGracefulShutdown,
    SignalHandler,
)


@pytest.mark.asyncio
async def test_signal_handler_executes_callbacks():
    """验证收到信号后会执行回调 / Ensure callbacks run after handling a signal."""

    handler = SignalHandler(shutdown_timeout=1)
    flag = {"called": False}

    async def _callback():
        flag["called"] = True

    handler.add_shutdown_callback(_callback)
    handler._handle_signal(signal.SIGTERM.value, None)
    await asyncio.sleep(0.05)

    assert flag["called"] is True


@pytest.mark.asyncio
async def test_service_graceful_shutdown_runs_cleanup(monkeypatch):
    """验证资源清理函数会在 shutdown 阶段执行 / Cleanup callbacks run during shutdown."""

    monkeypatch.setattr("linglong_web.utils.signal_handler.signal.signal", lambda *args, **kwargs: None)
    manager = ServiceGracefulShutdown(service_name="demo", shutdown_timeout=1)
    flag = {"clean": False}

    async def _cleanup():
        flag["clean"] = True

    manager.add_cleanup_resource(_cleanup)
    await manager.initialize()
    await manager.shutdown()

    assert flag["clean"] is True


@pytest.mark.asyncio
async def test_signal_handler_ignores_duplicate_signals():
    """验证重复信号被忽略."""
    handler = SignalHandler(shutdown_timeout=1)

    handler._handle_signal(signal.SIGTERM.value, None)
    first_shutdown = handler._is_shutting_down

    handler._handle_signal(signal.SIGTERM.value, None)
    second_shutdown = handler._is_shutting_down

    assert first_shutdown is True
    assert second_shutdown is True


@pytest.mark.asyncio
async def test_signal_handler_tracks_received_signals():
    """验证信号被记录."""
    handler = SignalHandler(shutdown_timeout=1)

    handler._handle_signal(signal.SIGTERM.value, None)
    handler._handle_signal(signal.SIGINT.value, None)

    signals = handler.get_signals_received()
    assert signal.SIGTERM in signals
    assert signal.SIGINT in signals


@pytest.mark.asyncio
async def test_signal_handler_remove_callback():
    """验证可以移除回调."""
    handler = SignalHandler(shutdown_timeout=1)

    async def _callback():
        pass

    handler.add_shutdown_callback(_callback)
    assert len(handler._shutdown_callbacks) == 1

    handler.remove_shutdown_callback(_callback)
    assert len(handler._shutdown_callbacks) == 0


@pytest.mark.asyncio
async def test_signal_handler_wait_for_shutdown_with_timeout():
    """验证等待关闭超时."""
    handler = SignalHandler(shutdown_timeout=1)

    result = await handler.wait_for_shutdown(timeout=0.1)
    assert result is False


@pytest.mark.asyncio
async def test_signal_handler_wait_for_shutdown_completes():
    """验证等待关闭完成."""
    handler = SignalHandler(shutdown_timeout=1)

    async def _trigger():
        await asyncio.sleep(0.05)
        handler._shutdown_event.set()

    asyncio.create_task(_trigger())
    result = await handler.wait_for_shutdown(timeout=1.0)

    assert result is True


def test_signal_handler_get_shutdown_elapsed_time():
    """验证关闭耗时计算."""
    handler = SignalHandler(shutdown_timeout=30)
    assert handler.get_shutdown_elapsed_time() == 0.0


def test_signal_handler_get_remaining_shutdown_time():
    """验证剩余关闭时间计算."""
    handler = SignalHandler(shutdown_timeout=30)
    remaining = handler.get_remaining_shutdown_time()
    assert remaining == 30


@pytest.mark.asyncio
async def test_signal_handler_is_shutting_down():
    """验证关闭状态查询."""
    handler = SignalHandler(shutdown_timeout=1)
    assert handler.is_shutting_down() is False

    handler._handle_signal(signal.SIGTERM.value, None)
    await asyncio.sleep(0.05)

    assert handler.is_shutting_down() is True


@pytest.mark.asyncio
async def test_signal_handler_force_shutdown_if_needed_does_nothing_when_not_shutting_down():
    """验证未关闭时不强制退出."""
    handler = SignalHandler(shutdown_timeout=1)
    await handler.force_shutdown_if_needed()


@pytest.mark.asyncio
async def test_signal_handler_create_graceful_shutdown_task():
    """验证创建优雅关闭任务."""
    handler = SignalHandler(shutdown_timeout=1)

    async def _coro():
        return "done"

    task = handler.create_graceful_shutdown_task(_coro())
    assert isinstance(task, asyncio.Task)


@pytest.mark.asyncio
async def test_signal_handler_safe_execute_callback_handles_exception():
    """验证安全执行回调时处理异常."""
    handler = SignalHandler(shutdown_timeout=1)

    async def _callback():
        raise ValueError("test error")

    await handler._safe_execute_callback(_callback)


@pytest.mark.asyncio
async def test_signal_handler_safe_execute_callback_sync_function():
    """验证安全执行同步回调."""
    handler = SignalHandler(shutdown_timeout=1)
    flag = {"called": False}

    def _callback():
        flag["called"] = True

    await handler._safe_execute_callback(_callback)
    assert flag["called"] is True


def test_signal_handler_install_signal_handlers_idempotent():
    """验证重复安装信号处理器是幂等的."""
    handler = SignalHandler(shutdown_timeout=1)

    handler.install_signal_handlers()
    handler.install_signal_handlers()

    assert handler._signal_handlers_installed is True


def test_signal_handler_restore_signal_handlers():
    """验证恢复信号处理器."""
    handler = SignalHandler(shutdown_timeout=1)

    handler.install_signal_handlers()
    handler.restore_signal_handlers()

    assert handler._signal_handlers_installed is False


@pytest.mark.asyncio
async def test_service_graceful_shutdown_add_cleanup_resource():
    """验证添加清理资源."""
    manager = ServiceGracefulShutdown(service_name="demo", shutdown_timeout=1)

    async def _cleanup():
        pass

    manager.add_cleanup_resource(_cleanup)
    assert len(manager._cleanup_resources) == 1


@pytest.mark.asyncio
async def test_service_graceful_shutdown_add_shutdown_task():
    """验证添加关闭任务."""
    manager = ServiceGracefulShutdown(service_name="demo", shutdown_timeout=1)

    async def _coro():
        return "done"

    task = manager.add_shutdown_task(_coro())
    assert isinstance(task, asyncio.Task)


@pytest.mark.asyncio
async def test_service_graceful_shutdown_wait_for_shutdown_signal():
    """验证等待关闭信号."""
    manager = ServiceGracefulShutdown(service_name="demo", shutdown_timeout=1)

    async def _trigger():
        await asyncio.sleep(0.05)
        manager.signal_handler._shutdown_event.set()

    asyncio.create_task(_trigger())
    result = await manager.wait_for_shutdown_signal(timeout=1.0)

    assert result is True


@pytest.mark.asyncio
async def test_service_graceful_shutdown_is_shutting_down():
    """验证服务关闭状态."""
    manager = ServiceGracefulShutdown(service_name="demo", shutdown_timeout=1)

    assert manager.is_shutting_down() is False

    manager.signal_handler._is_shutting_down = True

    assert manager.is_shutting_down() is True


@pytest.mark.asyncio
async def test_service_graceful_shutdown_get_remaining_shutdown_time():
    """验证获取剩余关闭时间."""
    manager = ServiceGracefulShutdown(service_name="demo", shutdown_timeout=30)

    remaining = manager.get_remaining_shutdown_time()
    assert remaining == 30
