"""Linglong Web 配置模型 / Configuration schemas.

This module contains Pydantic models for resource initialization configuration.
It relies only on standard libraries and Pydantic, ensuring no circular dependencies.
"""
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from pydantic import BaseModel, Field

from .constants import DEFAULT_DB_ALIAS


class PgsqlConfig(BaseModel):
    """PostgreSQL connection configuration."""
    alias: str = Field(default=DEFAULT_DB_ALIAS, description="Database connection alias")
    host: str
    port: int
    user: str
    password: str
    database: str
    pool_size: int = 5
    max_overflow: int = 10
    echo: bool = False
    ensure_database: bool = Field(default=True, description="Whether to auto-create database if missing")
    bootstrap_database: str = Field(default="postgres", description="Database used for bootstrap connection")
    create_db_owner: str | None = Field(default=None, description="Owner to assign when auto-creating database")


class RedisConfig(BaseModel):
    """Redis connection configuration."""
    host: str
    port: int
    password: str = ""
    maxsize: int = 10


class RabbitMQConfig(BaseModel):
    """RabbitMQ connection configuration."""
    host: str
    port: int
    username: str
    password: str
    vhost: str = "/"
    service_name: str = "unknown"


class MongoConfig(BaseModel):
    """MongoDB connection configuration."""
    uri: str


class CeleryConfig(BaseModel):
    """Celery worker/client configuration."""
    app_name: str
    broker_url: str
    backend_url: str
    config_options: Dict[str, Any] = Field(default_factory=dict)
    beat_schedule: Optional[Dict[str, Any]] = None


class ResourceInitConfig(BaseModel):
    """Aggregated configuration for initializing all resources."""
    pgsql_configs: List[PgsqlConfig] = Field(default_factory=list)
    redis: Optional[RedisConfig] = None
    rabbitmq: Optional[RabbitMQConfig] = None
    mongodb: Optional[MongoConfig] = None
    celery: Optional[CeleryConfig] = None
    enable_aioclock: bool = True
    enable_limiter: bool = True
