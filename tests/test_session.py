from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from app_support.file_channel import publish_stamp, stamp_age
from app_support.osr2_device import ANSWERS_ONCE_OFF_S, switched_on
from app_support.state_files import OSR2_SERIAL_RX

from osr2_broker import session as session_module
from osr2_broker.activity import ActivityStamp
from osr2_broker.hold import HoldScheduler
from osr2_broker.motion_log import UDP
from osr2_broker.question import DeviceQuestion
from osr2_broker.session import SessionRetryState
from osr2_broker.tcode_udp import NO_LISTENER_PORT
from osr2_broker.tcode_window import TCodeWriteWindow
from tests.conftest import FakePowerOnSayingNoUnlessToldSoNoStrayTestParksTheDevice
from tests.sessions import (
    NotActuallyRunningSoThreadsOtherTestsLeftCannotTripThese,
    StampSpy,
    make_session,
)


class FakeAutoMode:
    def __init__(self, *, active: bool = False):
        self.active = active
        self.handle_line_calls: list[str] = []
        self.set_auto_calls: list[tuple[object, bool]] = []
        self._deactivated = False

    @property
    def is_active(self) -> bool:
        return self.active

    def handle_line(self, _sock, line: str) -> None:
        self.handle_line_calls.append(line)

    def set_auto(self, sock, value: bool) -> None:
        self.set_auto_calls.append((sock, value))
        was_active = self.active
        self.active = value
        if was_active and not value:
            self._deactivated = True

    def consume_deactivation(self) -> bool:
        if self._deactivated:
            self._deactivated = False
            return True
        return False


def _build_session(*, auto_active: bool = False, monotonic=lambda: 10.0, logger=None, **given):
    auto_mode = FakeAutoMode(active=auto_active)
    logger = logger or MagicMock()
    session = make_session(auto_mode=auto_mode, monotonic=monotonic, logger=logger, **given)
    return session, auto_mode, logger


def test_handle_broker_command_sets_pause_and_resume():
    session, _auto_mode, logger = _build_session()

    session.handle_broker_command("PAUSE", object())
    assert session.broker_paused.is_set()
    logger.info.assert_called_once_with("OmniPause: broker paused")

    logger.reset_mock()
    session.handle_broker_command("RESUME", object())
    assert not session.broker_paused.is_set()
    logger.info.assert_called_once_with("OmniPause: broker resumed")


def test_park_schedules_delayed_write():
    clock = [10.0]
    session, _auto_mode, _logger = _build_session(monotonic=lambda: clock[0])
    real_port = MagicMock()
    lock = threading.Lock()
    sock = object()

    session.handle_broker_command("PARK", sock)
    session.tick(sock, real_port=real_port, serial_write_lock=lock)
    real_port.write.assert_not_called()

    clock[0] = 12.0
    session.tick(sock, real_port=real_port, serial_write_lock=lock)
    real_port.write.assert_called_once_with(b"L00000I1000\n")


def test_park_suppresses_mfp_forwarding():
    clock = [10.0]
    session, _auto_mode, _logger = _build_session(monotonic=lambda: clock[0])
    real_port = MagicMock()
    lock = threading.Lock()
    sock = object()

    session.handle_broker_command("PARK", sock)
    clock[0] = 12.0
    session.tick(sock, real_port=real_port, serial_write_lock=lock)
    assert session._tcode_window.is_open() is True


def test_resume_cancels_pending_park():
    clock = [10.0]
    session, _auto_mode, _logger = _build_session(monotonic=lambda: clock[0])
    real_port = MagicMock()
    lock = threading.Lock()
    sock = object()

    session.handle_broker_command("PARK", sock)
    session.handle_broker_command("RESUME", sock)
    clock[0] = 12.0
    session.tick(sock, real_port=real_port, serial_write_lock=lock)
    real_port.write.assert_not_called()


def test_retract_the_emergency_sends_the_device_to_the_far_end_instead_of_home():
    clock = [10.0]
    session, _auto_mode, _logger = _build_session(monotonic=lambda: clock[0])
    real_port = MagicMock()
    lock = threading.Lock()

    sock = object()

    session.handle_broker_command("RETRACT", sock)
    session.tick(sock, real_port=real_port, serial_write_lock=lock)
    real_port.write.assert_not_called()

    clock[0] = 12.0
    session.tick(sock, real_port=real_port, serial_write_lock=lock)
    real_port.write.assert_called_once_with(b"L09999I500\n")


def test_fired_hold_is_logged_as_the_position_it_actually_wrote():
    clock = [10.0]
    session, _auto_mode, logger = _build_session(monotonic=lambda: clock[0])
    lock = threading.Lock()
    sock = object()

    session.handle_broker_command("RETRACT", sock)
    clock[0] = 12.0
    session.tick(sock, real_port=MagicMock(), serial_write_lock=lock)

    fired = [call.args[0] for call in logger.info.call_args_list]
    assert any("Retracting" in msg and "9999" in msg for msg in fired), fired
    assert not any("Parking" in msg for msg in fired), fired
    assert "OmniPause" not in fired[-1], fired


