"""Central logging configuration for CLI and Gradio entrypoints."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False
_ROOT_LOGGER_NAME = "ai_news_agent"

_DEFAULT_LOG_PATH = Path("logs") / "ai-news-agent.log"
_DEFAULT_LEVEL = "INFO"
_DEFAULT_MAX_BYTES = 2_000_000
_DEFAULT_BACKUP_COUNT = 3

_LOG_FORMAT = (
    "%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _resolve_log_level() -> int:
    raw = os.environ.get("AI_NEWS_AGENT_LOG_LEVEL", _DEFAULT_LEVEL).strip().upper()
    level = logging.getLevelNamesMapping().get(raw)
    if isinstance(level, int):
        return level
    return logging.INFO


def _resolve_log_path() -> Path:
    raw = os.environ.get("AI_NEWS_AGENT_LOG_PATH")
    if raw and str(raw).strip():
        return Path(str(raw).strip())
    return _DEFAULT_LOG_PATH


def configure_logging(*, force: bool = False) -> logging.Logger:
    """Configure root package logger with console + rotating file handlers.

    Idempotent unless ``force=True``. Returns the package logger.
    """
    global _CONFIGURED
    logger = logging.getLogger(_ROOT_LOGGER_NAME)

    if _CONFIGURED and not force:
        return logger

    if force:
        logger.handlers.clear()

    level = _resolve_log_level()
    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(formatter)
        logger.addHandler(console)

    log_path = _resolve_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    max_bytes = _env_int("AI_NEWS_AGENT_LOG_MAX_BYTES", _DEFAULT_MAX_BYTES)
    backup_count = _env_int("AI_NEWS_AGENT_LOG_BACKUP_COUNT", _DEFAULT_BACKUP_COUNT)

    if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    _CONFIGURED = True
    logger.debug("logging configured level=%s path=%s", logging.getLevelName(level), log_path)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the package root (configures on first use)."""
    if not _CONFIGURED:
        configure_logging()
    if name is None or name == _ROOT_LOGGER_NAME:
        return logging.getLogger(_ROOT_LOGGER_NAME)
    if name.startswith(f"{_ROOT_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")


def reset_logging_for_tests() -> None:
    """Clear handlers and configuration state (tests only)."""
    global _CONFIGURED
    root = logging.getLogger(_ROOT_LOGGER_NAME)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    _CONFIGURED = False


__all__ = ["configure_logging", "get_logger", "reset_logging_for_tests"]
