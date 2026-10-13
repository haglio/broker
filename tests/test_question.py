"""Asking the OSR2 a question only a switched-on device can answer."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from app_support.file_channel import publish_stamp, stamp_age
from app_support.osr2_device import ANSWERS_ONCE_OFF_S, switched_on
from app_support.state_files import OSR2_SERIAL_ANSWER, OSR2_SERIAL_RX

from osr2_broker.question import DeviceQuestion


def _build(tmp_path: Path, clock: list[float], *, wall: float = 1_000.0,
           logger=None) -> DeviceQuestion:
    return DeviceQuestion(answer_file=tmp_path / OSR2_SERIAL_ANSWER,
                          monotonic=lambda: clock[0], logger=logger or MagicMock(),
                          wall_clock=lambda: wall)


def test_the_first_question_is_due_at_once(tmp_path):
    assert _build(tmp_path, [10.0]).due()


def test_the_next_question_waits_out_the_interval(tmp_path):
    clock = [10.0]
    question = _build(tmp_path, clock)
    question.asked()

    clock[0] = 10.0 + DeviceQuestion.EVERY_SECONDS - 0.01
    assert not question.due()
    clock[0] = 10.0 + DeviceQuestion.EVERY_SECONDS
    assert question.due()


def test_an_answer_is_stamped_where_the_apps_read_it(tmp_path):
    _build(tmp_path, [10.0], wall=1_000.0).heard("TCode v0.3")

    assert stamp_age(tmp_path / OSR2_SERIAL_ANSWER, now=1_000.5) == pytest.approx(0.5)


@pytest.mark.parametrize("line", ["StrokeName: Demo, PatternDuration: 2.0", "Auto mode is on!",
                                  "TCode task started"])
def test_whatever_else_the_device_says_is_no_answer(tmp_path, line):
    _build(tmp_path, [10.0]).heard(line)

    assert stamp_age(tmp_path / OSR2_SERIAL_ANSWER) is None


def test_the_first_answer_is_logged_with_what_the_device_said(tmp_path):
    logger = MagicMock()
    question = _build(tmp_path, [10.0], logger=logger)

    question.heard("TCode v0.3")
    question.heard("TCode v0.3")

    logger.info.assert_called_once()
    assert "TCode v0.3" in logger.info.call_args.args


def test_a_device_that_talks_but_never_answers_is_logged_once_with_what_it_says(tmp_path):
    logger = MagicMock()
    question = _build(tmp_path, [10.0], logger=logger)
    for _ in range(DeviceQuestion.UNANSWERED_BEFORE_WARNING - 1):
        question.asked()
    question.heard("Example line")
    logger.warning.assert_not_called()

    question.asked()
    question.heard("Example line")
    question.heard("Example line")

    logger.warning.assert_called_once()
    assert "Example line" in logger.warning.call_args.args


def test_a_device_that_answers_is_never_reported_for_what_else_it_says(tmp_path):
    logger = MagicMock()
    question = _build(tmp_path, [10.0], logger=logger)
    for _ in range(DeviceQuestion.UNANSWERED_BEFORE_WARNING):
        question.asked()
        question.heard("TCode v0.3")

    question.heard("Example line")

    logger.warning.assert_not_called()


def test_standing_down_leaves_the_device_judged_by_what_it_says_unasked(tmp_path):
    question = _build(tmp_path, [10.0], wall=1_000.0)
    question.heard("TCode v0.3")
    publish_stamp(tmp_path / OSR2_SERIAL_RX, 1_000.0)

    question.stand_down()

    assert switched_on(tmp_path, now=1_000.0 + ANSWERS_ONCE_OFF_S + 1.0)


def test_standing_down_again_writes_nothing_until_the_questions_resume(tmp_path):
    question = _build(tmp_path, [10.0])
    answer = tmp_path / OSR2_SERIAL_ANSWER
    question.stand_down()
    answer.unlink()

    question.stand_down()
    assert not answer.exists()

    question.asked()
    question.stand_down()
    assert answer.exists()
