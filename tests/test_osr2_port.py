from __future__ import annotations

import logging
import threading
from types import SimpleNamespace
from unittest.mock import patch

from app_support.file_channel import stamp_age

from osr2_broker import osr2_port


def _usb(device: str, vid: int, pid: int) -> SimpleNamespace:
    return SimpleNamespace(device=device, vid=vid, pid=pid)


def _not_usb(device: str) -> SimpleNamespace:
    return SimpleNamespace(device=device, vid=None, pid=None)


THE_OSR2 = (0x1A86, 0x7523)


class TestFindingTheOsr2:
    def test_the_osr2_is_the_usb_adapter_of_its_kind_among_the_machines_ports(self):
        with patch.object(osr2_port, "iter_serial_ports", return_value=[
            _not_usb("COM1"), _usb("COM4", *THE_OSR2), _not_usb("COM7"), _not_usb("COM8"),
        ]):
            assert osr2_port.osr2_adapters() == ["COM4"]


def _stamp(tmp_path):
    return tmp_path / "osr2_not_found.txt"


class TestWaitingForTheOsr2:
    def test_an_unplugged_osr2_is_waited_on_and_said_once(self, recorded_logger, tmp_path):
        logger, handler = recorded_logger
        plugged_in = [[], [], [], ["COM5"]]

        with (
            patch.object(osr2_port, "osr2_adapters", side_effect=plugged_in),
            patch.object(osr2_port.time, "sleep"),
        ):
            found = osr2_port.wait_for_the_osr2(threading.Event(), logger, not_found=_stamp(tmp_path), poll_seconds=0.0)

        assert found == "COM5"
        warnings = [r for r in handler.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, "the outage is announced once, not once per poll"
        assert "plugged in" in warnings[0].getMessage()
        assert [r.getMessage() for r in handler.records if r.levelno == logging.INFO] == [
            "The OSR2 is plugged in on COM5"
        ]

    def test_a_plugged_in_osr2_is_not_waited_on_at_all(self, recorded_logger, tmp_path):
        logger, _handler = recorded_logger
        with (
            patch.object(osr2_port, "osr2_adapters", return_value=["COM4"]),
            patch.object(osr2_port.time, "sleep") as slept,
        ):
            assert osr2_port.wait_for_the_osr2(threading.Event(), logger, not_found=_stamp(tmp_path)) == "COM4"
        assert slept.call_args_list == []

    def test_finding_the_osr2_where_the_last_session_had_it_says_nothing(
        self, recorded_logger, tmp_path,
    ):
        logger, handler = recorded_logger
        with patch.object(osr2_port, "osr2_adapters", return_value=["COM4"]):
            assert osr2_port.wait_for_the_osr2(
                threading.Event(), logger, not_found=_stamp(tmp_path), last_port="COM4") == "COM4"
        assert handler.records == [], "a session retried every second is no news"

    def test_two_adapters_of_its_kind_are_never_guessed_between(self, recorded_logger, tmp_path):
        logger, handler = recorded_logger
        plugged_in = [["COM4", "COM6"], ["COM4", "COM6"], ["COM6"]]

        with (
            patch.object(osr2_port, "osr2_adapters", side_effect=plugged_in),
            patch.object(osr2_port.time, "sleep"),
        ):
            found = osr2_port.wait_for_the_osr2(threading.Event(), logger, not_found=_stamp(tmp_path), poll_seconds=0.0)

        assert found == "COM6"
        warnings = [r.getMessage() for r in handler.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "COM4" in warnings[0]
        assert "COM6" in warnings[0]

    def test_a_second_adapter_plugged_in_leaves_the_osr2_where_it_was(self, recorded_logger, tmp_path):
        logger, handler = recorded_logger
        with patch.object(osr2_port, "osr2_adapters", return_value=["COM4", "COM6"]):
            assert osr2_port.wait_for_the_osr2(
                threading.Event(), logger, not_found=_stamp(tmp_path), last_port="COM6") == "COM6"
        assert handler.records == []

    def test_a_stopping_broker_leaves_the_wait(self, recorded_logger, tmp_path):
        logger, _handler = recorded_logger
        stop = threading.Event()

        with (
            patch.object(osr2_port, "osr2_adapters", return_value=[]),
            patch.object(osr2_port.time, "sleep", side_effect=lambda _s: stop.set()),
        ):
            assert osr2_port.wait_for_the_osr2(stop, logger, not_found=_stamp(tmp_path), poll_seconds=0.0) is None

    def test_while_no_osr2_is_found_the_broker_says_so_where_every_app_reads_it(
        self, recorded_logger, tmp_path,
    ):
        logger, _handler = recorded_logger
        plugged_in = [[], ["COM5"]]

        with (
            patch.object(osr2_port, "osr2_adapters", side_effect=plugged_in),
            patch.object(osr2_port.time, "sleep"),
        ):
            osr2_port.wait_for_the_osr2(threading.Event(), logger, not_found=_stamp(tmp_path),
                                        poll_seconds=0.0)

        assert stamp_age(_stamp(tmp_path)) is not None

    def test_an_osr2_found_at_once_leaves_nothing_said(self, recorded_logger, tmp_path):
        logger, _handler = recorded_logger
        with patch.object(osr2_port, "osr2_adapters", return_value=["COM4"]):
            osr2_port.wait_for_the_osr2(threading.Event(), logger, not_found=_stamp(tmp_path))

        assert not _stamp(tmp_path).exists()
