"""Saying who drove the OSR2 and when.

The log carried nothing about the device actually moving, so a report of "it
started too early" could only be answered by guessing which of the three writers
it was. These pin the shape of the answer: a line at each end of a run, naming
the source, and no line per write.
"""
from __future__ import annotations

import logging

import pytest

from osr2_broker.motion_log import HOLD, MFP, UDP, MotionLog


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
def log():
    logger = logging.getLogger("test.osr2_broker.motion")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = _Recorder()
    logger.addHandler(handler)
    clock = _Clock()
    yield MotionLog(logger=logger, monotonic=clock), handler, clock
    logger.handlers.clear()


class TestARunOfWrites:
    def test_it_is_one_line_at_each_end_not_one_per_write(self, log):
        motion, said, clock = log

        for _ in range(50):
            motion.wrote(UDP)
            clock.now += 0.1
        clock.now += 5.0
        motion.tick()

        assert said.said == [
            f"OSR2 driven by {UDP}",
            f"OSR2 quiet after 4.9s of {UDP}",
        ]

    def test_a_second_run_says_how_long_the_device_was_still(self, log):
        """The number the whole question turns on: how long before the motion
        he felt did nothing reach the device."""
        motion, said, clock = log
        motion.wrote(UDP)
        clock.now += 30.0
        motion.tick()

        motion.wrote(UDP)

        assert said.said[-1] == f"OSR2 driven by {UDP}, quiet for 30.0s before that"

    def test_the_tick_alone_closes_a_run_out(self, log):
        """Nothing writes when the device stops, so the end of a run can only be
        noticed by the beat that keeps running.  The length reported is the
        writes' own span, not the wait that revealed it was over."""
        motion, said, clock = log
        motion.wrote(MFP)
        clock.now += 1.0
        motion.wrote(MFP)
        clock.now += 1.0
        motion.tick()
        assert len(said.said) == 1

        clock.now += 5.0
        motion.tick()

        assert said.said[-1] == f"OSR2 quiet after 1.0s of {MFP}"

    def test_a_closed_run_is_not_closed_twice(self, log):
        motion, said, clock = log
        motion.wrote(HOLD)
        clock.now += 10.0
        motion.tick()
        motion.tick()
        motion.tick()

        assert said.said.count(f"OSR2 quiet after 0.0s of {HOLD}") == 1


class TestHandingTheDeviceOver:
    def test_a_new_source_ends_the_old_run_and_opens_its_own(self, log):
        """Two writers inside one stretch of motion is the case a single
        'the device is moving' flag could not tell apart."""
        motion, said, clock = log
        motion.wrote(MFP)
        clock.now += 1.0
        motion.wrote(MFP)

        motion.wrote(UDP)

        assert said.said == [
            f"OSR2 driven by {MFP}",
            f"OSR2 quiet after 1.0s of {MFP}",
            f"OSR2 driven by {UDP}",
        ]

    def test_the_sources_are_named_for_a_reader_not_for_the_code(self, log):
        assert (MFP, UDP, HOLD) == ("MFP", "T-Code UDP", "a hold")
