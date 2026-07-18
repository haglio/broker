"""The command file Fun Time steers the broker through.

All that is left of what was ``runtime_support``: the CLI, logging and threading
scaffolding it held alongside this is now ``app_support``.

One command at a time, folded to upper case — the broker's verbs (PARK, RESUME)
carry no arguments, so the whole payload can be uppercased, and the file is
emptied as it is read so a verb never replays. The players read a *list* from
their own channel (``player_core.file_channel``) because they can be handed
several navigation verbs between ticks; the broker cannot, so it does not.

Reading is best-effort by design: a half-written file, or one being replaced,
must never raise into the broker's loop, because the next poll is moments away
and will see the settled value.
"""
from __future__ import annotations

import logging
from pathlib import Path


def consume_command_file(path: Path, *, logger: logging.Logger | None = None) -> str | None:
    try:
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8").replace("﻿", "").strip().upper()
        if not text:
            return None
        path.write_text("", encoding="utf-8")
        return text
    except Exception:
        if logger is not None:
            logger.exception("Failed to consume command file %s", path)
        return None