def test_auto_mode_deactivation_schedules_park():
    clock = [10.0]
    session, _auto_mode, _logger = _build_session(auto_active=True, monotonic=lambda: clock[0],
                                                 device_on=lambda: False)
    real_port = MagicMock()
    lock = threading.Lock()
    sock = object()

    session.tick(sock, real_port=real_port, serial_write_lock=lock)

    real_port.write.assert_not_called()

    clock[0] = 12.0
    session.tick(sock, real_port=real_port, serial_write_lock=lock)
    real_port.write.assert_called_once_with(b"L00000I1000\n")


def test_auto_mode_deactivation_between_ticks_schedules_park():
    clock = [10.0]
    session, auto_mode, _logger = _build_session(auto_active=True, monotonic=lambda: clock[0])
    real_port = MagicMock()
    lock = threading.Lock()
    sock = object()

    auto_mode.set_auto(sock, False)

    session.tick(sock, real_port=real_port, serial_write_lock=lock)
    real_port.write.assert_not_called()

    clock[0] = 12.0
    session.tick(sock, real_port=real_port, serial_write_lock=lock)
    real_port.write.assert_called_once_with(b"L00000I1000\n")


def test_a_verb_another_app_grew_that_this_broker_does_not_know_is_a_quiet_no_op_the_file_is_shared():
    session, _auto_mode, logger = _build_session()

    session.handle_broker_command("TELEPORT", object())

    assert not session.broker_paused.is_set()
    logger.info.assert_not_called()
    logger.warning.assert_not_called()


def test_an_empty_tick_with_no_command_is_a_no_op():
    session, _auto_mode, logger = _build_session()

    session.handle_broker_command(None, object())

    assert not session.broker_paused.is_set()
    logger.info.assert_not_called()


def test_the_devices_own_auto_mode_ends_once_it_is_switched_off():
    session, auto_mode, logger = _build_session(auto_active=True, device_on=lambda: False)
    sock = object()

    session.end_auto_mode_once_switched_off(sock)

    assert auto_mode.set_auto_calls == [(sock, False)]
    logger.warning.assert_called_once_with("AUTO ended: the OSR2 has been switched off")


def test_end_auto_mode_once_switched_off_leaves_a_paused_broker_alone_paused_means_the_user_took_over():
    session, auto_mode, logger = _build_session(auto_active=True, device_on=lambda: False)
    session.broker_paused.set()

    session.end_auto_mode_once_switched_off(object())

    assert auto_mode.set_auto_calls == []
    logger.warning.assert_not_called()


def test_end_auto_mode_once_switched_off_ignores_an_inactive_auto_mode():
    session, auto_mode, logger = _build_session(auto_active=False, device_on=lambda: False)

    session.end_auto_mode_once_switched_off(object())

    assert auto_mode.set_auto_calls == []
    logger.warning.assert_not_called()


def test_forward_real_to_virtual_updates_timestamp_and_handles_lines():
    rx_activity = StampSpy()
    session, auto_mode, _logger = _build_session(rx_activity=rx_activity)
    session_stop = threading.Event()
    retry_state = SessionRetryState()
    udp_sock = object()

    class FakeReal:
        def __init__(self):
            self.in_waiting = 1
            self.calls = 0

        def read(self, _size):
            self.calls += 1
            session_stop.set()
            return b"hello\r\n"

    class FakeVirt:
        def __init__(self):
            self.writes: list[bytes] = []

        def write(self, data: bytes):
            self.writes.append(data)

    real = FakeReal()
    virt = FakeVirt()

    session.forward_real_to_virtual(real, virt, udp_sock, session_stop, retry_state)

    assert rx_activity.marks == 1
    assert virt.writes == [b"hello\r\n"]
    assert auto_mode.handle_line_calls == ["hello"]
    assert retry_state.value is False


def test_forward_virtual_to_real_skips_writes_while_auto_is_active():
    session, _auto_mode, _logger = _build_session(auto_active=True)
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeVirt:
        def __init__(self):
            self.in_waiting = 1
            self.calls = 0

        def read(self, _size):
            self.calls += 1
            session_stop.set()
            return b"ABC"

    class FakeReal:
        def __init__(self):
            self.writes: list[bytes] = []

        def write(self, data: bytes):
            self.writes.append(data)

    real = FakeReal()
    virt = FakeVirt()

    session.forward_virtual_to_real(virt, real, session_stop, retry_state, threading.Lock())

    assert real.writes == []
    assert retry_state.value is False


