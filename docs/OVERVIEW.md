# Linglong Web Overview

## Architecture

```
Service App
└── LinglongAppServer
    ├── Router (FastAPI)
    ├── ResourceManager (DB/Cache/MQ)
    ├── Scheduler (aioclock)
    ├── HTTP Client (aiohttp)
    └── Extension Hooks (on_config_ready/on_app_created/on_startup/on_shutdown)
```

- **AppServer**：统一封装服务启动、健康检查、优雅关闭；服务注册、远程配置等上层能力通过扩展钩子在业务侧实现，框架不内置。
- **ResourceManager**：集中管理 PG/Redis/Mongo/RabbitMQ/Celery/AioClock/Limiter，提供异步上下文管理器。
- **Config Proxy**：线程安全的配置访问层，支持批量更新、异步接口与动态热更新。
- **Decorators**：缓存 (`cacher`)、限流 (`limiter`, `limiter_local`)、集群锁 (`cluster_lock`) 均采用 asyncio 风格实现。
- **HTTP Client**：在请求链路自动注入 request-id、统一处理错误与日志。
- **Scheduler**：兼容 aioclock 触发器，支持任务包装、日志与异常捕获。

## Key Packages

| Package | Description |
| --- | --- |
| `linglong_web.server` | FastAPI 服务启动器，附带内部路由与中间件 |
| `linglong_web.config` | 配置代理，提供同步/异步 API |
| `linglong_web.resource` | 资源生命周期管理，包含初始化与关闭流程 |
| `linglong_web.http` | Async HTTP 客户端，带 request-id 与错误统一封装 |
| `linglong_web.scheduler` | aioclock 调度组合器 |
| `linglong_web.cacher` / `limiter` / `cluster_lock` | Redis 缓存、限流、锁装饰器 |
| `linglong_web.response` | 标准响应模型与辅助构造函数 |
| `linglong_web.utils` | 上下文、日志、信号、时间、同步原语等工具 |

## Testing Strategy

- 单元测试位于 `tests/` 目录，覆盖配置代理、HTTP 客户端、调度器、响应模型、服务启动器等核心模块。
- 对依赖外部系统的模块（ResourceManager、SignalHandler 等）提供 stub/mocking 测试，并在宿主项目中补充集成验证。
- 使用 `pytest-cov` 生成覆盖率报告，目标覆盖率 ≥ 80%（核心模块 ≥ 90%）。

## Publishing Checklist

1. `pip install -e ".[all,dev]"`（本地装齐核心 + 全部后端 + 开发依赖）。
2. 运行 `pytest` 并确认覆盖率符合标准。
3. 在 `linglong_web/__version__.py` 升级版本号，并更新 `CHANGELOG.md`。
4. 推送代码，在 GitHub 上创建 Release（打 tag）。
5. GitHub Actions（`.github/workflows/publish.yml`）经 PyPI Trusted Publishing 自动构建并发布，无需手动 `twine upload`。
