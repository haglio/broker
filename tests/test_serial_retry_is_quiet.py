"""The retry loop while the OSR2's port is away.

Every open against a port Windows does not have raises the same
SerialException.  Retried once a second with a traceback apiece, that wrote four
megabytes into the broker log in forty minutes -- rolling it three times, so the
outage erased every record that came before it and the one thing a reader came
for was the one thing gone.

These pin one half of the answer, that a run of identical failures is reported
once and then only counted; tests/test_osr2_port.py pins the other, that the
loop waits for the OSR2 to be plugged in rather than hammering the open.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import serial

from osr2_broker import app as broker_app
from osr2_broker.activity import ActivityStamp
from osr2_broker.session import BrokerSerialSession
from tests.conftest import FakePowerOn

MISSING_PORT = "could not open port COM4"


def _session(logger, serial_factory) -> BrokerSerialSession:
    return BrokerSerialSession(
        serial_factory=serial_factory,
        virtual_port="COM8",
        baud=115200,
        broker_cmd_file=Path("broker_cmd.txt"),
        device_on=lambda: True,
        stop_event=threading.Event(),
        broker_paused=threading.Event(),
        auto_mode=None,
        logger=logger,
        start_thread=lambda **_kw: None,
        consume_command=lambda _p: [],
        rx_activity=ActivityStamp(Path("rx.txt")),
        tx_activity=ActivityStamp(Path("tx.txt")),
        connected_event=threading.Event(),
        is_retryable_error=broker_app.is_retryable_serial_error,
        power_on=FakePowerOn(),
    )


class TestRepeatedOpenFailuresAreCollapsed:
    def test_one_traceback_then_a_count(self, recorded_logger):
        logger, handler = recorded_logger

        def always_missing(*_args, **_kwargs):
            raise serial.SerialException(MISSING_PORT)

        session = _session(logger, always_missing)
        session.FAILURE_SUMMARY_EVERY = 4
        for _ in range(9):
            assert session.run(udp_sock=None, osr2_port="COM4") is True

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
            session.run(udp_sock=None, osr2_port="COM4")

        assert len([r for r in handler.records if r.exc_info is not None]) == 2

    def test_a_session_that_opens_closes_out_the_run(self, recorded_logger):
        logger, handler = recorded_logger

        def always_missing(*_args, **_kwargs):
            raise serial.SerialException(MISSING_PORT)

        session = _session(logger, always_missing)
        session.run(udp_sock=None, osr2_port="COM4")
        session.run(udp_sock=None, osr2_port="COM4")

        class _Opened:
            dsr = True
            write_timeout = 0.1

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        session.serial_factory = lambda *_a, **_kw: _Opened()
        session.stop_event.set()  # the session loop sees it and returns at once
        session.run(udp_sock=None, osr2_port="COM4")

        assert [r.getMessage() for r in handler.records if r.levelno == logging.INFO] == [
            "Serial session opened after 2 failed attempt(s)"
        ]
