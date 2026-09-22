"""Where a test writes, and how it is taken away again."""
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
    """A directory of this case's own under *root*, gone when the case ends."""
    root.mkdir(parents=True, exist_ok=True)
    path = (root / f"case_{uuid.uuid4().hex}").resolve()
    path.mkdir()
    try:
        yield path
    finally:
        remove_scratch(path)


def remove_scratch(path: Path) -> None:
    """Delete *path* and all of it, clearing the read-only bit Windows stops on."""
    shutil.rmtree(path, onexc=_clear_the_read_only_bit_and_try_again)


def _clear_the_read_only_bit_and_try_again(function, name, refusal) -> None:
    if function not in (os.unlink, os.rmdir) or not _named_only_here(name):
        raise refusal
    os.chmod(name, stat.S_IWRITE)
    function(name)


def _named_only_here(name) -> bool:
    """Whether clearing *name*'s read-only bit would reach nothing outside."""
    entry = os.lstat(name)
    return not stat.S_ISLNK(entry.st_mode) and entry.st_nlink == 1
