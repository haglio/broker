from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from osr2_broker.protocol import BrokerAutoController, parse_auto_transition


def test_parse_auto_transition_detects_auto_mode_lines():
    assert parse_auto_transition("freeMode is on!") is True
    assert parse_auto_transition("Auto mode is off!") is False
    assert parse_auto_transition("StrokeName: Demo, PatternDuration: 2.0") is None


def test_set_auto_writes_mode_and_sends_udp_messages():
    writes: list[tuple[Path, str]] = []
    sends: list[str] = []
    logger = MagicMock()
    controller = BrokerAutoController(
        state_file=Path("mode.txt"),
        udp_host="127.0.0.1",
        udp_port=9001,
        logger=logger,
        write_mode=lambda path, value, _logger: writes.append((path, value)),
        udp_send=lambda _sock, _host, _port, msg: sends.append(msg),
    )

    controller.set_auto(object(), True)

    assert controller.is_active is True
    assert writes == [(Path("mode.txt"), "1")]
    assert sends == ["AUTO 1", "BPM 87"]
    logger.info.assert_called_once_with("AUTO %s", "ON")


def test_set_auto_skips_transition_log_when_value_is_unchanged():
    logger = MagicMock()
    controller = BrokerAutoController(
        state_file=Path("mode.txt"),
        udp_host="127.0.0.1",
        udp_port=9001,
        logger=logger,
        write_mode=lambda _path, _value, _logger: None,
        udp_send=lambda _sock, _host, _port, _msg: None,
    )

    controller.set_auto(object(), False)
    controller.set_auto(object(), False)

    assert logger.info.call_count == 0


def test_handle_line_infers_auto_mode_from_bpm_message():
    sends: list[str] = []
    controller = BrokerAutoController(
        state_file=Path("mode.txt"),
        udp_host="127.0.0.1",
        udp_port=9001,
        logger=MagicMock(),
        write_mode=lambda _path, _value, _logger: None,
        udp_send=lambda _sock, _host, _port, msg: sends.append(msg),
    )

    controller.handle_line(object(), "bpm 120, beats 4")

    assert controller.is_active is True
    assert "AUTO 1" in sends


def test_handle_line_infers_auto_mode_from_motion_message():
    sends: list[str] = []
    controller = BrokerAutoController(
        state_file=Path("mode.txt"),
        udp_host="127.0.0.1",
        udp_port=9001,
        logger=MagicMock(),
        write_mode=lambda _path, _value, _logger: None,
        udp_send=lambda _sock, _host, _port, msg: sends.append(msg),
    )

    controller.handle_line(object(), "StrokeName: Pull, PatternDuration: 2.0")

    assert controller.is_active is True
    assert "AUTO 1" in sends


def test_handle_line_sends_bpm_and_sync_messages():
    """Every motion and BPM line says auto is on, and only the first is news.
    Each used to rewrite the mode file and resend AUTO and the seed BPM
    -- ahead of the real tempo on the same line -- at the device's line rate
    (bug 29)."""
    writes: list[tuple[Path, str]] = []
    sends: list[str] = []
    controller = BrokerAutoController(
        state_file=Path("mode.txt"),
        udp_host="127.0.0.1",
        udp_port=9001,
        logger=MagicMock(),
        write_mode=lambda path, value, _logger: writes.append((path, value)),
        udp_send=lambda _sock, _host, _port, msg: sends.append(msg),
    )

    controller.handle_line(object(), "StrokeName: Pull, PatternDuration: 2.0 bpm 120, beats 4 continue StrokeName:")
    controller.handle_line(object(), "bpm 121, beats 4")

    assert writes == [(Path("mode.txt"), "1")]
    assert sends == [
        "AUTO 1",
        "BPM 87",
        "SYNC",
        "BPM 120",
        "SYNC",
        "BPM 121",
    ]


def test_handle_line_applies_auto_transition():
    sends: list[str] = []
    controller = BrokerAutoController(
        state_file=Path("mode.txt"),
        udp_host="127.0.0.1",
        udp_port=9001,
        logger=MagicMock(),
        write_mode=lambda _path, _value, _logger: None,
        udp_send=lambda _sock, _host, _port, msg: sends.append(msg),
    )

    controller.handle_line(object(), "Auto mode is on!")

    assert controller.is_active is True
    assert sends[:2] == ["AUTO 1", "BPM 87"]


