from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from pathlib import Path


def configure_logging(name: str, log_file: Path, *, console: bool = False) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    while logger.handlers:
        handler = logger.handlers.pop()
        handler.close()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


def install_exception_logging(logger: logging.Logger) -> None:
    def _log(where: str, exc_type, exc, tb) -> None:
        if exc_type is KeyboardInterrupt:
            return
        logger.critical("Unhandled exception in %s", where, exc_info=(exc_type, exc, tb))

    def _sys_excepthook(exc_type, exc, tb):
        _log("sys.excepthook", exc_type, exc, tb)

    def _thread_excepthook(args):
        thread_name = getattr(args.thread, "name", "unknown")
        _log(f"thread:{thread_name}", args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = _sys_excepthook
    threading.excepthook = _thread_excepthook
