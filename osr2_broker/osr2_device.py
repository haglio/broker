from __future__ import annotations

from pathlib import Path

from app_support.file_channel import stamp_age

SILENT_ONCE_OFF_S = 30.0


def switched_on(rx_stamp: Path, *, now: float | None = None) -> bool:
    age = stamp_age(rx_stamp, now)
    return age is not None and age < SILENT_ONCE_OFF_S