def test_forward_virtual_to_real_skips_writes_just_after_direct_t_code():
    clock = [10.0 - TCodeWriteWindow.SUPPRESS_SECONDS / 5]
    session, _auto_mode, _logger = _build_session(monotonic=lambda: clock[0])
    session._tcode_window.mark()
    clock[0] = 10.0
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeVirt:
        def __init__(self):
            self.in_waiting = 1
        def read(self, _size):
            session_stop.set()
            return b"L05000\n"

    class FakeReal:
        def __init__(self):
            self.writes: list[bytes] = []
        def write(self, data: bytes):
            self.writes.append(data)

    real = FakeReal()
    session.forward_virtual_to_real(FakeVirt(), real, session_stop, retry_state, threading.Lock())

    assert real.writes == []


def test_forward_virtual_to_real_allows_writes_once_direct_t_code_has_gone_quiet():
    clock = [10.0 - TCodeWriteWindow.SUPPRESS_SECONDS * 2]
    session, _auto_mode, _logger = _build_session(monotonic=lambda: clock[0])
    session._tcode_window.mark()
    clock[0] = 10.0
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeVirt:
        def __init__(self):
            self.in_waiting = 1
        def read(self, _size):
            session_stop.set()
            return b"L05000\n"

    class FakeReal:
        def __init__(self):
            self.writes: list[bytes] = []
        def write(self, data: bytes):
            self.writes.append(data)

    real = FakeReal()
    session.forward_virtual_to_real(FakeVirt(), real, session_stop, retry_state, threading.Lock())

    assert real.writes == [b"L05000\n"]


def test_park_suppression_heals_when_mfp_active_after_grace():
    clock = [100.0]
    session, _auto_mode, _logger = _build_session(monotonic=lambda: clock[0])
    session.handle_broker_command("PARK", object())
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeVirt:
        def __init__(self):
            self.in_waiting = 1

        def read(self, _size):
            session_stop.set()
            return b"L05000\n"

    class FakeReal:
        def __init__(self):
            self.writes: list[bytes] = []

        def write(self, data: bytes):
            self.writes.append(data)

    clock[0] = 100.0 + HoldScheduler.HEAL_WITHOUT_RESUME_SECONDS + 0.1
    real = FakeReal()
    session.forward_virtual_to_real(FakeVirt(), real, session_stop, retry_state, threading.Lock())

    assert real.writes == [b"L05000\n"]


def test_park_suppression_holds_within_grace_window():
    clock = [100.0]
    session, _auto_mode, _logger = _build_session(monotonic=lambda: clock[0])
    session.handle_broker_command("PARK", object())
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeVirt:
        def __init__(self):
            self.in_waiting = 1

        def read(self, _size):
            session_stop.set()
            return b"L05000\n"

    class FakeReal:
        def __init__(self):
            self.writes: list[bytes] = []

        def write(self, data: bytes):
            self.writes.append(data)

    clock[0] = 100.0 + 1.0
    real = FakeReal()
    session.forward_virtual_to_real(FakeVirt(), real, session_stop, retry_state, threading.Lock())

    assert real.writes == []


def test_resume_hands_mfp_back_without_waiting_out_the_grace():
    clock = [100.0]
    session, _auto_mode, _logger = _build_session(monotonic=lambda: clock[0])
    sock = object()
    session.handle_broker_command("PARK", sock)
    session.handle_broker_command("RESUME", sock)
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeVirt:
        def __init__(self):
            self.in_waiting = 1

        def read(self, _size):
            session_stop.set()
            return b"L05000\n"

    class FakeReal:
        def __init__(self):
            self.writes: list[bytes] = []

        def write(self, data: bytes):
            self.writes.append(data)

    clock[0] = 100.0 + 1.0
    real = FakeReal()
    session.forward_virtual_to_real(FakeVirt(), real, session_stop, retry_state, threading.Lock())

    assert real.writes == [b"L05000\n"]


def test_the_connected_event_is_set_while_the_ports_are_open_and_clear_after():
    session, _auto_mode, _logger = _build_session()
    seen_inside: list[bool] = []

    class FakePort:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, _n): return b""
        def write(self, _d): pass
        @property
        def dsr(self): return True

    def _sleep(_seconds):
        seen_inside.append(session.connected_event.is_set())
        session.stop_event.set()

    session.serial_factory = lambda *a, **kw: FakePort()
    session.sleep = _sleep
    session.start_thread = lambda **_kw: NotActuallyRunningSoThreadsOtherTestsLeftCannotTripThese()

    session.run(object(), "COM4")

    assert seen_inside == [True]
    assert not session.connected_event.is_set()


def test_a_retryable_read_error_asks_the_caller_for_another_session():
    session, _auto_mode, _logger = _build_session(is_retryable_error=lambda _exc: True)
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeReal:
        in_waiting = 1

        def read(self, _size):
            raise OSError("the port went away")

    class FakeVirt:
        def write(self, _data): pass

    session.forward_real_to_virtual(FakeReal(), FakeVirt(), object(), session_stop, retry_state)

    assert retry_state.value is True
    assert session_stop.is_set()


