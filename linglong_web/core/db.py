"""SQLAlchemy base definition shared across services.

为所有 ORM 模型提供统一的 declarative base。
ORM/PostgreSQL 能力属于可选 extra：``pip install "linglong-web[postgres]"``。
未安装时 ``TableBase`` 为 ``None``，仅当真正继承它定义模型时才会用到。
"""
try:
    from sqlalchemy.orm import declarative_base

    TableBase = declarative_base()
except ImportError:  # pragma: no cover - optional dependency
    TableBase = None
