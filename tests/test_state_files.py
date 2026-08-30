"""The files the broker publishes itself through.

Four names under the shared state directory, read by fun_time, genau, clipper
and the tray. Nothing here had a test before: every suite that touched these
functions substituted a lambda for them, so the mode file's exact contents, the
BOM stripping, the missing-file defaults and the blank-file repair were all
unpinned.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from osr2_broker.state_files import (
    ensure_genau_enabled_file,
    heartbeat_loop,
    read_genau_enabled,
    write_heartbeat,
    write_mode,
)

LOGGER = logging.getLogger("test.broker")


class TestWriteMode:
    def test_the_value_lands_verbatim(self, tmp_path: Path):
        """The tray reads "0"/"1" straight out of this file and genau's own
        readers compare it as text, so nothing may be added around it -- no
        newline, no BOM."""
        mode_file = tmp_path / "state" / "genau_mode.txt"

        write_mode(mode_file, "1", LOGGER)

        assert mode_file.read_bytes() == b"1"

    def test_the_state_directory_is_created_if_it_is_not_there(self, tmp_path: Path):
        """First run on a fresh machine: nothing has made state/ yet."""
        mode_file = tmp_path / "state" / "genau_mode.txt"

        write_mode(mode_file, "0", LOGGER)

        assert mode_file.exists()

    def test_a_write_that_cannot_land_is_logged_and_swallowed(self, tmp_path: Path):
        """Called from the protocol layer on every AUTO transition. A state
        directory that has gone away must not take the broker with it."""
        logger = MagicMock()

        write_mode(tmp_path, "1", logger)  # a directory, so the write cannot land

        logger.exception.assert_called_once()


class TestReadGenauEnabled:
    def test_a_file_that_is_not_there_reads_as_enabled(self, tmp_path: Path):
        """Genau is on until someone turns it off; a missing file is nobody
        having turned it off."""
        assert read_genau_enabled(tmp_path / "genau_enabled.txt") is True

    def test_a_zero_reads_as_disabled(self, tmp_path: Path):
        path = tmp_path / "genau_enabled.txt"
        path.write_text("0", encoding="utf-8")

        assert read_genau_enabled(path) is False

    def test_a_one_reads_as_enabled(self, tmp_path: Path):
        path = tmp_path / "genau_enabled.txt"
        path.write_text("1", encoding="utf-8")

        assert read_genau_enabled(path) is True

    def test_anything_that_is_not_a_zero_reads_as_enabled(self, tmp_path: Path):
        """The test is for the off switch, not for the on switch: a file left
        half-written, or holding something nobody here recognises, is not a
        decision to turn Genau off."""
        path = tmp_path / "genau_enabled.txt"
        path.write_text("yes please", encoding="utf-8")

        assert read_genau_enabled(path) is True

    def test_a_bom_and_surrounding_whitespace_do_not_hide_the_zero(self, tmp_path: Path):
        """PowerShell writes this file, and PowerShell leaves a BOM. Glued to
        the value it would read as enabled and Genau would be on against the
        user's wishes."""
        path = tmp_path / "genau_enabled.txt"
        path.write_bytes(b"\xef\xbb\xbf 0 \r\n")

        assert read_genau_enabled(path) is False

    def test_an_unreadable_file_reads_as_enabled(self, tmp_path: Path):
        assert read_genau_enabled(tmp_path) is True  # a directory


class TestEnsureGenauEnabledFile:
    def test_a_missing_file_is_seeded_enabled(self, tmp_path: Path):
        path = tmp_path / "state" / "genau_enabled.txt"

        ensure_genau_enabled_file(path, LOGGER)

        assert path.read_bytes() == b"1"

    def test_a_blank_file_is_repaired(self, tmp_path: Path):
        """A half-written file, or one a writer truncated and did not refill."""
        path = tmp_path / "genau_enabled.txt"
        path.write_text("  \r\n", encoding="utf-8")

        ensure_genau_enabled_file(path, LOGGER)

        assert path.read_bytes() == b"1"

    def test_a_file_holding_only_a_bom_counts_as_blank(self, tmp_path: Path):
        """A writer that opened the file, stamped the BOM and got no further."""
        path = tmp_path / "genau_enabled.txt"
        path.write_bytes(b"\xef\xbb\xbf")

        ensure_genau_enabled_file(path, LOGGER)

        assert path.read_bytes() == b"1"

    def test_a_deliberate_zero_is_left_exactly_as_it_was(self, tmp_path: Path):
        """The one case that must not be touched: seeding over a user's "0"
        would switch Genau back on at every broker start."""
        path = tmp_path / "genau_enabled.txt"
        path.write_text("0", encoding="utf-8")

        ensure_genau_enabled_file(path, LOGGER)

        assert path.read_bytes() == b"0"

    def test_a_failure_is_logged_and_swallowed(self, tmp_path: Path):
        logger = MagicMock()

        ensure_genau_enabled_file(tmp_path, logger)  # a directory

        logger.exception.assert_called_once()


class TestHeartbeat:
    def test_the_heartbeat_is_the_wall_clock_as_text(self, tmp_path: Path):
        heartbeat_file = tmp_path / "state" / "broker_heartbeat.txt"

        with patch("osr2_broker.state_files.time.time", return_value=123.45):
            write_heartbeat(heartbeat_file, LOGGER)

        assert heartbeat_file.read_text(encoding="utf-8") == "123.45"

    def test_the_loop_skips_the_write_while_the_session_is_disconnected(self, tmp_path: Path):
        """fun_time reads staleness off this file to decide the broker is dead,
        so a broker with no serial session must stop looking alive."""
        heartbeat_file = tmp_path / "broker_heartbeat.txt"
        stop = threading.Event()
        connected = threading.Event()
        ticks: list[float] = []

        def fake_sleep(seconds):
            ticks.append(seconds)
            if len(ticks) >= 3:
                stop.set()

        heartbeat_loop(heartbeat_file, stop, LOGGER, sleep=fake_sleep, connected=connected)

        assert not heartbeat_file.exists()
        assert ticks == [0.5, 0.5, 0.5], "fun_time's staleness window is sized off this cadence"

    def test_the_loop_writes_while_the_session_is_connected(self, tmp_path: Path):
        heartbeat_file = tmp_path / "broker_heartbeat.txt"
        stop = threading.Event()
        connected = threading.Event()
        connected.set()
        ticks: list[float] = []

        def fake_sleep(seconds):
            ticks.append(seconds)
            stop.set()

        heartbeat_loop(heartbeat_file, stop, LOGGER, sleep=fake_sleep, connected=connected)

        assert heartbeat_file.exists()
        assert ticks == [0.5]