def test_an_unretryable_read_error_ends_the_session_for_good():
    session, _auto_mode, _logger = _build_session(is_retryable_error=lambda _exc: False)
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeReal:
        in_waiting = 1

        def read(self, _size):
            raise OSError("the port went away")

    class FakeVirt:
        def write(self, _data): pass

    session.forward_real_to_virtual(FakeReal(), FakeVirt(), object(), session_stop, retry_state)

    assert retry_state.value is False
    assert session_stop.is_set()


def test_session_stops_when_peer_disconnects():
    session, _auto_mode, _logger = _build_session()

    dsr_values = iter([True, False])

    class FakePort:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, n): return b""
        def write(self, d): pass
        @property
        def dsr(self):
            return next(dsr_values, False)

    session.serial_factory = lambda *a, **kw: FakePort()
    session.sleep = lambda _: None
    def _fake_start_thread(*, target, args, name):
        t = threading.Thread(target=lambda: None, daemon=True)
        t.start()
        return t
    session.start_thread = _fake_start_thread

    should_retry = session.run(object(), "COM4")

    assert not session.connected_event.is_set()
    assert should_retry is True


def test_session_stays_alive_when_peer_never_connected():
    session, _auto_mode, _logger = _build_session()

    poll_count = 0

    class FakePort:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, n): return b""
        def write(self, d): pass
        @property
        def dsr(self):
            return False

    session.serial_factory = lambda *a, **kw: FakePort()

    def counting_sleep(_):
        nonlocal poll_count
        poll_count += 1
        if poll_count >= 5:
            session.stop_event.set()
    session.sleep = counting_sleep

    def _fake_start_thread(*, target, args, name):
        t = threading.Thread(target=lambda: None, daemon=True)
        t.start()
        return t
    session.start_thread = _fake_start_thread

    session.run(object(), "COM4")

    assert poll_count >= 5


def test_forward_real_to_virtual_writes_activity_rx_file(tmp_path):
    rx_file = tmp_path / "osr2_serial_rx.txt"
    session, _auto_mode, _logger = _build_session(
        monotonic=lambda: 12.5,
        rx_activity=ActivityStamp(rx_file, wall_clock=lambda: 1711900000.0),
    )
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeReal:
        def __init__(self):
            self.in_waiting = 1
        def read(self, _size):
            session_stop.set()
            return b"temp data\n"

    class FakeVirt:
        def write(self, data): pass

    session.forward_real_to_virtual(FakeReal(), FakeVirt(), object(), session_stop, retry_state)

    assert rx_file.exists()
    assert float(rx_file.read_text()) == 1711900000.0


def test_forward_virtual_to_real_writes_activity_tx_file(tmp_path):
    tx_file = tmp_path / "osr2_serial_tx.txt"
    session, _auto_mode, _logger = _build_session(
        tx_activity=ActivityStamp(tx_file, wall_clock=lambda: 1711900000.0),
    )
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeVirt:
        def __init__(self):
            self.in_waiting = 1
        def read(self, _size):
            session_stop.set()
            return b"L0500\n"

    class FakeReal:
        def __init__(self):
            self.writes = []
        def write(self, data):
            self.writes.append(data)

    real = FakeReal()
    session.forward_virtual_to_real(FakeVirt(), real, session_stop, retry_state, threading.Lock())

    assert real.writes == [b"L0500\n"]
    assert tx_file.exists()
    assert float(tx_file.read_text()) == 1711900000.0


def test_peer_disconnect_retries_despite_thread_teardown_error():
    session, _auto_mode, _logger = _build_session()

    thread_reading = threading.Event()

    class FakeVirt:
        def __init__(self):
            self._first_dsr = True
        def __enter__(self): return self
        def __exit__(self, *a): pass
        @property
        def in_waiting(self): return 0
        def read(self, n): return b""
        def write(self, data): pass
        @property
        def dsr(self):
            if self._first_dsr:
                self._first_dsr = False
                return True
            thread_reading.wait(timeout=5.0)
            return False

    class FakeReal:
        def __init__(self):
            self._closed = False
        def __enter__(self): return self
        def __exit__(self, *a):
            self._closed = True
        @property
        def in_waiting(self): return 1
        def read(self, n):
            thread_reading.set()
            while not self._closed:
                time.sleep(0.001)
            raise AttributeError(
                "'NoneType' object has no attribute 'hEvent'"
            )
        def write(self, data): pass

    fake_virt = FakeVirt()
    ports = iter([fake_virt, FakeReal()])
    session.serial_factory = lambda *a, **kw: next(ports)
    session.sleep = lambda _: None

    def _start(*, target, args, name):
        t = threading.Thread(target=target, args=args, daemon=True)
        t.start()
        return t
    session.start_thread = _start

    should_retry = session.run(object(), "COM4")

    assert should_retry is True


