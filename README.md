# Linglong Web

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code Style](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

Linglong Web is a FastAPI toolkit for microservice scenarios, focusing on "simple startup, flexible extension, and complete observability".

中文文档：see [README.zh-CN.md](README.zh-CN.md)

## Links

- GitHub: https://github.com/victorlai/linglong-web
- Issues: https://github.com/victorlai/linglong-web/issues
- Changelog: https://github.com/victorlai/linglong-web/blob/master/CHANGELOG.md

## Why this library

When building microservices with FastAPI, you often need:

- **Service lifecycle management** - startup, shutdown, health checks, graceful termination
- **Resource orchestration** - database connections, cache, message queues, schedulers
- **Observability** - request-id propagation, structured logging, rate limiting
- **Extensibility** - plugin hooks for service registration, remote config, etc.

Linglong Web provides all these out of the box as modular components.

## Features

- **AppServer lifecycle** - Built-in middleware, error handling, health checks, and signal handling
- **Extension hooks** - `on_config_ready`, `on_app_created`, `on_startup`, `on_shutdown` for custom logic injection
- **Thread-safe config** - `LinglongConfig` with hot reload support
- **Resource management** - Unified initialization for PostgreSQL, Redis, MongoDB, RabbitMQ, Celery
- **HTTP client** - aiohttp wrapper with request-id propagation and unified error handling
- **Decorators** - Redis cache, rate limit, and distributed lock decorators
- **Scheduler** - aioclock integration for periodic tasks
- **Bilingual comments** - Chinese and English comments throughout the codebase

## Installation

```bash
pip install linglong-web
```

## Quick Start

```python
from linglong_web import LinglongConfigBase, init_config
from linglong_web import build_success_response
from linglong_web import BaseRoute, ServerRouter
from linglong_web import LinglongAppServer


class DevConfig(LinglongConfigBase):
    """Development configuration"""
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

## Module Overview

| Module | Description |
| --- | --- |
| `server` | FastAPI bootstrapper with middlewares & extension hooks |
| `server_extensions` | Lifecycle extension protocol for custom capabilities |
| `config` | Thread-safe config proxy with hot reload |
| `resource` | Unified resource bootstrapper (DB, Cache, MQ, Scheduler) |
| `http` | aiohttp client with request-id injection |
| `cacher` | Redis cache decorator |
| `limiter` | Rate limit decorator |
| `cluster_lock` | Distributed lock decorator |
| `scheduler` | aioclock helpers for periodic tasks |
| `utils` | Context, logging, signal handling, time utilities |

## Extension Example

```python
from linglong_web.server_extensions import BaseServerExtension


class RegistryExtension(BaseServerExtension):
    """Example: custom service registration logic"""

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

> Linglong no longer bundles service registration or remote config capabilities. Implement them in your business repository using extension hooks.

## Testing & Coverage

```bash
# Run tests with coverage
pytest tests/ -v --cov=linglong_web --cov-report=term-missing

# Or with PYTHONPATH
PYTHONPATH=. pytest tests/ -v --cov=linglong_web --cov-report=term-missing
```

- All new modules should maintain **80%+** test coverage.
- Use `pytest-asyncio` and `pytest-mock` for fine-grained mocking of resources, rate limiters, and signal handlers.

## Project Layout

```
linglong_web/
├── linglong_web/
│   ├── core/               # Core modules
│   │   ├── server.py       # FastAPI bootstrapper
│   │   ├── config.py       # Config proxy
│   │   ├── resource.py     # Resource manager
│   │   ├── http.py         # HTTP client
│   │   ├── cacher.py       # Cache decorator
│   │   ├── limiter.py      # Rate limit decorator
│   │   └── ...
│   └── utils/              # Utilities
├── tests/                  # Test suite
└── docs/                   # Documentation
```

## Versioning

The package version is sourced from `linglong_web/__version__.py`.

## License

MIT License. See LICENSE.
