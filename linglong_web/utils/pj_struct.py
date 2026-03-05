from typing import Any


class Singleton:
    """简单单例基类 / Simple singleton base class."""

    _instance: "Singleton"

    def __new__(cls, *args: Any, **kwargs: Any) -> "Singleton":
        if not hasattr(cls, "_instance"):
            cls._instance = super().__new__(cls)
        return cls._instance
