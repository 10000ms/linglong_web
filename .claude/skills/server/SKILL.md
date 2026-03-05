---
name: server
description: 服务启动器开发指南。说明如何开发与扩展 LinglongAppServer、扩展钩子、路由管理等。
---

# Server 开发指南

本指南说明如何开发与扩展 Server 模块。Server 模块负责 FastAPI 应用的启动、中间件管理和扩展钩子。

## 架构概述

```
LinglongAppServer (主服务类)
    ├── FastAPI 实例管理
    ├── 生命周期钩子 (on_startup, on_shutdown 等)
    ├── 扩展系统 (BaseServerExtension)
    └── 调度器组 (aioclock Group)
```

## 常用操作

### 1. 添加新的生命周期钩子

#### 步骤 1：在 BaseServerExtension 中添加新钩子

在 `server_extensions.py` 中添加新的钩子方法：

```python
class BaseServerExtension(ABC):
    """服务器扩展基类 / Base class for server extensions."""

    async def on_config_ready(self, server: "LinglongAppServer") -> None:
        """
        配置就绪时调用 / Called when config is ready
        
        参数:
            server: 服务实例 / Server instance
        """
        pass
```

#### 步骤 2：在 LinglongAppServer 中触发钩子

在 `server.py` 中调用新钩子：

```python
async def initialize(self, ...):
    # 触发 on_config_ready
    for ext in self._extensions:
        await ext.on_config_ready(self)
```

### 2. 添加新的中间件

#### 步骤 1：在 server.py 中添加中间件

```python
async def _setup_middlewares(self):
    # 添加自定义中间件
    @self.app.middleware("http")
    async def custom_middleware(request: Request, call_next):
        # 中间件逻辑
        response = await call_next(request)
        return response
```

### 3. 添加新的路由功能

#### 步骤 1：在 router.py 中添加路由方法

```python
class ServerRouter:
    """路由管理器 / Route manager."""

    def add_route(self, path: str, method: str, handler: Callable):
        """
        添加路由 / Add a route
        
        参数:
            path: 路由路径 / Route path
            method: HTTP 方法 / HTTP method
            handler: 处理函数 / Handler function
        """
        pass
```

## 相关文档

- [Server 扩展](reference/server-extensions.md)
- [路由管理](reference/routing.md)
- [中间件](reference/middleware.md)
