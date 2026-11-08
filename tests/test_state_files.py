from __future__ import annotations

import logging
import threading
from pathlib import Path
from unittest.mock import MagicMock

from app_support.testing import file_channel_clock_at

from osr2_broker.state_files import heartbeat_loop, write_heartbeat, write_mode

LOGGER = logging.getLogger("test.broker")


class TestWriteMode:
    def test_the_value_lands_verbatim_genau_s_readers_compare_it_as_text(self, tmp_path: Path):
        mode_file = tmp_path / "state" / "broker_mode.txt"

        write_mode(mode_file, "1", LOGGER)

        assert mode_file.read_bytes() == b"1"

    def test_the_state_directory_is_created_if_it_is_not_there(self, tmp_path: Path):
        mode_file = tmp_path / "state" / "broker_mode.txt"

        write_mode(mode_file, "0", LOGGER)

        assert mode_file.exists()

    def test_a_write_that_cannot_land_is_logged_and_swallowed_the_writers_are_the_threads_carrying_the_serial_traffic(self, tmp_path: Path):
        logger = MagicMock()

        write_mode(tmp_path, "1", logger)

        logger.error.assert_called_once()

    def test_the_mode_is_published_whole_a_poller_catching_a_truncating_write_would_read_blank_as_controlled(self, tmp_path: Path):
        published: list[tuple[Path, str]] = []

        def publish(path: Path, text: str) -> bool:
            published.append((path, text))
            return True

        write_mode(tmp_path / "broker_mode.txt", "1", LOGGER, publish=publish)

        assert published == [(tmp_path / "broker_mode.txt", "1")]


class TestHeartbeat:
    def test_the_heartbeat_is_the_wall_clock_as_text_other_apps_read_these_files_as_a_wire_format(self, tmp_path: Path):
        heartbeat_file = tmp_path / "state" / "broker_heartbeat.txt"

        with file_channel_clock_at(123.45):
            write_heartbeat(heartbeat_file, LOGGER)

        assert heartbeat_file.read_text(encoding="utf-8") == "123.45"

    def test_the_loop_skips_the_write_while_the_session_is_disconnected(self, tmp_path: Path):
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
