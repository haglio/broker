from __future__ import annotations

import argparse
import logging
from pathlib import Path


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
