---
name: resource
description: 资源管理开发指南。说明如何开发与扩展 ResourceManager、数据库连接、缓存连接等功能。
---

# Resource 开发指南

本指南说明如何开发与扩展 Resource 模块。Resource 模块负责数据库、缓存、消息队列等资源的管理和生命周期。

## 架构概述

```
ResourceManager (资源管理器)
    ├── PostgreSQL 连接管理
    ├── Redis 连接管理
    ├── MongoDB 连接管理
    ├── RabbitMQ 连接管理
    ├── Celery 连接管理
    └── 统一初始化/关闭接口
```

## 常用操作

### 1. 添加新的资源类型

#### 步骤 1：在 ResourceManager 中添加资源初始化

在 `resource.py` 中添加新资源类型：

```python
class ResourceManager:
    """资源管理器 / Resource manager."""

    def __init__(self):
        self._resources: Dict[str, Any] = {}
        self._initialized = False

    async def init_new_resource(self, config: NewResourceConfig) -> None:
        """
        初始化新资源 / Initialize new resource
        
        参数:
            config: 资源配置 / Resource config
        """
        # 实现资源初始化逻辑
        client = await self._create_client(config)
        self._resources[config.alias] = client
```

#### 步骤 2：添加资源获取方法

```python
    def get_new_resource(self, alias: str = "default") -> NewResourceClient:
        """
        获取新资源客户端 / Get new resource client
        
        参数:
            alias: 资源别名 / Resource alias
            
        返回:
            资源客户端 / Resource client
            
        异常:
            RuntimeError: 资源未初始化时抛出
        """
        if alias not in self._resources:
            raise RuntimeError(f"Resource {alias} not initialized")
        return self._resources[alias]
```

### 2. 添加资源健康检查

#### 步骤 1：实现健康检查方法

```python
async def health_check(self) -> Dict[str, bool]:
    """
    健康检查 / Health check
    
    返回:
        各资源健康状态 / Health status of each resource
    """
    results = {}
    for alias, client in self._resources.items:
        try:
            await self._check_client_health(client)
            results[alias] = True
        except Exception:
            results[alias] = False
    return results
```

### 3. 添加资源关闭逻辑

#### 步骤 1：实现优雅关闭

```python
async def close(self) -> None:
    """
    关闭所有资源 / Close all resources
    """
    for alias, client in self._resources.items():
        try:
            await self._close_client(client)
        except Exception as e:
            logger.warning("Failed to close resource %s: %s", alias, e)
    self._resources.clear()
```

## 相关文档

- [数据库连接](reference/database.md)
- [缓存连接](reference/cache.md)
- [消息队列](reference/mq.md)
- [资源健康检查](reference/health-check.md)
