---
name: coding-standards
description: 代码规范指南。说明项目的代码风格、类型注解、文档注释等规范。用于代码审查和确保代码符合项目规范。
---

# 代码规范指南

本指南说明 linglong_web 项目的代码规范。

## 常用操作

### 1. 代码风格检查

#### 步骤 1：运行 ruff 检查格式

```bash
ruff check linglong_web
```

#### 步骤 2：运行 ruff 格式化

```bash
ruff format linglong_web
```

### 2. 类型检查

#### 步骤 1：运行 mypy 检查类型

```bash
mypy linglong_web
```

#### 步骤 2：修复类型错误

根据 mypy 提示修复类型注解问题。

### 3. 添加新模块

#### 步骤 1：创建模块文件

在对应目录下创建新模块：

```python
# linglong_web/new_module.py
"""
新模块 / New Module

模块功能描述 / Module function description.
"""

from typing import Dict, Any
```

#### 步骤 2：添加类型注解

确保所有公开函数有类型注解：

```python
def process(data: str) -> Dict[str, Any]:
    """处理数据 / Process data"""
    pass
```

#### 步骤 3：编写文档字符串

使用中英双语描述：

```python
def process(data: str) -> Dict[str, Any]:
    """
    处理数据 / Process data
    
    参数 / Args:
        data: 输入数据 / Input data
    
    返回 / Returns:
        处理后的数据 / Processed data
    """
    pass
```

### 4. 提交代码

#### 步骤 1：运行检查

```bash
ruff check linglong_web
ruff format --check linglong_web
mypy linglong_web
```

#### 步骤 2：运行测试

```bash
pytest tests/ -v
```

## 代码注释规范

### 模块文档字符串

```python
"""
模块名称 / Module Name

模块功能描述 / Module function description.

示例 / Example:
    >>> from linglong_web import module
    >>> module.function()
"""
```

### 类文档字符串

```python
class MyClass:
    """
    类名称 / Class Name
    
    类功能描述 / Class function description.
    """
```

### 函数文档字符串

```python
def function(param: str) -> str:
    """
    函数名称 / Function Name
    
    函数功能描述 / Function function description.
    
    参数 / Args:
        param: 参数说明 / Parameter description
        
    返回 / Returns:
        返回值说明 / Return value description
        
    异常 / Raises:
        ValueError: 异常说明 / Exception description
    """
    pass
```

### 行内注释

```python
# 注释内容 / Comment content
result = process()  # 处理结果 / Processing result
```
