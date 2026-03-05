---
name: linglong-web-development
description: Linglong Web 项目开发指南。用于添加新功能、修复 Bug、编写测试、发布版本等开发操作。
---

# Linglong Web 开发指南

本项目是一个面向微服务场景的 FastAPI 工具箱，提供服务启动、资源管理、配置代理、HTTP 客户端、缓存、限流、调度器等功能。

## 项目结构

```
linglong_web/
├── linglong_web/              # 主源码目录
│   ├── core/                  # 核心模块
│   │   ├── server.py          # FastAPI 启动器
│   │   ├── server_extensions.py  # 扩展钩子
│   │   ├── config.py          # 配置代理
│   │   ├── resource.py        # 资源管理器
│   │   ├── http.py            # HTTP 客户端
│   │   ├── cacher.py          # 缓存装饰器
│   │   ├── limiter.py         # 限流装饰器
│   │   ├── cluster_lock.py    # 分布式锁
│   │   ├── scheduler.py       # 调度器
│   │   ├── router.py          # 路由管理
│   │   ├── response.py        # 响应构建
│   │   └── ...
│   └── utils/                 # 工具函数
│       ├── context.py         # 上下文管理
│       ├── log.py             # 日志工具
│       ├── signal_handler.py  # 信号处理
│       └── ...
├── tests/                     # 测试目录
└── docs/                      # 文档目录
```

## 常用操作

### 1. 添加新功能

#### 步骤 1：确定功能类型

- **Server 级别功能**：服务启动、中间件、扩展钩子，使用 [server](server/SKILL.md)
- **Config 级别功能**：配置管理、热更新，使用 [config](config/SKILL.md)
- **Resource 级别功能**：数据库、缓存、MQ 连接管理，使用 [resource](resource/SKILL.md)
- **HTTP 装饰器功能**：缓存、限流、分布式锁，使用 [http-decorators](http-decorators/SKILL.md)
- **通用工具功能**：多个模块共用，使用 [scheduler](scheduler/SKILL.md)

#### 步骤 2：实现功能

1. 在对应模块中添加代码
2. 同步更新 `__init__.py` 的导出
3. 添加类型注解（使用 Pydantic 模型）
4. 遵循 [coding-standards](coding-standards/SKILL.md)

#### 步骤 3：编写测试

创建测试文件，参考 `tests/` 目录下的测试规范。

#### 步骤 4：更新文档

- API 文档：更新对应的 docstring
- 用户文档：更新 README.zh-CN.md

### 2. 修复 Bug

#### 步骤 1：定位问题

1. 查看错误堆栈，确定问题模块
2. 分析相关代码逻辑
3. 编写最小复现用例

#### 步骤 2：修复问题

1. 在对应模块中修复代码
2. 确保修复不影响现有功能

#### 步骤 3：验证修复

1. 运行相关测试用例
2. 确保所有测试通过

### 3. 代码审查

使用 [coding-standards](coding-standards/SKILL.md) 进行代码审查：

- 代码风格检查
- 类型注解检查
- 文档字符串检查

### 4. 发布新版本

#### 步骤 1：准备发布

1. 更新 CHANGELOG.md
2. 检查版本号是否需要更新（在 `linglong_web/__version__.py`）
3. 确保所有测试通过

#### 步骤 2：执行发布

1. 使用 `python -m build` 工具打包
2. 上传到 PyPI

## Skills 索引

### 开发指南

- [server](server/SKILL.md) - 服务启动器开发
- [config](config/SKILL.md) - 配置管理开发
- [resource](resource/SKILL.md) - 资源管理开发
- [http-decorators](http-decorators/SKILL.md) - HTTP 装饰器开发
- [scheduler](scheduler/SKILL.md) - 调度器开发

### 工程实践

- [coding-standards](coding-standards/SKILL.md) - 代码规范
