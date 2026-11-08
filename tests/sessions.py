from __future__ import annotations

import logging
import threading
import time
from dataclasses import fields
from pathlib import Path

from osr2_broker.session import (
    BrokerSerialSession,
    DeviceWatches,
    Senders,
    SerialLink,
    SessionControls,
    SessionRuntime,
)
from tests.conftest import FakePowerOn, idle_slot


class StampSpy:
    def __init__(self):
        self.marks = 0

    def mark(self) -> None:
        self.marks += 1


class NotActuallyRunningSoNoThreadIsLeftSpinning:
    def join(self, timeout=None) -> None:
        pass


def _no_port(*_args, **_kwargs):
    raise AssertionError("this test opens no serial port")


def make_session(**given) -> BrokerSerialSession:
    def part(kind, **defaults):
        named = {field.name for field in fields(kind)}
        return kind(**{**defaults, **{name: given[name] for name in named & given.keys()}})

    return BrokerSerialSession(
        link=part(SerialLink, serial_factory=_no_port, virtual_port="COM15", baud=115200,
                  is_retryable_error=lambda _exc: False),
        controls=part(SessionControls, broker_cmd_file=Path("broker.cmd"),
                      consume_command=lambda _path: [], stop_event=threading.Event(),
                      broker_paused=threading.Event(), connected_event=threading.Event()),
        watches=part(DeviceWatches, device_on=lambda: True, rx_activity=StampSpy(),
                     tx_activity=StampSpy(), power_on=FakePowerOn()),
        runtime=part(SessionRuntime, logger=logging.getLogger("tests.sessions"),
                     start_thread=lambda **_kw: NotActuallyRunningSoNoThreadIsLeftSpinning(),
                     monotonic=time.monotonic, sleep=time.sleep),
        senders=part(Senders, auto_mode=None, slot=idle_slot()),
    )
