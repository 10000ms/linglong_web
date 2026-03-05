# Linglong Web

[Linglong Web](README.md) 的中文文档。

Linglong Web 是面向微服务场景的 FastAPI 工具箱，聚焦「启动简单、扩展灵活、观测完备」。

---

## 🎯 项目目标

- **模块化能力**：提供可独立选用的配置、HTTP、资源、缓存、调度与限流组件，避免侵入式框架束缚。
- **扩展友好**：通过 `BaseServerExtension` 将服务注册、远程配置等上层能力外置，Linglong 默认零扩展也能完整运行。
- **生产可用**：开箱包含 request-id 透传、结构化日志、优雅停机、健康检查、资源托管与双语注释，方便团队直接落地。

---

## ✨ 核心优势

1. **AppServer 生命周期管理**
   - 内置统一中间件、错误处理、健康检查与信号监听。
   - 新增扩展钩子（`on_config_ready`, `on_app_created`, `on_startup`, `on_shutdown`），方便注入自定义逻辑。
2. **配置与资源管理**
   - `LinglongConfig` 提供线程安全更新；`ResourceManager` 统一管理 PostgreSQL、Redis、MongoDB、RabbitMQ、Celery 等连接。
3. **观测与治理**
   - HTTP 客户端自动透传 request-id，日志工具与限流器/分布式锁提供双语注释与异常语义。
4. **清晰目录**
   - `linglong_web/` 存放源码；`tests/` 覆盖所有关键模块；文档集中在 `docs/`，方便单独打包发布。

---

## 📁 目录结构

```
linglong_web/
├── LICENSE
├── README.md
├── README.zh-CN.md
├── pyproject.toml
├── docs/
├── linglong_web/
│   ├── __init__.py
│   ├── __version__.py
│   ├── core/
│   │   ├── server.py
│   │   ├── server_extensions.py
│   │   ├── config.py
│   │   ├── resource.py
│   │   ├── http.py
│   │   ├── cacher.py
│   │   ├── limiter.py
│   │   ├── cluster_lock.py
│   │   ├── scheduler.py
│   │   └── ...
│   └── utils/
│       ├── context.py
│       ├── log.py
│       ├── signal_handler.py
│       └── ...
└── tests/
```

> 📌 **运行提示**：本仓库以「src layout」组织源码，运行测试或示例前请确保 `PYTHONPATH` 包含项目根目录。

---

## 🧩 模块矩阵

| 模块 | 说明 |
| --- | --- |
| `server` | FastAPI 启动器 + 中间件栈 + 扩展钩子 |
| `server_extensions` | 扩展生命周期协议，可挂接服务注册、远程配置等自定义能力 |
| `config` | 可热更新配置代理 + 双语注释 |
| `resource` | 统一初始化数据库、缓存、MQ、限流、调度器 |
| `http` | request-id 透传 + 超时设置 + 统一异常包装的 aiohttp 客户端 |
| `cacher` `limiter` `cluster_lock` | Redis 缓存、限流、分布式锁装饰器 |
| `scheduler` | aioclock 封装，快速声明周期性任务 |
| `utils` | 上下文、日志、信号处理、读写锁、时间工具等 |

更多深入说明参见 [docs/OVERVIEW.md](docs/OVERVIEW.md)。

---

## 🚀 快速开始

```python
from linglong_web import LinglongConfigBase, init_config
from linglong_web import build_success_response
from linglong_web import BaseRoute, ServerRouter
from linglong_web import LinglongAppServer


class DevConfig(LinglongConfigBase):
    """开发环境配置"""
    DEBUG = True
    SERVICE_NAME = "demo-service"


router = ServerRouter()
router.initialize([
    BaseRoute(
        path="/ping",
        method="GET",
        handler=lambda: build_success_response({"pong": True}),
    )
])

init_config({"dev": DevConfig}, mode_name="dev")

app_server = LinglongAppServer()
await app_server.initialize(
    service_name="demo-service",
    router=router.get_router(),
    config_dict={"dev": DevConfig},
)
await app_server.start(host="0.0.0.0", port=8080)
```

---

## 🔌 扩展示例

```python
from linglong_web.server_extensions import BaseServerExtension


class RegistryExtension(BaseServerExtension):
    """示例：注入自定义服务注册逻辑"""

    def __init__(self, client):
        self._client = client

    async def on_startup(self, server):
        payload = {"service": server.service_name, "instance": server.instance_id}
        await self._client.register(payload)
        server.register_shutdown_callback(lambda: self._client.deregister(payload))


extensions = [RegistryExtension(client)]
await app_server.initialize(
    service_name="demo",
    router=router.get_router(),
    config_dict={"dev": DevConfig},
    extensions=extensions,
)
```

> ✅ Linglong 不再内置服务注册、远程配置等能力；请通过扩展钩子在业务仓库实现，以保持框架通用性。

---

## 📚 使用场景

1. **单体到微服务迁移**：快速抽取公共基础设施（配置、限流、资源管理），保持项目结构一致。
2. **多运行环境**：通过配置代理与扩展钩子，在本地、测试、生产环境中注入差异化逻辑。
3. **可选中间件**：按需挑选 cacher/limiter/cluster_lock/scheduler，无需引入整套服务治理组件。

---

## 🧪 测试与覆盖率

```bash
# 运行测试
pytest tests/ -v --cov=linglong_web --cov-report=term-missing

# 或带 PYTHONPATH
PYTHONPATH=. pytest tests/ -v --cov=linglong_web --cov-report=term-missing
```

- 所有新模块需保持 **80%+** 单测覆盖率。
- 推荐结合 `pytest-asyncio` 与 `pytest-mock` 对资源、限流、信号处理做精细化 mock 测试。

---

## 🤝 贡献指南

- 遵循仓库统一的代码规范：使用 `ruff`（格式化 + lint）与类型检查。
- 关键逻辑必须提供中英双语注释，方便跨团队协作。
- 请在提交前运行 `pytest` 并附带覆盖率报告。

---

## 📄 许可证

Linglong Web 采用 [MIT License](LICENSE)。
