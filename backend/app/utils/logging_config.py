"""
Structured Logging Configuration for ScreenShare Pro Backend

Uses loguru for production-ready logging with:
- JSON format for structured logs
- File rotation with compression
- Different log levels per module
- Request correlation ID support
"""

import sys
import logging
from pathlib import Path
from typing import Optional

from loguru import logger as loguru_logger

from app.config import settings


# Log directory
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


class InterceptHandler(logging.Handler):
    """
    Intercept standard logging messages and redirect to Loguru.
    This allows compatibility with third-party libraries using standard logging.
    """

    def emit(self, record: logging.LogRecord) -> None:
        # Get corresponding Loguru level if it exists
        try:
            level = loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        loguru_logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging() -> None:
    """
    Configure Loguru for production use.
    Call this once at application startup.
    """
    # Remove default handler
    loguru_logger.remove()

    # Console handler with human-readable format for development
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    loguru_logger.add(
        sys.stdout,
        format=log_format,
        level=settings.LOG_LEVEL,
        colorize=True,
        backtrace=True,
        diagnose=settings.DEBUG,
    )

    # File handler - All logs (INFO and above)
    loguru_logger.add(
        LOG_DIR / "app.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        level="INFO",
        rotation="00:00",  # New file at midnight
        retention="30 days",  # Keep logs for 30 days
        compression="zip",  # Compress old logs
        backtrace=True,
        diagnose=settings.DEBUG,
        encoding="utf-8",
    )

    # File handler - Error logs only
    loguru_logger.add(
        LOG_DIR / "error.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        level="ERROR",
        rotation="00:00",
        retention="90 days",  # Keep error logs longer
        compression="zip",
        backtrace=True,
        diagnose=True,
        encoding="utf-8",
    )

    # File handler - WebSocket messages (separate file for debugging signaling)
    loguru_logger.add(
        LOG_DIR / "websocket.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        level="DEBUG",
        rotation="500 MB",  # Rotate when file gets too large
        retention="7 days",
        compression="zip",
        filter=lambda record: "websocket" in record["name"].lower(),
        encoding="utf-8",
    )

    # Intercept standard logging
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


# Module-specific loggers
def get_logger(name: str):
    """
    Get a logger for a specific module.

    Usage:
        from app.utils.logging_config import get_logger
        logger = get_logger(__name__)
    """
    return loguru_logger.bind(name=name)


# FastAPI/Starlette specific logger
fastapi_logger = loguru_logger.bind(name="fastapi")
websocket_logger = loguru_logger.bind(name="websocket")
database_logger = loguru_logger.bind(name="database")
auth_logger = loguru_logger.bind(name="auth")
room_logger = loguru_logger.bind(name="room")
diagram_logger = loguru_logger.bind(name="diagram")
mindmap_logger = loguru_logger.bind(name="mindmap")


__all__ = [
    "setup_logging",
    "get_logger",
    "loguru_logger",
    "fastapi_logger",
    "websocket_logger",
    "database_logger",
    "auth_logger",
    "room_logger",
    "diagram_logger",
    "mindmap_logger",
]
