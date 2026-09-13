"""The broker's mode file, renamed once from the name it carried while it was called Genau's."""
from __future__ import annotations

import logging
from pathlib import Path

from app_support import state_files as names

from osr2_broker.state_files import rename_last_sessions_mode_file

_LOG = logging.getLogger("test")
_LAST_SESSIONS_NAME = "genau_mode.txt"


def test_last_sessions_mode_file_is_renamed_with_its_contents(tmp_path: Path):
    """It was named after Genau, which never read it; left lying beside the new
    one it would say the broker's mode to nobody, forever."""
    (tmp_path / _LAST_SESSIONS_NAME).write_text("1", encoding="utf-8")

    assert rename_last_sessions_mode_file(tmp_path, _LOG) is True

    assert (tmp_path / names.BROKER_MODE).read_text(encoding="utf-8") == "1"
    assert not (tmp_path / _LAST_SESSIONS_NAME).exists()


def test_a_file_already_under_todays_name_wins_over_the_old_one(tmp_path: Path):
    """A broker that started after the rename has written the new file; an old
    one still lying there is a broker from before, not a newer answer."""
    (tmp_path / _LAST_SESSIONS_NAME).write_text("1", encoding="utf-8")
    (tmp_path / names.BROKER_MODE).write_text("0", encoding="utf-8")

    assert rename_last_sessions_mode_file(tmp_path, _LOG) is False

    assert (tmp_path / names.BROKER_MODE).read_text(encoding="utf-8") == "0"
    assert not (tmp_path / _LAST_SESSIONS_NAME).exists()


def test_a_state_dir_with_nothing_old_in_it_is_left_alone(tmp_path: Path):
    (tmp_path / names.BROKER_MODE).write_text("0", encoding="utf-8")

    assert rename_last_sessions_mode_file(tmp_path, _LOG) is False

    assert sorted(p.name for p in tmp_path.iterdir()) == [names.BROKER_MODE]


def test_a_state_dir_that_is_not_there_yet_is_not_an_error(tmp_path: Path):
    assert rename_last_sessions_mode_file(tmp_path / "state", _LOG) is False
