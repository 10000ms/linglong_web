import threading
import asyncio
from contextlib import (
    contextmanager,
    asynccontextmanager,
)
from typing import (
    AsyncGenerator,
    Generator,
)


class AsyncReadWriteLock:
    """
    一个在线程级别上对协程友好的读写锁 / An asyncio-friendly, thread-safe read-write lock.

    - Multiple readers can hold the lock concurrently when no writer is waiting.
    - Writers have priority to prevent starvation.
    - Write locks are reentrant for the owning thread.
    - Provides sync/async context managers to ensure timely release.
    """

    def __init__(self):
        self._main_lock = threading.Lock()
        self._condition = threading.Condition(self._main_lock)
        self._num_readers = 0
        self._num_writers_waiting = 0
        self._writer_thread = None
        self._write_recursion_depth = 0

    def acquire_read(self):
        with self._main_lock:
            while self._num_writers_waiting > 0 or self._writer_thread is not None:
                self._condition.wait()
            self._num_readers += 1

    def release_read(self):
        with self._main_lock:
            if self._num_readers == 0:
                raise RuntimeError("Cannot release a read lock that has not been acquired.")
            self._num_readers -= 1
            if self._num_readers == 0:
                self._condition.notify_all()

    def acquire_write(self):
        current_thread = threading.current_thread()
        with self._main_lock:
            if self._writer_thread is current_thread:
                self._write_recursion_depth += 1
                return

            self._num_writers_waiting += 1
            while self._num_readers > 0 or self._writer_thread is not None:
                self._condition.wait()

            self._num_writers_waiting -= 1
            self._writer_thread = current_thread
            self._write_recursion_depth = 1

    def release_write(self):
        current_thread = threading.current_thread()
        with self._main_lock:
            if self._writer_thread is not current_thread:
                raise RuntimeError("Cannot release a write lock that is not held by the current thread.")

            self._write_recursion_depth -= 1
            if self._write_recursion_depth == 0:
                self._writer_thread = None
                self._condition.notify_all()

    @contextmanager
    def read_locked(self) -> Generator[None, None, None]:
        try:
            self.acquire_read()
            yield
        finally:
            self.release_read()

    @contextmanager
    def write_locked(self) -> Generator[None, None, None]:
        try:
            self.acquire_write()
            yield
        finally:
            self.release_write()

    async def a_acquire_read(self):
        await asyncio.to_thread(self.acquire_read)

    async def a_release_read(self):
        await asyncio.to_thread(self.release_read)

    async def a_acquire_write(self):
        await asyncio.to_thread(self.acquire_write)

    async def a_release_write(self):
        await asyncio.to_thread(self.release_write)

    @asynccontextmanager
    async def a_read_locked(self) -> AsyncGenerator[None, None]:
        try:
            await self.a_acquire_read()
            yield
        finally:
            await self.a_release_read()

    @asynccontextmanager
    async def a_write_locked(self) -> AsyncGenerator[None, None]:
        try:
            await self.a_acquire_write()
            yield
        finally:
            await self.a_release_write()
