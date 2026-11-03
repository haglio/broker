from __future__ import annotations

import logging

import pytest

from osr2_broker.motion_log import (
    HOLD,
    MFP,
    UDP,
    driven_from_outside,
    dropped_udp_log,
    motion_log,
    tcode_from,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class _Recorder(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.said: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.said.append(record.getMessage())


@pytest.fixture
def heard():
    logger = logging.getLogger("test.osr2_broker.motion")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = _Recorder()
    logger.addHandler(handler)
    yield logger, handler
    logger.handlers.clear()


@pytest.fixture
def log(heard):
    logger, handler = heard
    clock = _Clock()
    return motion_log(logger=logger, monotonic=clock), handler, clock


@pytest.fixture
def dropped(heard):
    logger, handler = heard
    clock = _Clock()
    return dropped_udp_log(logger=logger, monotonic=clock), handler, clock


class TestARunOfWrites:
    def test_it_is_one_line_at_each_end_not_one_per_write(self, log):
        motion, said, clock = log

        for _ in range(50):
            motion.happened(UDP)
            clock.now += 0.1
        clock.now += 5.0
        motion.tick()

        assert said.said == [
            f"OSR2 driven by {UDP}",
            f"OSR2 quiet after 4.9s of {UDP}",
        ]

    def test_a_second_run_says_how_long_the_device_was_still(self, log):
        motion, said, clock = log
        motion.happened(UDP)
        clock.now += 30.0
        motion.tick()

        motion.happened(UDP)

        assert said.said[-1] == f"OSR2 driven by {UDP}, quiet for 30.0s before that"

    def test_the_tick_alone_closes_a_run_out(self, log):
        motion, said, clock = log
        motion.happened(MFP)
        clock.now += 1.0
        motion.happened(MFP)
        clock.now += 1.0
        motion.tick()
        assert len(said.said) == 1

        clock.now += 5.0
        motion.tick()

        assert said.said[-1] == f"OSR2 quiet after 1.0s of {MFP}"

    def test_a_closed_run_is_not_closed_twice(self, log):
        motion, said, clock = log
        motion.happened(HOLD)
        clock.now += 10.0
        motion.tick()
        motion.tick()
        motion.tick()

        assert said.said.count(f"OSR2 quiet after 0.0s of {HOLD}") == 1


class TestHandingTheDeviceOver:
    def test_a_new_source_ends_the_old_run_and_opens_its_own(self, log):
        motion, said, clock = log
        motion.happened(MFP)
        clock.now += 1.0
        motion.happened(MFP)

        motion.happened(UDP)

        assert said.said == [
            f"OSR2 driven by {MFP}",
            f"OSR2 quiet after 1.0s of {MFP}",
            f"OSR2 driven by {UDP}",
        ]

    def test_the_sources_are_named_for_a_reader_not_for_the_code(self, log):
        assert (MFP, UDP, HOLD) == ("MFP", "T-Code UDP", "a hold")
        assert tcode_from("portrait") == "T-Code from portrait"


class TestWhetherSomethingIsDrivingTheOsr2:
    @pytest.mark.parametrize("source", [MFP, UDP, tcode_from("portrait")])
    def test_a_driver_writing_is_driving_it_until_it_falls_quiet(self, log, source):
        motion, _said, clock = log

        motion.happened(source)
        clock.now += 1.0
        assert driven_from_outside(motion)

        clock.now += 1.5
        assert not driven_from_outside(motion)

    def test_the_brokers_own_hold_is_not_a_driver(self, log):
        motion, _said, _clock = log

        motion.happened(HOLD)

        assert not driven_from_outside(motion)


class TestUdpDroppedForTheSlot:
    def test_a_run_of_dropped_lines_is_told_at_its_two_ends_with_how_many(self, dropped):
        held_off, said, clock = dropped

        for _ in range(3):
            held_off.happened("portrait")
            clock.now += 0.1
        clock.now += 5.0
        held_off.tick()

        assert said.said == [
            "Dropping T-Code UDP while the OSR2 is portrait's",
            "Dropped 3 T-Code UDP lines while the OSR2 was portrait's",
        ]

    def test_one_dropped_line_is_one_line(self, dropped):
        held_off, said, clock = dropped

        held_off.happened("portrait")
        clock.now += 5.0
        held_off.tick()

        assert said.said[-1] == "Dropped 1 T-Code UDP line while the OSR2 was portrait's"

    def test_the_slot_changing_hands_ends_one_run_and_starts_the_next(self, dropped):
        held_off, said, _clock = dropped

        held_off.happened("portrait")
        held_off.happened("main")

        assert said.said == [
            "Dropping T-Code UDP while the OSR2 is portrait's",
            "Dropped 1 T-Code UDP line while the OSR2 was portrait's",
            "Dropping T-Code UDP while the OSR2 is main's",
        ]
