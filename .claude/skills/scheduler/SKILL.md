---
name: scheduler
description: 调度器开发指南。说明如何开发与扩展 aioclock 调度功能、定时任务等。
---

# Scheduler 开发指南

本指南说明如何开发与扩展 Scheduler 模块。Scheduler 模块负责定时任务的注册、管理和执行。

## 架构概述

```
SchedulerModule
├── SchedulerGroup (aioclock Group 封装)
├── 定时任务注册
├── 任务生命周期管理
└── 异常捕获与日志
```

## 常用操作

### 1. 添加新的调度模式

#### 步骤 1：在 scheduler.py 中添加调度方法

```python
class SchedulerGroup:
    """调度器组 / Scheduler group."""

    def add_task(
        self,
        trigger: Trigger,
        func: Callable,
        name: str | None = None
    ) -> None:
        """
        添加定时任务 / Add scheduled task
        
        参数:
            trigger: 触发器 / Trigger (e.g., IntervalTrigger, CronTrigger)
            func: 任务函数 / Task function
            name: 任务名称 / Task name
        """
        pass
```

### 2. 添加新的触发器类型

#### 步骤 1：实现自定义触发器

```python
class CustomTrigger(Trigger):
    """自定义触发器 / Custom trigger."""

    def __init__(self, interval: int):
        """
        初始化触发器 / Initialize trigger
        
        参数:
            interval: 间隔时间（秒）/ Interval in seconds
        """
        self.interval = interval

    async def next(self) -> datetime | None:
        """
        获取下次触发时间 / Get next trigger time
        
        返回:
            下次触发时间 / Next trigger time
        """
        pass
```

### 3. 添加任务包装器

#### 步骤 1：实现任务包装

```python
def wrap_task(
    func: Callable,
    name: str | None = None,
    log_errors: bool = True
) -> Callable:
    """
    包装任务函数 / Wrap task function
    
    参数:
        func: 原始任务函数 / Original task function
        name: 任务名称 / Task name
        log_errors: 是否记录错误 / Whether to log errors
        
    返回:
        包装后的任务函数 / Wrapped task function
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if log_errors:
                logger.exception("Task %s failed: %s", name, e)
            raise
    return wrapper
```

## 相关文档

- [IntervalTrigger 用法](reference/interval-trigger.md)
- [CronTrigger 用法](reference/cron-trigger.md)
- [任务错误处理](reference/error-handling.md)
