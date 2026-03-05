"""Linglong Web 调度器封装 / Scheduler helpers."""
import time
from typing import (
    Awaitable,
    Callable,
    List,
)

from aioclock.group import Group
from aioclock.triggers import BaseTrigger

from ..utils.context import set_request_id
from ..utils.log import logger


def _wrap_task(name: str, func: Callable[[], Awaitable]) -> Callable[[], Awaitable]:
    async def wrapper():
        set_request_id(None)
        start_time_nano = time.time_ns()
        logger.info("aioclock executing task: %s", name)
        try:
            await func()
        except BaseException as exc:  # pragma: no cover - defensive logging
            logger.error("scheduler task: %s failed: %s", name, exc, exc_info=True)
        elapsed = (time.time_ns() - start_time_nano) / 1e6
        logger.info("scheduler task: %s executed, cost: <%.2f> ms", name, elapsed)
        return None

    return wrapper


class BaseScheduler:
    """调度器描述符 / Scheduler descriptor."""

    def __init__(self, name: str, trigger: BaseTrigger, func: Callable[[], Awaitable]):
        self.name = name
        self.trigger = trigger
        self.func = _wrap_task(name, func)

    def as_tuple(self) -> tuple[str, BaseTrigger, Callable[[], Awaitable]]:
        """转换为三元组 / Convert to tuple for downstream helpers."""

        return self.name, self.trigger, self.func


class SchedulerGroup:
    """调度器组合 / Task group builder."""

    def __init__(self) -> None:
        self.group = Group()

    def register(self, name: str, trigger: BaseTrigger, func: Callable[[], Awaitable]) -> None:
        wrapped = _wrap_task(name, func)
        self.group.task(trigger=trigger)(wrapped)

    def include(self, schedulers: List[tuple[str, BaseTrigger, Callable[[], Awaitable]]]) -> Group:
        for name, trigger, func in schedulers:
            self.register(name, trigger, func)
        return self.group

    def get_group(self) -> Group:
        return self.group


def to_group(
        schedulers: List[BaseScheduler | tuple[str, BaseTrigger, Callable[[], Awaitable]]],
) -> Group:
    """构造 Group / Build a Group from schedulers."""

    group = Group()
    for scheduler in schedulers:
        if isinstance(scheduler, BaseScheduler):
            name, trigger, func = scheduler.as_tuple()
        else:
            name, trigger, func = scheduler
        wrapped = _wrap_task(name, func)
        group.task(trigger=trigger)(wrapped)
    return group
