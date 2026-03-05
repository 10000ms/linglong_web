# 缓存装饰器

本文档说明缓存装饰器的使用方法。

## 基本用法

### 1. 使用缓存装饰器

```python
from linglong_web import cacher

@cacher(key="user:{user_id}", expire=300)
async def get_user(user_id: str) -> dict:
    """获取用户信息 / Get user info"""
    # 从数据库获取用户
    return await db.fetch("SELECT * FROM users WHERE id = $1", user_id)
```

### 2. 手动缓存操作

```python
from linglong_web import cache_set, cache_get, cache_delete

# 设置缓存
await cache_set("key", "value", expire=300)

# 获取缓存
value = await cache_get("key")

# 删除缓存
await cache_delete("key")
```

### 3. 缓存前缀

```python
@cacher(key="user:{user_id}", expire=300, prefix="api")
async def get_user(user_id: str) -> dict:
    """使用自定义前缀的缓存 / Cache with custom prefix"""
    pass
```

## 缓存策略

### LRU 缓存

```python
@cacher(key="data:{key}", strategy="lru", max_size=1000)
async def get_data(key: str) -> dict:
    """LRU 缓存 / LRU cache"""
    pass
```

### TTL 缓存

```python
@cacher(key="data:{key}", expire=60, strategy="ttl")
async def get_data(key: str) -> dict:
    """TTL 缓存 / TTL cache"""
    pass
```

### 缓存失效

```python
from linglong_web import cache_invalidate

# 失效指定 key
await cache_invalidate("user:123")

# 失效前缀匹配的所有 key
await cache_invalidate(prefix="user")
```
