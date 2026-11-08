from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

from app_support.file_channel import consume_command_file

from tests.sessions import make_session


def test_a_file_caught_half_written_or_in_another_encoding_reads_as_no_command_never_raising_into_the_loop(tmp_path: Path):
    cmd = tmp_path / "broker_cmd.txt"
    cmd.write_bytes(b"\xff\xfe\x00park")

    assert consume_command_file(cmd) == []


def _a_directory_at_the_queue_s_path_never_tmp_path_itself_which_the_claim_would_rename(tmp_path: Path) -> Path:
    cmd = tmp_path / "broker_cmd.txt"
    cmd.mkdir()
    return cmd


def test_an_unreadable_path_logs_and_reads_as_no_command(tmp_path: Path):
    logger = MagicMock()
    cmd = _a_directory_at_the_queue_s_path_never_tmp_path_itself_which_the_claim_would_rename(tmp_path)

    assert consume_command_file(cmd, logger=logger) == []
    logger.exception.assert_called_once()


def test_a_park_written_to_the_file_schedules_the_hold_exactly_once_a_tick_after_it_fired_schedules_no_second(
        tmp_path: Path):
    clock = [10.0]
    cmd = tmp_path / "broker_cmd.txt"
    cmd.write_text("park", encoding="utf-8")

    auto_mode = MagicMock()
    auto_mode.is_active = False
    auto_mode.consume_deactivation.return_value = False
    logger = MagicMock()
    session = make_session(
        broker_cmd_file=cmd,
        auto_mode=auto_mode,
        logger=logger,
        consume_command=consume_command_file,
        monotonic=lambda: clock[0],
    )
    real_port = MagicMock()
    lock = threading.Lock()

    for clock[0] in (10.0, 11.5, 12.0, 13.5):
        session.tick(object(), real_port=real_port, serial_write_lock=lock)

    real_port.write.assert_called_once_with(b"L00000I1000\n")
    scheduled = [c.args[0] for c in logger.info.call_args_list]
    assert scheduled.count("OmniPause: park scheduled") == 1


def test_two_verbs_queued_between_ticks_are_both_acted_on_in_order_a_reader_of_the_broker_s_own_once_lost_them(tmp_path: Path):
    cmd = tmp_path / "broker_cmd.txt"
    cmd.write_text("park\nresume\n", encoding="utf-8")
    auto_mode = MagicMock()
    auto_mode.is_active = False
    auto_mode.consume_deactivation.return_value = False
    logger = MagicMock()
    session = make_session(
        broker_cmd_file=cmd,
        auto_mode=auto_mode,
        logger=logger,
        consume_command=consume_command_file,
        monotonic=lambda: 10.0,
    )

    session.tick(
        object(), real_port=MagicMock(), serial_write_lock=threading.Lock())

    said = [c.args[0] for c in logger.info.call_args_list]
    assert said.index("OmniPause: park scheduled") < said.index("OmniPause: broker resumed")
