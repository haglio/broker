"""The files the broker publishes itself through.

Three names under the shared state directory, read by fun_time, genau, clipper
and the tray.  The reading and the writing are app_support.file_channel's and
pinned there, file by file; what is pinned here is the broker's side of each:
what it writes, when, and what it does when it cannot.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from osr2_broker.state_files import heartbeat_loop, write_heartbeat, write_mode

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

        logger.error.assert_called_once()


class TestHeartbeat:
    def test_the_heartbeat_is_the_wall_clock_as_text(self, tmp_path: Path):
        heartbeat_file = tmp_path / "state" / "broker_heartbeat.txt"

        with patch("app_support.file_channel.time.time", return_value=123.45):
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
