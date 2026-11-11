from __future__ import annotations

import inspect
import logging
import threading
from pathlib import Path
from unittest.mock import MagicMock

from app_support.file_channel import publish_whole
from app_support.testing import file_channel_clock_at

from osr2_broker.state_files import heartbeat_loop, write_mode

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
        assert inspect.signature(write_mode).parameters["publish"].default is publish_whole


class TestHeartbeat:
    def test_the_heartbeat_is_the_wall_clock_as_text_other_apps_read_these_files_as_a_wire_format(self, tmp_path: Path):
        heartbeat_file = tmp_path / "state" / "broker_heartbeat.txt"

        stop, connected = threading.Event(), threading.Event()
        connected.set()

        with file_channel_clock_at(123.45):
            heartbeat_loop(heartbeat_file, stop, LOGGER, connected=connected, sleep=lambda seconds: stop.set())

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


def _beats(landed: list[bool], caplog) -> list[tuple[str, str]]:
    stop, connected = threading.Event(), threading.Event()
    connected.set()
    outcomes, now = iter(landed), [0.0]

    def publish(path: Path, *, attempts: int, delay_s: float) -> bool:
        return next(outcomes)

    def sleep(seconds: float) -> None:
        now[0] += seconds
        if len(landed) * 0.5 <= now[0]:
            stop.set()

    with caplog.at_level(logging.INFO, logger=LOGGER.name):
        heartbeat_loop(Path("broker_heartbeat.txt"), stop, LOGGER, connected=connected, sleep=sleep,
                       clock=lambda: now[0], publish=publish)
    return [(record.levelname, record.getMessage()) for record in caplog.records]


class TestAHeartbeatThatDoesNotLand:
    def test_a_few_beats_lost_while_the_stamp_is_still_fresh_to_its_readers_are_not_an_error(self, caplog):
        assert _beats([True, False, False, False, False, False, True], caplog) == []

    def test_beats_lost_until_the_readers_count_the_broker_stopped_are_one_error_and_its_return_one_line_of_news(
            self, caplog):
        said = _beats([True] + [False] * 12 + [True, True], caplog)

        assert [level for level, _ in said] == ["ERROR", "INFO"]
        assert "count the broker as stopped" in said[0][1]

    def test_a_reader_holding_the_file_has_most_of_a_beat_to_let_go_before_the_beat_is_lost(self):
        asked = {}

        def publish(path: Path, *, attempts: int, delay_s: float) -> bool:
            asked.update(attempts=attempts, delay_s=delay_s)
            return True

        stop, connected = threading.Event(), threading.Event()
        connected.set()
        heartbeat_loop(Path("broker_heartbeat.txt"), stop, LOGGER, connected=connected,
                       sleep=lambda seconds: stop.set(), publish=publish)

        assert 0.3 <= asked["attempts"] * asked["delay_s"] < 0.5