def test_forward_virtual_to_real_uses_serial_write_lock():
    session, _auto_mode, _logger = _build_session()
    session_stop = threading.Event()
    retry_state = SessionRetryState()
    lock = threading.Lock()
    lock_held_during_write = [False]

    class FakeVirt:
        def __init__(self):
            self.in_waiting = 1
        def read(self, _size):
            session_stop.set()
            return b"L0500\n"

    class FakeReal:
        def write(self, data):
            lock_held_during_write[0] = lock.locked()

    session.forward_virtual_to_real(FakeVirt(), FakeReal(), session_stop, retry_state, lock)

    assert lock_held_during_write[0] is True


def _thread_names_started_by_one_run(session) -> list[str]:
    started: list[str] = []

    class FakePort:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, _n): return b""
        def write(self, _d): pass
        @property
        def dsr(self): return True

    def _start(*, target, args, name):
        started.append(name)
        return NotActuallyRunningSoThreadsOtherTestsLeftCannotTripThese()

    session.serial_factory = lambda *a, **kw: FakePort()
    session.sleep = lambda _s: session.stop_event.set()
    session.start_thread = _start
    session.run(object(), "COM4")
    return started


def test_a_configured_tcode_port_gets_a_listener_thread():
    session, _auto_mode, _logger = _build_session(tcode_udp_port=50557)

    assert _thread_names_started_by_one_run(session) == [
        "broker-real", "broker-virtual", "broker-tcode-udp",
    ]


class _Port:
    def __init__(self):
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)


def _writer(session, port, *, lock=None, session_stop=None, retry_state=None):
    return session.tcode_writer(port, lock or threading.Lock(),
                                session_stop or threading.Event(),
                                retry_state or SessionRetryState())


def test_t_code_reaches_the_osr2_one_line_at_a_time():
    session, _auto_mode, _logger = _build_session()
    port = _Port()

    _writer(session, port)(UDP, "L05000I33")

    assert port.writes == [b"L05000I33\n"]


def test_a_line_that_is_not_ascii_is_dropped_without_ending_the_session_its_stand_in_characters_could_read_as_a_move_nobody_sent():
    session, _auto_mode, _logger = _build_session()
    session_stop = threading.Event()
    port = _Port()

    _writer(session, port, session_stop=session_stop)(UDP, "L0\N{REPLACEMENT CHARACTER}500I33")

    assert port.writes == []
    assert not session_stop.is_set()


def test_t_code_arriving_while_the_device_drives_itself_is_dropped_whole():
    tx_activity = StampSpy()
    session, auto_mode, _logger = _build_session(auto_active=True, tx_activity=tx_activity)
    port = _Port()
    write = _writer(session, port)

    write(UDP, "L05000I33")
    auto_mode.active = False
    write(UDP, "L09999I33")

    assert port.writes == [b"L09999I33\n"]
    assert tx_activity.marks == 1


def test_t_code_is_written_under_the_session_s_serial_lock():
    session, _auto_mode, _logger = _build_session()
    lock = threading.Lock()
    held_during_write = []

    class Port:
        def write(self, _data):
            held_during_write.append(lock.locked())

    _writer(session, Port(), lock=lock)(UDP, "L05000I33")

    assert held_during_write == [True]


def test_written_t_code_stamps_the_tx_activity_file(tmp_path):
    tx_file = tmp_path / "osr2_serial_tx.txt"
    session, _auto_mode, _logger = _build_session(
        tx_activity=ActivityStamp(tx_file, wall_clock=lambda: 1711900000.0),
    )

    _writer(session, _Port())(UDP, "L05000I33")

    assert float(tx_file.read_text()) == 1711900000.0


def test_written_t_code_mutes_mfp_after_it():
    session, _auto_mode, _logger = _build_session()

    _writer(session, _Port())(UDP, "L05000I33")

    assert session._tcode_window.is_open() is True


def test_written_t_code_is_told_to_the_motion_log_by_the_inlet_it_came_in_on(recorded_logger):
    logger, heard = recorded_logger
    session, _auto_mode, _logger = _build_session(logger=logger)

    _writer(session, _Port())(UDP, "L05000I33")

    assert [record.getMessage() for record in heard.records] == [f"OSR2 driven by {UDP}"]


def test_t_code_the_port_cannot_take_ends_the_session_and_says_whether_to_retry():
    session, _auto_mode, _logger = _build_session(is_retryable_error=lambda _exc: True)
    session_stop, retry_state = threading.Event(), SessionRetryState()

    class GonePort:
        def write(self, _data):
            raise OSError("the port went away")

    _writer(session, GonePort(), session_stop=session_stop, retry_state=retry_state)(
        UDP, "L05000I33")

    assert session_stop.is_set()
    assert retry_state.value is True


