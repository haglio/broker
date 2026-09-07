"""The retry loop while the OSR2's port is away.

Every open against a port Windows does not have raises the same
SerialException.  Retried once a second with a traceback apiece, that wrote four
megabytes into the broker log in forty minutes -- rolling it three times, so the
outage erased every record that came before it and the one thing a reader came
for was the one thing gone.

These pin both halves of the answer: the loop waits on the port's return rather
than hammering the open, and a run of identical failures is reported once and
then only counted.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
import serial

from osr2_broker import app as broker_app
from osr2_broker.activity import ActivityStamp
from osr2_broker.ports import serial_port_present
from osr2_broker.session import BrokerSerialSession

MISSING_PORT = "could not open port COM4"


class _Recorder(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def recorded_logger():
    logger = logging.getLogger("test.osr2_broker.quiet_retry")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = _Recorder()
    logger.addHandler(handler)
    yield logger, handler
    logger.handlers.clear()


class _Port:
    def __init__(self, device: str) -> None:
        self.device = device


class TestWaitingForTheRealPort:
    def test_an_absent_port_is_waited_on_and_said_once(self, recorded_logger):
        logger, handler = recorded_logger
        answers = [False, False, False, True]

        with (
            patch.object(broker_app, "serial_port_present", side_effect=answers),
            patch.object(broker_app.time, "sleep"),
        ):
            came_back = broker_app.wait_for_real_port(
                "COM4", threading.Event(), logger, poll_seconds=0.0,
            )

        assert came_back is True
        warnings = [r for r in handler.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, "the outage is announced once, not once per poll"
        assert "COM4" in warnings[0].getMessage()
        assert [r.getMessage() for r in handler.records if r.levelno == logging.INFO] == [
            "COM4 is back; reconnecting"
        ]

    def test_a_present_port_is_not_waited_on_at_all(self, recorded_logger):
        logger, handler = recorded_logger
        with (
            patch.object(broker_app, "serial_port_present", return_value=True),
            patch.object(broker_app.time, "sleep") as slept,
        ):
            assert broker_app.wait_for_real_port("COM4", threading.Event(), logger) is True
        assert slept.call_args_list == []
        assert handler.records == []

    def test_a_stopping_broker_leaves_the_wait(self, recorded_logger):
        logger, _handler = recorded_logger
        stop = threading.Event()

        with (
            patch.object(broker_app, "serial_port_present", return_value=False),
            patch.object(broker_app.time, "sleep", side_effect=lambda _s: stop.set()),
        ):
            assert broker_app.wait_for_real_port("COM4", stop, logger, poll_seconds=0.0) is False


class TestSerialPortPresence:
    def test_enumeration_decides(self):
        with patch("osr2_broker.ports.iter_serial_ports",
                   return_value=[_Port("COM8"), _Port("com4")]):
            assert serial_port_present("COM4") is True
            assert serial_port_present("COM9") is False

    def test_an_empty_enumeration_says_present(self):
        """Nothing to enumerate and no pyserial look alike from here, and a
        broker that stopped retrying because it could not ask never returns."""
        with patch("osr2_broker.ports.iter_serial_ports", return_value=[]):
            assert serial_port_present("COM4") is True


def _session(logger, serial_factory) -> BrokerSerialSession:
    return BrokerSerialSession(
        serial_factory=serial_factory,
        virtual_port="COM8",
        real_port="COM4",
        baud=115200,
        broker_cmd_file=Path("broker_cmd.txt"),
        genau_enabled_file=Path("genau_enabled.txt"),
        auto_stale_timeout=5.0,
        stop_event=threading.Event(),
        broker_paused=threading.Event(),
        auto_mode=None,
        logger=logger,
        start_thread=lambda **_kw: None,
        consume_command=lambda _p: [],
        read_genau_enabled=lambda _p: False,
        rx_activity=ActivityStamp(Path("rx.txt")),
        tx_activity=ActivityStamp(Path("tx.txt")),
        connected_event=threading.Event(),
        is_retryable_error=broker_app.is_retryable_serial_error,
    )


class TestRepeatedOpenFailuresAreCollapsed:
    def test_one_traceback_then_a_count(self, recorded_logger):
        logger, handler = recorded_logger

        def always_missing(*_args, **_kwargs):
            raise serial.SerialException(MISSING_PORT)

        session = _session(logger, always_missing)
        session.FAILURE_SUMMARY_EVERY = 4
        for _ in range(9):
            assert session.run(udp_sock=None) is True

        tracebacks = [r for r in handler.records if r.exc_info is not None]
        assert len(tracebacks) == 1, "nine identical failures, one traceback"
        summaries = [
            r.getMessage() for r in handler.records
            if r.levelno == logging.WARNING and r.exc_info is None
        ]
        assert summaries == [
            f"Still failing to open or run the serial session (4 attempts): {MISSING_PORT}",
            f"Still failing to open or run the serial session (8 attempts): {MISSING_PORT}",
        ]

    def test_a_different_failure_gets_its_own_traceback(self, recorded_logger):
        logger, handler = recorded_logger
        faults = [
            serial.SerialException(MISSING_PORT),
            serial.SerialException(MISSING_PORT),
            PermissionError(13, "Access is denied"),
        ]

        def failing(*_args, **_kwargs):
            raise faults.pop(0)

        session = _session(logger, failing)
        for _ in range(3):
            session.run(udp_sock=None)

        assert len([r for r in handler.records if r.exc_info is not None]) == 2

    def test_a_session_that_opens_closes_out_the_run(self, recorded_logger):
        logger, handler = recorded_logger

        def always_missing(*_args, **_kwargs):
            raise serial.SerialException(MISSING_PORT)

        session = _session(logger, always_missing)
        session.run(udp_sock=None)
        session.run(udp_sock=None)

        class _Opened:
            dsr = True
            write_timeout = 0.1

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        session.serial_factory = lambda *_a, **_kw: _Opened()
        session.stop_event.set()  # the session loop sees it and returns at once
        session.run(udp_sock=None)

        assert [r.getMessage() for r in handler.records if r.levelno == logging.INFO] == [
            "Serial session opened after 2 failed attempt(s)"
        ]
