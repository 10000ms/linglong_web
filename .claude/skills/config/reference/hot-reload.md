# 配置热更新

本文档说明配置热更新的使用方法。

## 基本用法

### 1. 更新配置

```python
from linglong_web import LinglongConfig

# 更新单个配置项
LinglongConfig.update_config({"DEBUG": True})

# 更新多个配置项
LinglongConfig.update_config({
    "DEBUG": True,
    "LOG_LEVEL": "DEBUG",
    "MAX_CONNECTIONS": 100,
})
```

### 2. 获取配置

```python
from linglong_web import LinglongConfig

# 获取配置值
debug = LinglongConfig.DEBUG
log_level = LinglongConfig.get_log_level()
```

### 3. 监听配置变化

```python
from linglong_web import LinglongConfig

# 注册配置变化回调
def on_config_changed(key: str, old_value: Any, new_value: Any):
    print(f"Config {key} changed from {old_value} to {new_value}")

LinglongConfig.register_change_callback(on_config_changed)
```

## 线程安全

所有配置操作都是线程安全的，使用锁机制保护：

```python
@classmethod
def update_config(cls, config_dict: Dict[str, Any]) -> None:
    """更新配置（线程安全）/ Update config (thread-safe)"""
    with cls._lock:
        cls._config.update(config_dict)
```