def test_a_session_that_has_begun_to_end_writes_no_more_t_code_sparing_the_failed_port_a_try_per_line():
    session, _auto_mode, _logger = _build_session()
    session_stop = threading.Event()
    session_stop.set()
    port = _Port()

    _writer(session, port, session_stop=session_stop)(UDP, "L05000I33")

    assert port.writes == []


class _SlotSpy:
    def __init__(self, events: list | None = None, *, holder: str | None = None):
        self.holder = holder
        self.writers: list = []
        self.events = [] if events is None else events

    def write_through(self, writer) -> None:
        self.writers.append(writer)

    def kick(self, taker: str) -> None:
        self.events.append(f"{taker} took the OSR2")


def test_mfp_is_not_forwarded_while_a_sender_holds_the_slot():
    slot = _SlotSpy(holder="portrait")
    session, _auto_mode, _logger = _build_session(slot=slot)
    real = _Port()

    _forward(session, real, threading.Lock(), b"L05000I33\n")
    slot.holder = None
    _forward(session, real, threading.Lock(), b"L09999I33\n")

    assert real.writes == [b"L09999I33\n"]


def test_the_udp_inlet_asks_the_session_s_slot_who_holds_it(monkeypatch):
    handed = {}
    monkeypatch.setattr(session_module, "UdpTCodeListener", lambda **kwargs: handed.update(kwargs))
    slot = _SlotSpy(holder="portrait")

    _build_session(tcode_udp_port=50557, slot=slot)
    lets_through = handed["lets_through"]

    assert lets_through() is False
    slot.holder = None
    assert lets_through() is True


def test_udp_dropped_while_the_slot_is_held_is_told_when_the_tick_finds_the_run_over(
        monkeypatch, recorded_logger):
    handed = {}
    monkeypatch.setattr(session_module, "UdpTCodeListener", lambda **kwargs: handed.update(kwargs))
    logger, heard = recorded_logger
    clock = [10.0]
    session, _auto_mode, _logger = _build_session(tcode_udp_port=50557, logger=logger,
                                                  slot=_SlotSpy(holder="portrait"),
                                                  monotonic=lambda: clock[0])

    handed["lets_through"]()
    clock[0] += 5.0
    session.tick(object(), real_port=MagicMock(), serial_write_lock=threading.Lock())

    assert [record.getMessage() for record in heard.records] == [
        "Dropping T-Code UDP while the OSR2 is portrait's",
        "Dropped 1 T-Code UDP line while the OSR2 was portrait's",
    ]


def _a_session_telling(events: list, **kwargs):
    logger = MagicMock()
    logger.info.side_effect = lambda message, *_args: events.append(message)
    return _build_session(slot=_SlotSpy(events), logger=logger, **kwargs)[0]


def test_a_park_takes_the_osr2_from_whoever_holds_the_slot_before_it_is_scheduled():
    events: list = []

    _a_session_telling(events).handle_broker_command("PARK", object())

    assert events == ["The park took the OSR2", "OmniPause: park scheduled"]


def test_a_retract_takes_the_osr2_from_whoever_holds_the_slot_before_it_is_scheduled():
    events: list = []

    _a_session_telling(events).handle_broker_command("RETRACT", object())

    assert events == ["The retract took the OSR2", "OmniPause: retract scheduled"]


def test_the_park_when_the_osr2_is_switched_on_takes_nothing_from_the_slot_nobody_drove_a_device_that_was_off_and_whoever_connects_now_is_not_thrown_off():
    events: list = []
    session = _a_session_telling(events, power_on=FakePowerOnSayingNoUnlessToldSoNoStrayTestParksTheDevice(breaks_silence=True))
    session_stop = threading.Event()

    class FakeReal:
        in_waiting = 1

        def read(self, _size):
            session_stop.set()
            return b"hello\n"

    session.forward_real_to_virtual(FakeReal(), MagicMock(), object(), session_stop,
                                    SessionRetryState())

    assert events == ["OSR2 powered on: park scheduled"]


def test_the_park_when_auto_mode_ends_takes_nothing_from_the_slot():
    events: list = []
    session = _a_session_telling(events, auto_active=True, device_on=lambda: False)

    session.tick(object(), real_port=MagicMock(), serial_write_lock=threading.Lock())

    assert "Auto mode deactivated: park scheduled" in events
    assert not [event for event in events if "took the OSR2" in event]


class _OpenPort(_Port):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def read(self, _size):
        return b""

    @property
    def dsr(self):
        return True


