import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler

from .context import get_request_id

logger = logging.getLogger()


class CustomFormatter(logging.Formatter):
    """自定义格式器，确保异常堆栈完整 / Preserve stack traces in log output."""

    def formatException(self, ei):  # noqa: N802
        return "".join(traceback.format_exception(*ei))


class ColorFormatter(CustomFormatter):
    """ANSI 颜色输出 / ANSI color-enhanced formatter."""

    COLORS = {
        logging.DEBUG: '\033[35m',
        logging.WARNING: '\033[33m',
        logging.ERROR: '\033[31m',
        logging.CRITICAL: '\033[31;47m',
    }
    RESET = '\033[0m'

    def format(self, record):  # noqa: A003
        if record.levelno == logging.INFO:
            return super().format(record)
        color = self.COLORS.get(record.levelno, self.RESET)
        message = super().format(record)
        return f"{color}{message}{self.RESET}"


def _add_request_id(*args, **kwargs):
    record = logging.LogRecord(*args, **kwargs)
    record.oid = get_request_id()
    return record


logging.setLogRecordFactory(_add_request_id)


def init_logger(
        level: int = logging.DEBUG,
        enable_file_handler: bool = False,
        file_addr: str | None = None,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 20,
) -> None:
    """初始化日志输出（控制台 + 轮转文件）/ Configure console & rotating-file log sinks."""

    logger.setLevel(level)

    # 清理旧 handler，避免重复初始化导致日志重复输出。
    # Clear existing handlers to avoid duplicate logs after repeated initialization.
    for existing_handler in list(logger.handlers):
        logger.removeHandler(existing_handler)
        try:
            existing_handler.close()
        except Exception:
            pass

    log_format = '%(levelname).4s %(asctime)s.%(msecs)03d %(oid).30s %(filename)s %(lineno)d: %(message)s'

    if enable_file_handler and file_addr:
        log_directory = os.path.dirname(file_addr)
        if log_directory and not os.path.exists(log_directory):
            os.makedirs(log_directory)
        file_handler = RotatingFileHandler(
            file_addr,
            mode='a',
            maxBytes=max_bytes,
            backupCount=backup_count,
        )
        file_handler.setFormatter(CustomFormatter(log_format, datefmt='%Y-%m-%d %H:%M:%S'))
        logger.addHandler(file_handler)
    else:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(ColorFormatter(log_format, datefmt='%Y-%m-%d %H:%M:%S'))
        logger.addHandler(console_handler)
