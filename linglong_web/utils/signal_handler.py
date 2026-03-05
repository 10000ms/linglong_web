"""Linglong Web 信号处理原语 / Enhanced signal handling primitives for Linglong Web."""
import asyncio
import signal
import os
import traceback
from typing import (
    Dict,
    Any,
    Optional,
    List,
    Callable,
)
from datetime import datetime

from .log import logger


class SignalHandler:
    def __init__(self, shutdown_timeout: int = 30):
        self._shutdown_timeout = shutdown_timeout
        self._shutdown_event = asyncio.Event()
        self._shutdown_start_time: Optional[datetime] = None
        self._shutdown_callbacks: List[Callable] = []
        self._is_shutting_down = False
        self._signal_handlers_installed = False
        self._original_handlers: Dict[int, Any] = {}
        self._signals_received: List[signal.Signals] = []

    def install_signal_handlers(self):
        if self._signal_handlers_installed:
            logger.warning("Signal handlers already installed")
            return

        for sig in [signal.SIGTERM, signal.SIGINT, signal.SIGQUIT]:
            self._original_handlers[sig] = signal.signal(sig, self._handle_signal)

        self._signal_handlers_installed = True
        logger.info("Enhanced signal handlers installed")

    def restore_signal_handlers(self):
        if not self._signal_handlers_installed:
            return

        for sig, handler in self._original_handlers.items():
            try:
                signal.signal(sig, handler)
            except (OSError, ValueError) as exc:
                logger.warning("Failed to restore handler for signal %s: %s", sig, exc)

        self._signal_handlers_installed = False
        logger.info("Original signal handlers restored")

    def _handle_signal(self, signum: int, frame):  # noqa: ARG002
        sig_name = signal.Signals(signum).name
        logger.info("Received signal: %s (%s)", sig_name, signum)

        self._signals_received.append(signal.Signals(signum))

        if self._is_shutting_down:
            logger.info("Ignoring signal %s, already shutting down", sig_name)
            return

        if not self._shutdown_event.is_set():
            self._shutdown_event.set()
            self._shutdown_start_time = datetime.now()
            self._is_shutting_down = True
            asyncio.create_task(self._execute_shutdown_callbacks())

    async def _execute_shutdown_callbacks(self):
        logger.info("Executing shutdown callbacks")

        if self._shutdown_callbacks:
            tasks = [asyncio.create_task(self._safe_execute_callback(cb)) for cb in self._shutdown_callbacks]
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=self._shutdown_timeout)
            except asyncio.TimeoutError:
                logger.warning("Shutdown callbacks timed out after %ss", self._shutdown_timeout)

        logger.info("Shutdown callbacks completed")

    async def _safe_execute_callback(self, callback: Callable):
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback()
            else:
                callback()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Error in shutdown callback: %s", exc)

    def add_shutdown_callback(self, callback: Callable[[], Any]) -> None:
        self._shutdown_callbacks.append(callback)
        logger.info("Added shutdown callback: %s", callback.__name__)

    def remove_shutdown_callback(self, callback: Callable[[], Any]) -> None:
        if callback in self._shutdown_callbacks:
            self._shutdown_callbacks.remove(callback)
            logger.info("Removed shutdown callback: %s", callback.__name__)

    async def wait_for_shutdown(self, timeout: Optional[float] = None) -> bool:
        try:
            if timeout:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=timeout)
            else:
                await self._shutdown_event.wait()
            return True
        except asyncio.TimeoutError:
            return False

    def is_shutting_down(self) -> bool:
        return self._is_shutting_down

    def get_shutdown_elapsed_time(self) -> float:
        if not self._shutdown_start_time:
            return 0.0
        return (datetime.now() - self._shutdown_start_time).total_seconds()

    def get_signals_received(self) -> List[signal.Signals]:
        return self._signals_received.copy()

    def get_remaining_shutdown_time(self) -> float:
        if not self._shutdown_start_time:
            return self._shutdown_timeout
        elapsed = self.get_shutdown_elapsed_time()
        remaining = self._shutdown_timeout - elapsed
        return max(0, remaining)

    async def force_shutdown_if_needed(self):
        if not self._is_shutting_down:
            return

        remaining = self.get_remaining_shutdown_time()
        if remaining <= 0:
            logger.warning("Shutdown timeout reached, forcing exit")
            os._exit(1)

    def create_graceful_shutdown_task(self, coro: Any, timeout: Optional[float] = None) -> asyncio.Task:
        async def wrapper():
            try:
                task_timeout = timeout if timeout is not None else self.get_remaining_shutdown_time()
                if self._is_shutting_down and task_timeout > self.get_remaining_shutdown_time():
                    task_timeout = self.get_remaining_shutdown_time()

                if task_timeout > 0:
                    return await asyncio.wait_for(coro, timeout=task_timeout)
                logger.warning("Skipping task due to shutdown timeout")
                return None
            except asyncio.TimeoutError:
                logger.warning("Task timed out during shutdown: %s", coro)
                return None

        return asyncio.create_task(wrapper())


