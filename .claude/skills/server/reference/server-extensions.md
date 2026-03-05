# Server 扩展

本文档说明 Server 模块的扩展相关功能。

## 扩展钩子

### 1. on_config_ready

配置就绪时调用。

```python
async def on_config_ready(self, server: "LinglongAppServer") -> None:
    """
    配置就绪时调用 / Called when config is ready
    
    参数 / Args:
        server: 服务实例 / Server instance
    """
    pass
```

### 2. on_app_created

FastAPI App 创建后调用。

```python
async def on_app_created(self, app: FastAPI) -> None:
    """
    App 创建后调用 / Called after app is created
    
    参数 / Args:
        app: FastAPI 实例 / FastAPI instance
    """
    pass
```

### 3. on_startup

服务启动时调用。

```python
async def on_startup(self, server: "LinglongAppServer") -> None:
    """
    启动时调用 / Called on startup
    
    参数 / Args:
        server: 服务实例 / Server instance
    """
    pass
```

### 4. on_shutdown

服务关闭时调用。

```python
async def on_shutdown(self, server: "LinglongAppServer") -> None:
    """
    关闭时调用 / Called on shutdown
    
    参数 / Args:
        server: 服务实例 / Server instance
    """
    pass
```

## 扩展示例

### 服务注册扩展

```python
class RegistryExtension(BaseServerExtension):
    """服务注册扩展 / Service registry extension"""

    def __init__(self, registry_url: str):
        self._registry_url = registry_url

    async def on_startup(self, server: "LinglongAppServer") -> None:
        payload = {
            "service": server.service_name,
            "instance": server.instance_id,
            "host": server.host,
            "port": server.port,
        }
        async with aiohttp.ClientSession() as session:
            await session.post(f"{self._registry_url}/register", json=payload)
