"""COM-level broker tests.

These tests wire up the real BrokerAutoController and BrokerSerialSession
together with mocked serial (COM) ports, verifying the full flow from
serial data arriving on the device port through protocol parsing to
state-file writes and UDP message emission.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app_support.threading_utils import wait_until
from osr2_broker.protocol import BrokerAutoController
from osr2_broker.session import BrokerSerialSession


class FakeSerialPort:
    def __init__(self):
        self._rx_buf = bytearray()
        self._tx_buf = bytearray()
        self._lock = threading.Lock()
        self._closed = False

    def inject(self, data: bytes) -> None:
        with self._lock:
            self._rx_buf.extend(data)

    @property
    def tx_data(self) -> bytes:
        with self._lock:
            return bytes(self._tx_buf)

    @property
    def in_waiting(self) -> int:
        with self._lock:
            return len(self._rx_buf)

    def read(self, size: int = 1) -> bytes:
        with self._lock:
            chunk = bytes(self._rx_buf[:size])
            del self._rx_buf[:size]
            return chunk

    def write(self, data: bytes) -> None:
        with self._lock:
            self._tx_buf.extend(data)

    def close(self):
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


class _FakeClock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class _Stack:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _start_real_thread(target, args, name):
    t = threading.Thread(target=target, args=args, name=name, daemon=True)
    t.start()
    return t


@contextmanager
def _running(stack, *, timeout=2.0):
    """Run the session on a thread, and stop it however the block ends.

    `stop_event.set()` used to sit after the wait, so a test whose predicate
    timed out never reached it -- and `session.run` plus its two forwarding
    threads spin (the fake ports return b"" straight away), so one red test left
    three threads burning a core each. They compound, and pytest itself stalls:
    one mutation probe never printed a summary at all and the file had to be
    killed at 120 s, which on CI is a job timeout with no traceback naming the
    test that caused it.
    """
    runner = threading.Thread(target=stack.session.run, args=(object(),),
                              name="broker-session", daemon=True)
    runner.start()
    try:
        yield runner
    finally:
        stack.stop_event.set()
        runner.join(timeout=timeout)


def _wait_until(predicate) -> None:
    """The shared waiter, with the one timeout this file's stack ever needs.

    Two seconds is far past anything the fake ports here take, and the helper
    returns the moment the predicate holds, so the number costs nothing until
    something is actually wrong -- at which point it names the predicate that
    never came true.
    """
    wait_until(predicate, timeout=2.0, interval=0.02)


def _build_stack(tmp_path: Path, *, enabled: bool = True):
    state_file = tmp_path / "state" / "genau_mode.txt"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    rh_enabled_file = tmp_path / "state" / "genau_enabled.txt"
    broker_cmd_file = tmp_path / "state" / "broker_cmd.txt"

    writes: list[tuple[Path, str]] = []
    udp_messages: list[str] = []

    def capture_write(path, value, _logger):
        writes.append((path, value))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def capture_udp(_sock, _host, _port, msg):
        udp_messages.append(msg)

    logger = MagicMock()

    controller = BrokerAutoController(
        state_file=state_file,
        udp_host="127.0.0.1",
        udp_port=9001,
        logger=logger,
        write_mode=capture_write,
        udp_send=capture_udp,
        enabled=enabled,
    )

    real_port = FakeSerialPort()
    virt_port = FakeSerialPort()

    clock = _FakeClock(0.0)

    def serial_factory(port_name, _baud, timeout=0.02):
        return real_port if port_name == "COM4" else virt_port

    stop_event = threading.Event()
    broker_paused = threading.Event()

    session = BrokerSerialSession(
        serial_factory=serial_factory,
        virtual_port="COM15",
        real_port="COM4",
        baud=115200,
        broker_cmd_file=broker_cmd_file,
        genau_enabled_file=rh_enabled_file,
        auto_stale_timeout=2.0,
        stop_event=stop_event,
        broker_paused=broker_paused,
        auto_mode=controller,
        logger=logger,
        start_thread=_start_real_thread,
        consume_command=lambda _path: None,
        read_genau_enabled=lambda _path: enabled,
        monotonic=clock,
        # Not a no-op: with nothing to read the run loop and both forwarding
        # threads would spin at full tilt for as long as the test lasts. A
        # millisecond on the stop event yields the core and returns the moment
        # the test asks them to stop.
        sleep=lambda _s: stop_event.wait(0.001),
    )
    session.port_exists = lambda _name: True

    return _Stack(
        session=session,
        controller=controller,
        real_port=real_port,
        virt_port=virt_port,
        stop_event=stop_event,
        broker_paused=broker_paused,
        state_file=state_file,
        rh_enabled_file=rh_enabled_file,
        broker_cmd_file=broker_cmd_file,
        writes=writes,
        udp_messages=udp_messages,
        logger=logger,
        clock=clock,
    )


class TestAutoTransitionFromSerial:
    def test_auto_on_line_activates_genau(self, tmp_path):
        s = _build_stack(tmp_path)
        s.real_port.inject(b"Auto mode is on!\r\n")

        with _running(s):
            _wait_until(lambda: s.controller.is_active)

        assert s.state_file.read_text(encoding="utf-8") == "1"
        assert "AUTO 1" in s.udp_messages
        assert "SHOW" in s.udp_messages

    def test_auto_off_line_deactivates_genau(self, tmp_path):
        s = _build_stack(tmp_path)
        s.controller.set_auto(object(), True)
        s.writes.clear()
        s.udp_messages.clear()

        s.real_port.inject(b"Auto mode is off!\r\n")
        with _running(s):
            _wait_until(lambda: not s.controller.is_active)

        assert s.state_file.read_text(encoding="utf-8") == "0"
        assert "AUTO 0" in s.udp_messages
        assert "HIDE" in s.udp_messages

    def test_freemode_line_activates(self, tmp_path):
        s = _build_stack(tmp_path)
        s.real_port.inject(b"freeMode is on!\r\n")

        with _running(s):
            _wait_until(lambda: s.controller.is_active)

        assert "AUTO 1" in s.udp_messages


class TestStrokeAndBpmFromSerial:
    def test_stroke_and_pattern_parsed_from_serial_data(self, tmp_path):
        s = _build_stack(tmp_path)
        s.real_port.inject(b"StrokeName: Pull, PatternDuration: 2.0\r\n")

        with _running(s):
            _wait_until(lambda: "STROKE Pull" in s.udp_messages)

        assert "STROKE Pull" in s.udp_messages
        assert "PATTERN 2.0" in s.udp_messages
        assert "SYNC" in s.udp_messages

    def test_bpm_and_beats_parsed_from_serial_data(self, tmp_path):
        s = _build_stack(tmp_path)
        s.real_port.inject(b"bpm 120, beats 4\r\n")

        with _running(s):
            _wait_until(lambda: "BPM 120" in s.udp_messages)

        assert "BPM 120" in s.udp_messages
        assert "BEATS 4" in s.udp_messages

    def test_combined_stroke_and_bpm_on_one_line(self, tmp_path):
        s = _build_stack(tmp_path)
        line = b"StrokeName: Twist, PatternDuration: 1.5 bpm 90, beats 2 continue StrokeName:\r\n"
        s.real_port.inject(line)

        with _running(s):
            _wait_until(lambda: "BEATS 2" in s.udp_messages)

        assert s.udp_messages == [
            "AUTO 1", "SHOW", "BPM 87",
            "STROKE Twist", "PATTERN 1.5", "SYNC",
            "AUTO 1", "SHOW", "BPM 87",
            "BPM 90", "BEATS 2", "SYNC",
        ]


class TestSerialForwarding:
    def test_real_data_forwarded_to_virtual(self, tmp_path):
        s = _build_stack(tmp_path)
        s.real_port.inject(b"device says hello\r\n")

        with _running(s):
            _wait_until(lambda: len(s.virt_port.tx_data) > 0)

        assert b"device says hello" in s.virt_port.tx_data

    def test_virtual_data_forwarded_to_real_when_auto_inactive(self, tmp_path):
        s = _build_stack(tmp_path)
        s.virt_port.inject(b"L0100\n")

        with _running(s):
            _wait_until(lambda: len(s.real_port.tx_data) > 0)

        assert b"L0100" in s.real_port.tx_data

    def test_virtual_data_blocked_when_auto_active(self, tmp_path):
        s = _build_stack(tmp_path)
        s.controller.set_auto(object(), True)

        s.virt_port.inject(b"L0100\n")

        with _running(s):
            _wait_until(lambda: s.virt_port.in_waiting == 0)

        assert s.real_port.tx_data == b""


class TestGenauEnabledSuppression:
    def test_disabled_genau_suppresses_state_file(self, tmp_path):
        s = _build_stack(tmp_path, enabled=False)
        s.real_port.inject(b"Auto mode is on!\r\n")

        with _running(s):
            _wait_until(lambda: s.controller.is_active)

        assert s.controller.is_active is True
        assert s.state_file.read_text(encoding="utf-8") == "0"
        assert "AUTO 0" in s.udp_messages
        assert "HIDE" in s.udp_messages

    def test_reenabling_while_auto_active_restores_visibility(self, tmp_path):
        s = _build_stack(tmp_path, enabled=False)
        sock = object()
        s.controller.set_auto(sock, True)

        s.controller.set_enabled(sock, True)

        assert s.state_file.read_text(encoding="utf-8") == "1"
        assert s.udp_messages[-3:] == ["AUTO 1", "SHOW", "BPM 87"]


class TestBrokerCommands:
    def test_pause_blocks_stale_timeout(self, tmp_path):
        s = _build_stack(tmp_path)
        sock = object()
        s.controller.set_auto(sock, True)
        s.session.last_real_rx_time = 1.0
        s.clock.t = 10.0

        s.session.handle_broker_command("PAUSE", sock)
        s.session.maybe_disable_stale_auto(sock)

        assert s.controller.is_active is True

    def test_resume_allows_stale_timeout(self, tmp_path):
        s = _build_stack(tmp_path)
        sock = object()
        s.controller.set_auto(sock, True)
        s.session.last_real_rx_time = 1.0
        s.clock.t = 10.0

        s.session.handle_broker_command("PAUSE", sock)
        s.session.handle_broker_command("RESUME", sock)
        s.session.maybe_disable_stale_auto(sock)

        assert s.controller.is_active is False

    def test_genau_disable_command_suppresses_output(self, tmp_path):
        s = _build_stack(tmp_path)
        sock = object()
        s.controller.set_auto(sock, True)
        s.writes.clear()
        s.udp_messages.clear()

        s.session.handle_broker_command("GENAU_DISABLE", sock)

        assert s.state_file.read_text(encoding="utf-8") == "0"
        assert "HIDE" in s.udp_messages


class TestMultiLineSerialBuffer:
    def test_partial_lines_buffered_until_newline(self, tmp_path):
        s = _build_stack(tmp_path)
        s.real_port.inject(b"Auto mode")

        with _running(s):
            # The half line has been read off the port and is sitting in the
            # session's buffer -- which is the moment the "not yet active" claim
            # is about. A tenth of a second was standing in for it, and said
            # nothing at all on a machine where the reader had not got there.
            _wait_until(lambda: s.real_port.in_waiting == 0)

            assert s.controller.is_active is False

            s.real_port.inject(b" is on!\r\n")
            _wait_until(lambda: s.controller.is_active)

        assert s.controller.is_active is True

    def test_multiple_lines_in_single_read(self, tmp_path):
        s = _build_stack(tmp_path)
        s.real_port.inject(
            b"StrokeName: Push, PatternDuration: 3.0\r\n"
            b"bpm 60, beats 8\r\n"
        )

        with _running(s):
            _wait_until(lambda: "BEATS 8" in s.udp_messages)

        assert "STROKE Push" in s.udp_messages
        assert "PATTERN 3.0" in s.udp_messages
        assert "BPM 60" in s.udp_messages
        assert "BEATS 8" in s.udp_messages


class TestAutoTransitionSequence:
    def test_on_off_on_sequence(self, tmp_path):
        s = _build_stack(tmp_path)
        s.real_port.inject(b"Auto mode is on!\r\n")

        with _running(s):
            _wait_until(lambda: s.controller.is_active)

            s.real_port.inject(b"Auto mode is off!\r\n")
            _wait_until(lambda: not s.controller.is_active)

            s.real_port.inject(b"freeMode is on!\r\n")
            _wait_until(lambda: s.controller.is_active)


        auto_msgs = [m for m in s.udp_messages if m.startswith("AUTO")]
        transitions = [auto_msgs[0]] + [
            m for i, m in enumerate(auto_msgs[1:], 1) if m != auto_msgs[i - 1]
        ]
        assert transitions == ["AUTO 1", "AUTO 0", "AUTO 1"]

    def test_stroke_data_interleaved_with_auto_transitions(self, tmp_path):
        s = _build_stack(tmp_path)
        s.real_port.inject(
            b"Auto mode is on!\r\n"
            b"StrokeName: Wave, PatternDuration: 1.0\r\n"
            b"bpm 140, beats 4\r\n"
        )

        with _running(s):
            _wait_until(lambda: "BEATS 4" in s.udp_messages)

        assert "AUTO 1" in s.udp_messages
        assert "STROKE Wave" in s.udp_messages
        assert "BPM 140" in s.udp_messages
        auto_idx = s.udp_messages.index("AUTO 1")
        stroke_idx = s.udp_messages.index("STROKE Wave")
        assert auto_idx < stroke_idx
