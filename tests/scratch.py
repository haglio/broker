from __future__ import annotations

import contextlib
import os
import shutil
import stat
import uuid
from collections.abc import Iterator
from pathlib import Path


@contextlib.contextmanager
def scratch_dir(root: Path) -> Iterator[Path]:
    root.mkdir(parents=True, exist_ok=True)
    path = (root / f"case_{uuid.uuid4().hex}").resolve()
    path.mkdir()
    try:
        yield path
    finally:
        remove_scratch(path)


def remove_scratch(path: Path) -> None:
    # Windows refuses to delete a read-only file.
    shutil.rmtree(path, onexc=_clear_the_read_only_bit_and_try_again)


def _clear_the_read_only_bit_and_try_again(function, name, refusal) -> None:
    if function not in (os.unlink, os.rmdir) or not _named_only_here_every_link_shares_the_read_only_bit(name):
        raise refusal
    os.chmod(name, stat.S_IWRITE)
    function(name)


def _named_only_here_every_link_shares_the_read_only_bit(name) -> bool:
    entry = os.lstat(name)
    return not stat.S_ISLNK(entry.st_mode) and entry.st_nlink == 1
