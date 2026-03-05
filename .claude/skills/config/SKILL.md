---
name: config
description: 配置管理开发指南。说明如何开发与扩展 LinglongConfig、配置热更新等功能。
---

# Config 开发指南

本指南说明如何开发与扩展 Config 模块。Config 模块负责配置管理、热更新和线程安全访问。

## 架构概述

```
LinglongConfigBase (配置基类)
    └── LinglongConfig (配置代理实现)
        ├── 线程安全的配置访问
        ├── 配置热更新
        └── 多环境配置切换
```

## 常用操作

### 1. 添加新的配置项

#### 步骤 1：在 LinglongConfigBase 中定义配置类

在 `config.py` 中添加新的配置类：

```python
class LinglongConfigBase(BaseModel):
    """配置基类 / Base configuration class."""

    DEBUG: bool = False
    SERVICE_NAME: str = "default-service"
    # 新增配置项
    NEW_CONFIG_ITEM: str = "default"
```

#### 步骤 2：在 LinglongConfig 中添加访问方法

```python
class LinglongConfig:
    """配置代理 / Config proxy."""

    @classmethod
    def get_new_config_item(cls) -> str:
        """
        获取新配置项 / Get new config item
        
        返回:
            配置值 / Config value
        """
        return cls._config.get("NEW_CONFIG_ITEM", "default")
```

### 2. 添加配置验证

#### 步骤 1：使用 Pydantic 验证器

```python
class LinglongConfigBase(BaseModel):
    """配置基类 / Base configuration class."""

    PORT: int = 8080

    @field_validator("PORT")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """
        验证端口号 / Validate port number
        
        参数:
            v: 端口号 / Port number
            
        返回:
            验证后的端口号
            
        异常:
            ValueError: 端口号无效时抛出
        """
        if v < 1 or v > 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v
```

### 3. 添加配置热更新

#### 步骤 1：实现热更新方法

```python
@classmethod
def update_config(cls, config_dict: Dict[str, Any]) -> None:
    """
    更新配置 / Update config
    
    参数:
        config_dict: 配置字典 / Config dictionary
    """
    with cls._lock:
        cls._config.update(config_dict)
```

## 相关文档

- [配置热更新](reference/hot-reload.md)
- [多环境配置](reference/multi-env.md)
- [配置验证](reference/validation.md)
