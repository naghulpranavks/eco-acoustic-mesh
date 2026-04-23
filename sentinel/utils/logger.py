"""
Structured Logging — File + Console Output

Provides rotating file logging and colored console output
for the sentinel system. Call setup_logging() once at startup.
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler


_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: str = "INFO",
    log_file: str = "sentinel.log",
    max_bytes: int = 5_242_880,
    backup_count: int = 3,
) -> None:
    """
    Configure root logger with console + rotating file handlers.

    Args:
        level: Logging level string (DEBUG, INFO, WARNING, etc.)
        log_file: Path to the log file.
        max_bytes: Max log file size before rotation.
        backup_count: Number of backup log files to keep.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers to avoid duplicates on re-init
    root.handlers.clear()

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # --- Console handler ---
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG)
    console.setFormatter(formatter)
    root.addHandler(console)

    # --- Rotating file handler ---
    try:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as e:
        root.warning(f"Could not create log file '{log_file}': {e}")

    # Suppress noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    root.info(f"Logging initialized: level={level}, file={log_file}")