def test_the_osr2_s_slot_writes_through_a_session_only_while_its_ports_are_open(recorded_logger):
    logger, heard = recorded_logger
    slot = _SlotSpy()
    session, _auto_mode, _logger = _build_session(slot=slot, logger=logger)
    ports = {"COM15": _OpenPort(), "COM4": _OpenPort()}
    session.serial_factory = lambda name, *_a, **_kw: ports[name]
    session.start_thread = lambda **_kw: NotActuallyRunningSoThreadsOtherTestsLeftCannotTripThese()

    def _sleep(_seconds):
        slot.writers[-1]("portrait", "L05000I33")
        session.stop_event.set()

    session.sleep = _sleep
    session.run(object(), "COM4")

    assert ports["COM4"].writes == [b"L05000I33\n"]
    assert slot.writers[-1] is None
    assert "OSR2 driven by T-Code from portrait" in [r.getMessage() for r in heard.records]


def test_port_zero_means_no_listener_binding_it_would_take_a_port_no_sender_can_address():
    session, _auto_mode, _logger = _build_session(tcode_udp_port=NO_LISTENER_PORT)

    assert _thread_names_started_by_one_run(session) == ["broker-real", "broker-virtual"]


def test_the_osr2_speaking_after_a_silence_is_parked_switched_on_it_comes_up_halfway_along_its_travel():
    clock = [10.0]
    session, _auto_mode, _logger = _build_session(
        monotonic=lambda: clock[0], power_on=FakePowerOnSayingNoUnlessToldSoNoStrayTestParksTheDevice(breaks_silence=True),
    )
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeReal:
        in_waiting = 1

        def read(self, _size):
            session_stop.set()
            return b"hello\n"

    class FakeVirt:
        def write(self, data):
            pass

    session.forward_real_to_virtual(FakeReal(), FakeVirt(), object(), session_stop, retry_state)

    real_port = MagicMock()
    clock[0] = 12.0
    session.tick(
        object(), real_port=real_port, serial_write_lock=threading.Lock(),
    )
    real_port.write.assert_called_once_with(b"L00000I1000\n")


def test_the_osr2_talking_on_without_a_silence_is_left_alone():
    clock = [10.0]
    session, _auto_mode, _logger = _build_session(
        monotonic=lambda: clock[0], power_on=FakePowerOnSayingNoUnlessToldSoNoStrayTestParksTheDevice(breaks_silence=False),
    )
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeReal:
        in_waiting = 1

        def read(self, _size):
            session_stop.set()
            return b"hello\n"

    class FakeVirt:
        def write(self, data):
            pass

    session.forward_real_to_virtual(FakeReal(), FakeVirt(), object(), session_stop, retry_state)

    real_port = MagicMock()
    clock[0] = 12.0
    session.tick(
        object(), real_port=real_port, serial_write_lock=threading.Lock(),
    )
    real_port.write.assert_not_called()


def test_a_park_on_power_on_leaves_the_script_feed_running_a_device_that_was_off_had_no_tail_to_swallow():
    clock = [10.0]
    session, _auto_mode, _logger = _build_session(
        monotonic=lambda: clock[0], power_on=FakePowerOnSayingNoUnlessToldSoNoStrayTestParksTheDevice(breaks_silence=True),
    )
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeReal:
        in_waiting = 1

        def __init__(self):
            self.writes: list[bytes] = []

        def read(self, _size):
            session_stop.set()
            return b"hello\n"

        def write(self, data: bytes):
            self.writes.append(data)

    feed_stop = threading.Event()

    class FakeVirt:
        in_waiting = 3

        def read(self, _size):
            feed_stop.set()
            return b"L50"

        def write(self, data):
            pass

    real = FakeReal()
    session.forward_real_to_virtual(real, FakeVirt(), object(), session_stop, retry_state)
    session.forward_virtual_to_real(
        FakeVirt(), real, feed_stop, retry_state, threading.Lock(),
    )

    assert real.writes == [b"L50"]


def _question(tmp_path: Path, clock: list[float]) -> DeviceQuestion:
    return DeviceQuestion(answer_file=tmp_path / "osr2_serial_answer.txt",
                          monotonic=lambda: clock[0], logger=MagicMock())


def test_the_tick_asks_the_device_its_question_when_one_is_due(tmp_path):
    session, _auto_mode, _logger = _build_session(question=_question(tmp_path, [10.0]))
    real_port = MagicMock()

    session.tick(object(), real_port=real_port,
                                           serial_write_lock=threading.Lock())

    real_port.write.assert_called_once_with(DeviceQuestion.QUESTION)


def _forward(session, real, lock, *chunks: bytes) -> None:
    pending = list(chunks)
    session_stop = threading.Event()

    class FakeVirt:
        in_waiting = 1

        def read(self, _size):
            data = pending.pop(0)
            if not pending:
                session_stop.set()
            return data

    session.forward_virtual_to_real(FakeVirt(), real, session_stop, SessionRetryState(), lock)


