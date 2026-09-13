"""The broker's two state files, renamed once from the names they carried until 2026-09-13."""
from __future__ import annotations

import logging
from pathlib import Path

from app_support import state_files as names

from osr2_broker.state_files import migrate_state_files

_LOG = logging.getLogger("test")


def test_last_sessions_files_are_renamed_with_their_contents(tmp_path: Path):
    """Both were named after Genau, which never read either; a session that had
    turned auto off must find it still off under the new name."""
    (tmp_path / "genau_mode.txt").write_text("1", encoding="utf-8")
    (tmp_path / "genau_enabled.txt").write_text("0", encoding="utf-8")

    renamed = migrate_state_files(tmp_path, _LOG)

    assert sorted(renamed) == sorted([names.BROKER_MODE, names.BROKER_AUTO_ENABLED])
    assert (tmp_path / names.BROKER_MODE).read_text(encoding="utf-8") == "1"
    assert (tmp_path / names.BROKER_AUTO_ENABLED).read_text(encoding="utf-8") == "0"
    assert not (tmp_path / "genau_mode.txt").exists()
    assert not (tmp_path / "genau_enabled.txt").exists()


def test_a_file_already_under_todays_name_wins_over_the_old_one(tmp_path: Path):
    """A session that started after the rename has written the new file; an old
    one still lying there is a broker from before, not a newer decision."""
    (tmp_path / "genau_enabled.txt").write_text("0", encoding="utf-8")
    (tmp_path / names.BROKER_AUTO_ENABLED).write_text("1", encoding="utf-8")

    assert migrate_state_files(tmp_path, _LOG) == []

    assert (tmp_path / names.BROKER_AUTO_ENABLED).read_text(encoding="utf-8") == "1"
    assert not (tmp_path / "genau_enabled.txt").exists()


def test_a_state_dir_with_nothing_old_in_it_is_left_alone(tmp_path: Path):
    (tmp_path / names.BROKER_MODE).write_text("0", encoding="utf-8")

    assert migrate_state_files(tmp_path, _LOG) == []

    assert sorted(p.name for p in tmp_path.iterdir()) == [names.BROKER_MODE]
