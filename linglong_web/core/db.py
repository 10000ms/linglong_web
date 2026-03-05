"""SQLAlchemy base definition shared across services.

为所有 ORM 模型提供统一的 declarative base。
"""
from sqlalchemy.orm import declarative_base

TableBase = declarative_base()