def test_no_question_goes_into_the_middle_of_a_command_being_forwarded(tmp_path):
    session, _auto_mode, _logger = _build_session(question=_question(tmp_path, [10.0]))
    real, lock = MagicMock(), threading.Lock()
    _forward(session, real, lock, b"L05")
    real.write.reset_mock()

    session.tick(object(), real_port=real, serial_write_lock=lock)

    real.write.assert_not_called()


def test_the_question_goes_out_once_the_command_being_forwarded_has_ended(tmp_path):
    session, _auto_mode, _logger = _build_session(question=_question(tmp_path, [10.0]))
    real, lock = MagicMock(), threading.Lock()
    _forward(session, real, lock, b"L05", b"00I100\n")
    real.write.reset_mock()

    session.tick(object(), real_port=real, serial_write_lock=lock)

    real.write.assert_called_once_with(DeviceQuestion.QUESTION)


def test_no_question_goes_out_while_the_device_runs_its_own_auto_mode(tmp_path):
    session, _auto_mode, _logger = _build_session(auto_active=True,
                                                  question=_question(tmp_path, [10.0]))
    real = MagicMock()

    session.tick(object(), real_port=real,
                                           serial_write_lock=threading.Lock())

    real.write.assert_not_called()


def test_a_device_running_its_own_auto_mode_is_judged_by_what_it_says_unasked(tmp_path):
    question = _question(tmp_path, [10.0])
    question.heard("TCode v0.3")
    publish_stamp(tmp_path / OSR2_SERIAL_RX)
    session, _auto_mode, _logger = _build_session(auto_active=True, question=question)

    session.tick(object(), real_port=MagicMock(),
                                           serial_write_lock=threading.Lock())

    assert switched_on(tmp_path, now=time.time() + ANSWERS_ONCE_OFF_S + 1.0)


def test_the_devices_answer_is_stamped_as_it_arrives(tmp_path):
    session, _auto_mode, _logger = _build_session(question=_question(tmp_path, [10.0]))
    session_stop = threading.Event()

    class FakeReal:
        in_waiting = 12

        def read(self, _size):
            session_stop.set()
            return b"TCode v0.3\r\n"

    session.forward_real_to_virtual(FakeReal(), MagicMock(), object(), session_stop,
                                    SessionRetryState())

    assert stamp_age(tmp_path / "osr2_serial_answer.txt") is not None


def test_the_devices_own_auto_mode_outlasts_a_quiet_spell_while_it_is_switched_on():
    session, auto_mode, _logger = _build_session(auto_active=True, device_on=lambda: True)

    session.end_auto_mode_once_switched_off(object())

    assert auto_mode.set_auto_calls == []


class _NotAnsweringSpy:
    def __init__(self) -> None:
        self.heard_count = 0
        self.ticks: list[bool] = []

    def heard(self) -> None:
        self.heard_count += 1

    def tick(self, *, driving: bool) -> None:
        self.ticks.append(driving)


def test_a_word_from_the_osr2_is_passed_to_the_not_answering_watch():
    watch = _NotAnsweringSpy()
    session, _auto_mode, _logger = _build_session(not_answering=watch)
    session_stop = threading.Event()

    class FakeReal:
        in_waiting = 1

        def read(self, _size):
            session_stop.set()
            return b"hello\n"

    class FakeVirt:
        def write(self, data):
            pass

    session.forward_real_to_virtual(FakeReal(), FakeVirt(), object(), session_stop,
                                    SessionRetryState())

    assert watch.heard_count == 1


def test_each_tick_tells_the_not_answering_watch_whether_mfp_is_driving_the_osr2():
    clock = [10.0]
    watch = _NotAnsweringSpy()
    session, _auto_mode, _logger = _build_session(monotonic=lambda: clock[0],
                                                  not_answering=watch)
    session_stop = threading.Event()

    class FakeVirt:
        in_waiting = 3

        def read(self, _size):
            session_stop.set()
            return b"L09\n"

    session.forward_virtual_to_real(FakeVirt(), MagicMock(), session_stop, SessionRetryState(),
                                    threading.Lock())
    lock = threading.Lock()
    session.tick(object(), real_port=MagicMock(), serial_write_lock=lock)
    clock[0] = 20.0
    session.tick(object(), real_port=MagicMock(), serial_write_lock=lock)

    assert watch.ticks == [True, False]


def test_a_fired_hold_tells_the_motion_log_so_a_move_felt_too_early_can_be_laid_at_its_door(recorded_logger):
    logger, heard = recorded_logger
    clock = [10.0]
    session, _auto_mode, _logger = _build_session(monotonic=lambda: clock[0], logger=logger)
    lock = threading.Lock()

    session.handle_broker_command("PARK", object())
    clock[0] = 12.0
    session.tick(object(), real_port=MagicMock(), serial_write_lock=lock)

    assert "OSR2 driven by a hold" in [record.getMessage() for record in heard.records]
