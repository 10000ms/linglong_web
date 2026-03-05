---
name: http-decorators
description: HTTP 装饰器开发指南。说明如何开发与扩展 cacher、limiter、cluster_lock 等装饰器。
---

# HTTP 装饰器开发指南

本指南说明如何开发与扩展 HTTP 装饰器模块。包括缓存、限流、分布式锁等功能。

## 架构概述

```
HTTP 装饰器模块
├── cacher      # 缓存装饰器
├── limiter     # 限流装饰器
├── limiter_local  # 本地限流装饰器
└── cluster_lock  # 分布式锁装饰器
```

## 常用操作

### 1. 添加新的缓存策略

#### 步骤 1：在 cacher.py 中添加缓存方法

```python
async def cacher(
    key: str,
    expire: int = 300,
    prefix: str = "default"
) -> Callable:
    """
    缓存装饰器 / Cache decorator
    
    参数:
        key: 缓存键 / Cache key
        expire: 过期时间（秒）/ Expire time in seconds
        prefix: 键前缀 / Key prefix
        
    返回:
        装饰器函数 / Decorator function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 缓存逻辑
            pass
        return wrapper
    return decorator
```

### 2. 添加新的限流策略

#### 步骤 1：在 limiter.py 中添加限流方法

```python
async def limiter(
    key: str,
    rate: str = "10/minute",
    block: bool = False
) -> Callable:
    """
    限流装饰器 / Rate limit decorator
    
    参数:
        key: 限流键 / Rate limit key
        rate: 限流速率 / Rate limit (e.g., "10/minute")
        block: 是否阻塞 / Whether to block
        
    返回:
        装饰器函数 / Decorator function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 限流逻辑
            pass
        return wrapper
    return decorator
```

### 3. 添加新的锁策略

#### 步骤 1：在 cluster_lock.py 中添加锁方法

```python
async def cluster_lock(
    key: str,
    timeout: float = 10.0,
    retry_interval: float = 0.1
) -> Callable:
    """
    分布式锁装饰器 / Distributed lock decorator
    
    参数:
        key: 锁键 / Lock key
        timeout: 超时时间（秒）/ Timeout in seconds
        retry_interval: 重试间隔（秒）/ Retry interval in seconds
        
    返回:
        装饰器函数 / Decorator function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 锁逻辑
            pass
        return wrapper
    return decorator
```

## 相关文档

- [缓存策略](reference/cache-strategies.md)
- [限流配置](reference/rate-limiting.md)
- [分布式锁实现](reference/distributed-lock.md)
