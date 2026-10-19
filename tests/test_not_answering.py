from __future__ import annotations

import logging
from unittest.mock import patch

from app_support.file_channel import stamp_age

from osr2_broker import not_answering
from osr2_broker.not_answering import NotAnsweringWatch


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _watch(tmp_path, clock: _Clock, logger=None) -> NotAnsweringWatch:
    return NotAnsweringWatch(stamp_file=tmp_path / "osr2_not_answering.txt", monotonic=clock,
                             logger=logger or logging.getLogger("test.not_answering"))


def _tick_for(watch: NotAnsweringWatch, clock: _Clock, seconds: float, *, driving: bool) -> None:
    end = clock.now + seconds
    while clock.now < end:
        clock.now += 0.5
        watch.tick(driving=driving)


def test_an_osr2_driven_for_minutes_without_a_word_back_is_said_not_to_answer(tmp_path):
    clock = _Clock()
    watch = _watch(tmp_path, clock)

    _tick_for(watch, clock, NotAnsweringWatch.DRIVEN_S + 1, driving=True)

    assert stamp_age(tmp_path / "osr2_not_answering.txt") is not None


def test_a_shorter_drive_without_a_word_back_says_nothing(tmp_path):
    clock = _Clock()
    watch = _watch(tmp_path, clock)

    _tick_for(watch, clock, NotAnsweringWatch.DRIVEN_S - 1, driving=True)

    assert stamp_age(tmp_path / "osr2_not_answering.txt") is None


def test_a_word_from_the_osr2_starts_the_count_again(tmp_path):
    clock = _Clock()
    watch = _watch(tmp_path, clock)
    _tick_for(watch, clock, NotAnsweringWatch.DRIVEN_S - 10, driving=True)

    watch.heard()
    _tick_for(watch, clock, 20, driving=True)

    assert stamp_age(tmp_path / "osr2_not_answering.txt") is None


def test_only_the_time_spent_driving_it_counts(tmp_path):
    clock = _Clock()
    watch = _watch(tmp_path, clock)

    _tick_for(watch, clock, 3600, driving=False)
    _tick_for(watch, clock, 10, driving=True)

    assert stamp_age(tmp_path / "osr2_not_answering.txt") is None


def test_a_long_rest_from_driving_starts_the_count_again(tmp_path):
    clock = _Clock()
    watch = _watch(tmp_path, clock)
    _tick_for(watch, clock, NotAnsweringWatch.DRIVEN_S - 10, driving=True)

    _tick_for(watch, clock, NotAnsweringWatch.FORGOTTEN_AFTER_S + 1, driving=False)
    _tick_for(watch, clock, 20, driving=True)

    assert stamp_age(tmp_path / "osr2_not_answering.txt") is None


def test_the_word_is_renewed_about_once_a_second_rather_than_every_tick(tmp_path):
    clock = _Clock()
    watch = _watch(tmp_path, clock)
    _tick_for(watch, clock, NotAnsweringWatch.DRIVEN_S + 1, driving=True)

    with patch.object(not_answering, "publish_stamp") as renewed:
        for _ in range(8):
            clock.now += 0.25
            watch.tick(driving=True)

    assert renewed.call_count == 2


def test_the_broker_log_says_when_the_osr2_stops_and_starts_answering(tmp_path, recorded_logger):
    logger, handler = recorded_logger
    clock = _Clock()
    watch = _watch(tmp_path, clock, logger)

    _tick_for(watch, clock, NotAnsweringWatch.DRIVEN_S + 5, driving=True)
    watch.heard()
    watch.tick(driving=True)

    assert [r.getMessage() for r in handler.records] == [
        "The OSR2 has said nothing through 3 minutes of driving: counted as not answering",
        "The OSR2 is heard again",
    ]


def test_a_long_rest_from_driving_ends_the_word_and_says_so(tmp_path, recorded_logger):
    logger, handler = recorded_logger
    clock = _Clock()
    watch = _watch(tmp_path, clock, logger)
    _tick_for(watch, clock, NotAnsweringWatch.DRIVEN_S + 5, driving=True)

    _tick_for(watch, clock, NotAnsweringWatch.FORGOTTEN_AFTER_S + 1, driving=False)
    _tick_for(watch, clock, NotAnsweringWatch.DRIVEN_S + 5, driving=True)

    assert [r.getMessage() for r in handler.records] == [
        "The OSR2 has said nothing through 3 minutes of driving: counted as not answering",
        "The OSR2 has not been driven for 10 minutes: no longer counted as not answering",
        "The OSR2 has said nothing through 3 minutes of driving: counted as not answering",
    ]
