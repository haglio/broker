"""Tests for the verb channel fun_time, genau and clipper steer the broker through.

The contract under pin: one verb at a time, folded to upper case, the file
emptied as it is read so a verb never replays, and a read that never raises
into the broker's loop.
"""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

from osr2_broker.command_file import consume_command_file


def test_a_lower_case_verb_is_returned_upper_cased(tmp_path: Path):
    cmd = tmp_path / "broker_cmd.txt"
    cmd.write_text("park", encoding="utf-8")

    assert consume_command_file(cmd) == "PARK"


def test_surrounding_whitespace_is_stripped(tmp_path: Path):
    cmd = tmp_path / "broker_cmd.txt"
    cmd.write_text("  resume \r\n", encoding="utf-8")

    assert consume_command_file(cmd) == "RESUME"


def test_a_bom_is_stripped(tmp_path: Path):
    """PowerShell writers leave a BOM; it must not glue itself to the verb."""
    cmd = tmp_path / "broker_cmd.txt"
    cmd.write_text("﻿retract", encoding="utf-8")

    assert consume_command_file(cmd) == "RETRACT"


def test_the_file_is_emptied_by_the_read_so_a_verb_never_replays(tmp_path: Path):
    cmd = tmp_path / "broker_cmd.txt"
    cmd.write_text("PARK", encoding="utf-8")

    consume_command_file(cmd)

    assert cmd.read_text(encoding="utf-8") == ""


def test_a_second_read_returns_none(tmp_path: Path):
    cmd = tmp_path / "broker_cmd.txt"
    cmd.write_text("PARK", encoding="utf-8")

    assert consume_command_file(cmd) == "PARK"
    assert consume_command_file(cmd) is None


def test_a_missing_file_reads_as_no_command(tmp_path: Path):
    assert consume_command_file(tmp_path / "broker_cmd.txt") is None


def test_a_blank_file_reads_as_no_command(tmp_path: Path):
    cmd = tmp_path / "broker_cmd.txt"
    cmd.write_text("  \r\n", encoding="utf-8")

    assert consume_command_file(cmd) is None


def test_an_undecodable_file_reads_as_no_command(tmp_path: Path):
    """A half-written or foreign-encoded file must never raise into the loop."""
    cmd = tmp_path / "broker_cmd.txt"
    cmd.write_bytes(b"\xff\xfe\x00park")

    assert consume_command_file(cmd) is None


def test_an_unreadable_path_logs_and_reads_as_no_command(tmp_path: Path):
    logger = MagicMock()

    # A directory exists but cannot be read as text, on any platform.
    assert consume_command_file(tmp_path, logger=logger) is None
    logger.exception.assert_called_once()


def test_a_park_written_to_the_file_schedules_the_hold_exactly_once(tmp_path: Path):
    """The whole channel, end to end: a lower-case 'park' dropped in the file is
    consumed on the next tick and scheduled once — the blanking write means the
    ticks after it see nothing, so the hold's clock is never pushed back."""
    from osr2_broker.session import BrokerSerialSession

    clock = [10.0]
    cmd = tmp_path / "broker_cmd.txt"
    cmd.write_text("park", encoding="utf-8")

    auto_mode = MagicMock()
    auto_mode.is_active = False
    auto_mode.consume_deactivation.return_value = False
    logger = MagicMock()
    session = BrokerSerialSession(
        serial_factory=MagicMock(),
        virtual_port="COM15",
        real_port="COM4",
        baud=115200,
        broker_cmd_file=cmd,
        genau_enabled_file=tmp_path / "genau_enabled.txt",
        auto_stale_timeout=2.0,
        stop_event=threading.Event(),
        broker_paused=threading.Event(),
        auto_mode=auto_mode,
        logger=logger,
        start_thread=MagicMock(),
        consume_command=consume_command_file,
        read_genau_enabled=lambda _path: True,
        monotonic=lambda: clock[0],
    )
    real_port = MagicMock()
    lock = threading.Lock()

    session.tick_command_and_stale_timeout(object(), real_port=real_port, serial_write_lock=lock)
    clock[0] = 10.5
    session.tick_command_and_stale_timeout(object(), real_port=real_port, serial_write_lock=lock)

    # 11.2 is past the first tick's schedule (11.0) but short of where a replay
    # on the second tick would have pushed it (11.5): a replayed verb means no
    # write lands here.
    clock[0] = 11.2
    session.tick_command_and_stale_timeout(object(), real_port=real_port, serial_write_lock=lock)

    real_port.write.assert_called_once_with(b"L00000I500\n")
    scheduled = [c.args[0] for c in logger.info.call_args_list]
    assert scheduled.count("OmniPause: park scheduled") == 1
