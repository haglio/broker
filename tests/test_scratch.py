"""A case's scratch goes when the case ends, whatever it wrote there."""
from __future__ import annotations

import contextlib
import os
import stat
from pathlib import Path

import pytest

from tests.scratch import scratch_dir


def test_a_read_only_file_does_not_keep_the_scratch_standing(tmp_path: Path):
    """git writes its object files read-only, and Windows refuses to delete one."""
    with scratch_dir(tmp_path) as scratch:
        written = scratch / "object"
        written.write_bytes(b"what git writes under .git/objects")
        written.chmod(stat.S_IREAD)

    assert not scratch.exists()


def test_a_file_the_case_left_open_is_named_instead_of_left_behind(tmp_path: Path):
    with (
        contextlib.ExitStack() as still_open,
        pytest.raises(PermissionError, match=r"held\.log"),
        scratch_dir(tmp_path) as scratch,
    ):
        still_open.enter_context((scratch / "held.log").open("w"))


def test_a_file_linked_in_from_outside_keeps_its_read_only_bit(tmp_path: Path):
    """Every link to a file shares that file's read-only bit, so clearing it on
    the link would clear it on a file outside the scratch too."""
    outside = tmp_path / "elsewhere.txt"
    outside.write_bytes(b"a file its owner keeps read-only")
    outside.chmod(stat.S_IREAD)
    try:
        with pytest.raises(PermissionError, match=r"linked\.txt"), scratch_dir(tmp_path) as scratch:
            os.link(outside, scratch / "linked.txt")

        assert not outside.stat().st_mode & stat.S_IWRITE
    finally:
        outside.chmod(stat.S_IWRITE)
