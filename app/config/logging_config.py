"""Centralised logging configuration — date-based file + console output."""

from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# Project root is two levels up from this file (app/config → project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LOG_DIR = _PROJECT_ROOT / "logs"

_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with console + daily-rotating file handlers.

    Safe to call multiple times — only the first invocation takes effect.
    Log files are written to ``<project_root>/logs/marketing_ai_YYYY-MM-DD.log``.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    # Ensure logs directory exists
    os.makedirs(_LOG_DIR, exist_ok=True)

    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(log_format, datefmt=date_format)

    # ── File handler (daily rotation, 30-day retention) ──
    log_file = _LOG_DIR / "marketing_ai.log"
    file_handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"  # rotated files: marketing_ai.log.2026-03-01
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    # ── Console handler ──
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    # ── Root logger ──
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
