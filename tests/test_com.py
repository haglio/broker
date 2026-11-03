from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

from app_support import osr2_device
from app_support.threading_utils import wait_until

from osr2_broker.activity import ActivityStamp
from osr2_broker.protocol import BrokerAutoController
from tests.sessions import make_session


class FakeSerialPort:
    def __init__(self):
        self._rx_buf = bytearray()
        self._tx_buf = bytearray()
        self._lock = threading.Lock()
        self._closed = False
        self.reads = 0

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
            self.reads += 1
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
    runner = threading.Thread(target=stack.session.run, args=(object(), "COM4"),
                              name="broker-session", daemon=True)
    runner.start()
    try:
        yield runner
    finally:
        stack.stop_event.set()
        runner.join(timeout=timeout)


def _wait_until(predicate) -> None:
    wait_until(predicate, timeout=2.0, interval=0.02)


def _build_stack(tmp_path: Path):
    state_file = tmp_path / "state" / "broker_mode.txt"
    state_file.parent.mkdir(parents=True, exist_ok=True)
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
        udp_target=("127.0.0.1", 9001),
        logger=logger,
        write_mode=capture_write,
        udp_send=capture_udp,
    )

    real_port = FakeSerialPort()
    virt_port = FakeSerialPort()

    clock = _FakeClock(0.0)

    def serial_factory(port_name, _baud, timeout=0.02):
        return real_port if port_name == "COM4" else virt_port

    stop_event = threading.Event()
    broker_paused = threading.Event()

    session = make_session(
        serial_factory=serial_factory,
        broker_cmd_file=broker_cmd_file,
        device_on=lambda: osr2_device.switched_on(tmp_path / "state"),
        stop_event=stop_event,
        broker_paused=broker_paused,
        auto_mode=controller,
        logger=logger,
        start_thread=_start_real_thread,
        rx_activity=ActivityStamp(tmp_path / "state" / "osr2_serial_rx.txt"),
        tx_activity=ActivityStamp(tmp_path / "state" / "osr2_serial_tx.txt"),
        monotonic=clock,
        sleep=lambda _s: stop_event.wait(0.001),
    )

    return _Stack(
        session=session,
        controller=controller,
        real_port=real_port,
        virt_port=virt_port,
        stop_event=stop_event,
        broker_paused=broker_paused,
        state_file=state_file,
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

    def test_freemode_line_activates(self, tmp_path):
        s = _build_stack(tmp_path)
        s.real_port.inject(b"freeMode is on!\r\n")

        with _running(s):
            _wait_until(lambda: s.controller.is_active)

        assert "AUTO 1" in s.udp_messages


class TestMotionAndBpmFromSerial:
    def test_motion_line_sends_a_sync(self, tmp_path):
        s = _build_stack(tmp_path)
        s.real_port.inject(b"StrokeName: Pull, PatternDuration: 2.0\r\n")

        with _running(s):
            _wait_until(lambda: "SYNC" in s.udp_messages)

        assert s.controller.is_active is True
        assert "SYNC" in s.udp_messages

    def test_bpm_parsed_from_serial_data(self, tmp_path):
        s = _build_stack(tmp_path)
        s.real_port.inject(b"bpm 120, beats 4\r\n")

        with _running(s):
            _wait_until(lambda: "BPM 120" in s.udp_messages)

        assert "BPM 120" in s.udp_messages

    def test_combined_motion_and_bpm_on_one_line(self, tmp_path):
        s = _build_stack(tmp_path)
        line = b"StrokeName: Twist, PatternDuration: 1.5 bpm 90, beats 2 continue StrokeName:\r\n"
        s.real_port.inject(line)

        with _running(s):
            _wait_until(lambda: s.udp_messages.count("SYNC") == 2)

        assert s.udp_messages == [
            "AUTO 1", "BPM 87",
            "SYNC",
            "BPM 90", "SYNC",
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


class TestBrokerCommands:
    def test_pause_keeps_auto_mode_through_the_device_going_quiet(self, tmp_path):
        s = _build_stack(tmp_path)
        sock = object()
        s.controller.set_auto(sock, True)

        s.session.handle_broker_command("PAUSE", sock)
        s.session.end_auto_mode_once_switched_off(sock)

        assert s.controller.is_active is True

    def test_resume_lets_a_switched_off_device_end_auto_mode(self, tmp_path):
        s = _build_stack(tmp_path)
        sock = object()
        s.controller.set_auto(sock, True)

        s.session.handle_broker_command("PAUSE", sock)
        s.session.handle_broker_command("RESUME", sock)
        s.session.end_auto_mode_once_switched_off(sock)

        assert s.controller.is_active is False


class TestMultiLineSerialBuffer:
    def test_partial_lines_buffered_until_newline(self, tmp_path):
        s = _build_stack(tmp_path)
        s.real_port.inject(b"Auto mode")

        with _running(s):
            _wait_until(lambda: s.real_port.in_waiting == 0)
            took_the_half_line = s.real_port.reads
            _wait_until(lambda: s.real_port.reads > took_the_half_line)

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
            _wait_until(lambda: "BPM 60" in s.udp_messages)

        assert "SYNC" in s.udp_messages
        assert "BPM 60" in s.udp_messages


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

    def test_motion_data_interleaved_with_auto_transitions(self, tmp_path):
        s = _build_stack(tmp_path)
        s.real_port.inject(
            b"Auto mode is on!\r\n"
            b"StrokeName: Wave, PatternDuration: 1.0\r\n"
            b"bpm 140, beats 4\r\n"
        )

        with _running(s):
            _wait_until(lambda: "BPM 140" in s.udp_messages)

        assert "AUTO 1" in s.udp_messages
        assert "SYNC" in s.udp_messages
        assert "BPM 140" in s.udp_messages
        auto_idx = s.udp_messages.index("AUTO 1")
        motion_idx = s.udp_messages.index("SYNC")
        assert auto_idx < motion_idx
