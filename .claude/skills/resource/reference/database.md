# 资源管理

本文档说明资源管理的使用方法。

## 基本用法

### 1. 初始化资源

```python
from linglong_web import init_resources

await init_resources(
    db_config={"default": {"url": "postgresql://..."}},
    redis_config={"default": {"host": "localhost", "port": 6379}},
)
```

### 2. 获取资源

```python
from linglong_web import Rmanager

# 获取数据库连接
db = Rmanager.get_db("default")

# 获取 Redis 连接
redis = Rmanager.get_redis("default")

# 获取 MongoDB 连接
mongo = Rmanager.get_mongo("default")
```

### 3. 关闭资源

```python
from linglong_web import close_resources

await close_resources()
```

## 资源类型

### 数据库 (PostgreSQL)

```python
await init_resources(
    db_config={
        "default": {
            "url": "postgresql://user:pass@localhost/dbname",
            "pool_size": 10,
        }
    }
)
```

### 缓存 (Redis)

```python
await init_resources(
    redis_config={
        "default": {
            "host": "localhost",
            "port": 6379,
            "db": 0,
        }
    }
)
```

### 消息队列 (RabbitMQ)

```python
await init_resources(
    rabbitmq_config={
        "default": {
            "url": "amqp://guest:guest@localhost/",
        }
    }
)
```
