import logging
from logging.handlers import RotatingFileHandler
from os import environ
from pathlib import Path


DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3


def _int_from_env(name: str, default: int) -> int:
    raw_value = environ.get(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def setup_logger(name: str, log_file: str | Path) -> logging.Logger:
    """Set up a named logger with console and rotating file handlers."""
    log_level_name = environ.get("LOG_LEVEL", "WARNING").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    max_bytes = _int_from_env("LOG_MAX_BYTES", DEFAULT_MAX_BYTES)
    backup_count = _int_from_env("LOG_BACKUP_COUNT", DEFAULT_BACKUP_COUNT)

    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    logger.propagate = False

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
