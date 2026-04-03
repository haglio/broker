from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def preparse_config_path(argv: list[str] | None) -> str | None:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--config")
    known, _ = ap.parse_known_args(argv)
    return known.config


def consume_command_file(path: Path, *, logger: logging.Logger | None = None) -> str | None:
    try:
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8").replace("\ufeff", "").strip().upper()
        if not text:
            return None
        path.write_text("", encoding="utf-8")
        return text
    except Exception:
        if logger is not None:
            logger.exception("Failed to consume command file %s", path)
        return None


def hidden_subprocess_kwargs() -> dict[str, Any]:
    if os.name != "nt" and sys.platform != "win32":
        return {}

    kwargs: dict[str, Any] = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    kwargs["startupinfo"] = startupinfo
    show_window = getattr(subprocess, "SW_HIDE", None)
    if show_window is not None:
        startupinfo.wShowWindow = show_window
    return kwargs
