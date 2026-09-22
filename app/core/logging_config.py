"""Antigravity Telegram Bot - Central Logging Configuration."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core import config

DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    log_file: str | Path | None = None,
    level: int = logging.INFO,
) -> None:
    """Configures root logger with console (stdout) and rotating file handlers."""
    target_log = Path(log_file or (config.PROJECT_ROOT / "bot.log"))
    target_log.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    target_resolved = str(target_log.resolve())
    has_target_file_handler = any(
        isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None) == target_resolved
        for h in root_logger.handlers
    )
    if has_target_file_handler:
        return

    formatter = logging.Formatter(fmt=DEFAULT_LOG_FORMAT, datefmt=DEFAULT_DATE_FORMAT)

    has_console_handler = any(
        isinstance(h, logging.StreamHandler)
        and not isinstance(h, RotatingFileHandler)
        and getattr(h, "stream", None) is sys.stdout
        for h in root_logger.handlers
    )
    if not has_console_handler:
        # Console handler (stdout)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # Rotating file handler (5 MB, 3 backups)
    file_handler = RotatingFileHandler(
        target_log,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Silence overly verbose third-party loggers
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