class ServiceGracefulShutdown:
    def __init__(self, service_name: str, shutdown_timeout: int = 30):
        self.service_name = service_name
        self.signal_handler = SignalHandler(shutdown_timeout)
        self._shutdown_tasks: List[asyncio.Task] = []
        self._cleanup_resources: List[Callable] = []

    async def initialize(self):
        self.signal_handler.install_signal_handlers()
        self.signal_handler.add_shutdown_callback(self._on_shutdown_start)
        self.signal_handler.add_shutdown_callback(self._cleanup_resources_callback)
        logger.info("ServiceGracefulShutdown initialized for %s", self.service_name)

    async def shutdown(self):
        logger.info("Starting graceful shutdown for %s", self.service_name)
        signals = self.signal_handler.get_signals_received()
        if not signals:
            stack_info = "".join(traceback.format_stack(limit=8))
            logger.warning(
                "Shutdown triggered without receiving OS signal for %s. Call stack:\n%s",
                self.service_name,
                stack_info,
            )
        if not self.signal_handler._shutdown_event.is_set():
            self.signal_handler._shutdown_event.set()
            self.signal_handler._shutdown_start_time = datetime.now()
            self.signal_handler._is_shutting_down = True

        await self.signal_handler._execute_shutdown_callbacks()

        if self._shutdown_tasks:
            logger.info("Waiting for %d shutdown tasks", len(self._shutdown_tasks))
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._shutdown_tasks, return_exceptions=True),
                    timeout=self.signal_handler.get_remaining_shutdown_time(),
                )
            except asyncio.TimeoutError:
                logger.warning("Shutdown tasks timed out")

        self.signal_handler.restore_signal_handlers()
        logger.info("Graceful shutdown completed for %s", self.service_name)

    async def _on_shutdown_start(self):
        logger.info("Shutdown started for %s", self.service_name)

    async def _cleanup_resources_callback(self):
        logger.info("Cleaning up resources for %s", self.service_name)
        for cleanup_func in self._cleanup_resources:
            try:
                if asyncio.iscoroutinefunction(cleanup_func):
                    await cleanup_func()
                else:
                    cleanup_func()
            except Exception as exc:  # pragma: no cover
                logger.error("Error in cleanup function: %s", exc)

    def add_cleanup_resource(self, cleanup_func: Callable[[], Any]) -> None:
        self._cleanup_resources.append(cleanup_func)

    def add_shutdown_task(self, coro: Any, timeout: Optional[float] = None) -> asyncio.Task:
        task = self.signal_handler.create_graceful_shutdown_task(coro, timeout)
        self._shutdown_tasks.append(task)
        return task

    async def wait_for_shutdown_signal(self, timeout: Optional[float] = None) -> bool:
        return await self.signal_handler.wait_for_shutdown(timeout)

    def is_shutting_down(self) -> bool:
        return self.signal_handler.is_shutting_down()

    def get_remaining_shutdown_time(self) -> float:
        return self.signal_handler.get_remaining_shutdown_time()
