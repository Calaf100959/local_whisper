from __future__ import annotations

import logging
from pathlib import Path
import sys

from app.core.runtime import APP_SLUG, get_project_root, get_user_data_root


def configure_logging() -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        _ensure_file_handler(root_logger)
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _ensure_file_handler(root_logger)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def _ensure_file_handler(root_logger: logging.Logger) -> None:
    log_path = _build_log_path()
    if any(
        isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == log_path
        for handler in root_logger.handlers
    ):
        return

    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root_logger.addHandler(file_handler)


def _build_log_path() -> Path:
    if getattr(sys, "frozen", False):
        return get_user_data_root().parent / "logs" / "app.log"
    return get_project_root() / "data" / "logs" / f"{APP_SLUG}.log"
