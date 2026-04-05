"""Single-instance guards using Win32 named mutexes."""
from __future__ import annotations

import ctypes
import hashlib
from pathlib import Path

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
_get_last_error = ctypes.get_last_error

ERROR_ALREADY_EXISTS = 183

MUTEX_BROKER = "Global\\OSR2Broker"


def mutex_name_for_config(base: str, config_path: Path) -> str:
    suffix = hashlib.md5(str(config_path).encode()).hexdigest()[:12]
    return f"{base}.{suffix}"


def try_acquire_mutex(name: str) -> int | None:
    handle = _kernel32.CreateMutexW(None, False, name)
    if not handle:
        return None
    if _get_last_error() == ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return None
    return handle
