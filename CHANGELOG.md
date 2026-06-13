# Changelog

All notable changes to this project will be documented in this file.

## 0.0.1 - 2026-06-13

- Initial release of Linglong Web
- FastAPI service bootstrapper with lifecycle management
- Resource backends as optional extras: PostgreSQL (`[postgres]`), MongoDB (`[mongo]`),
  RabbitMQ (`[rabbitmq]`), Celery (`[celery]`); install everything with `[all]`
- MongoDB support uses the native PyMongo async API (`AsyncMongoClient`); Motor is no longer a dependency
- Redis-backed cache, rate limit, and cluster lock decorators (core)
- Thread-safe config proxy with hot reload support
- HTTP client with request-id propagation
- Scheduler integration with aioclock
- Extension hooks (`on_config_ready` / `on_app_created` / `on_startup` / `on_shutdown`) for custom logic
- Bilingual code comments (Chinese/English)
