from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from osr2_broker.activity import ActivityStamp
from osr2_broker.hold import HoldScheduler
from osr2_broker.session import BrokerSerialSession, SessionRetryState


class NotActuallyRunning:
    """What `start_thread` hands back when a test only needs `run` to get on.

    `run` does nothing with a worker but join it, so a stub is enough -- and
    starting real threads here would make these tests the first to fall over
    when the process is already carrying the ones another test left spinning.
    """

    def join(self, timeout=None) -> None:
        pass


class StampSpy:
    """Stands in for an ActivityStamp where the test is not about the stamp.

    The stamp's own file, throttle and clock are covered in
    tests/test_activity.py; the tests here that do care about what lands on disk
    hand the session a real ActivityStamp over a tmp_path instead.
    """

    def __init__(self):
        self.marks = 0

    def mark(self) -> None:
        self.marks += 1


class FakeAutoMode:
    def __init__(self, *, active: bool = False):
        self.active = active
        self.handle_line_calls: list[str] = []
        self.set_auto_calls: list[tuple[object, bool]] = []
        self.set_enabled_calls: list[tuple[object, bool]] = []
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

    def set_enabled(self, sock, value: bool) -> None:
        self.set_enabled_calls.append((sock, value))

    def consume_deactivation(self) -> bool:
        if self._deactivated:
            self._deactivated = False
            return True
        return False


def _build_session(*, auto_active: bool = False, monotonic=lambda: 10.0,
                    rx_activity=None, tx_activity=None,
                    is_retryable_error=lambda _exc: False,
                    tcode_udp_port: int = 0):
    auto_mode = FakeAutoMode(active=auto_active)
    logger = MagicMock()
    session = BrokerSerialSession(
        serial_factory=MagicMock(),
        virtual_port="COM15",
        real_port="COM4",
        baud=115200,
        broker_cmd_file=Path("broker.cmd"),
        genau_enabled_file=Path("genau_enabled.txt"),
        auto_stale_timeout=2.0,
        stop_event=threading.Event(),
        broker_paused=threading.Event(),
        auto_mode=auto_mode,
        logger=logger,
        start_thread=MagicMock(),
        consume_command=lambda _path: [],
        read_genau_enabled=lambda _path: True,
        monotonic=monotonic,
        rx_activity=rx_activity or StampSpy(),
        tx_activity=tx_activity or StampSpy(),
        connected_event=threading.Event(),
        is_retryable_error=is_retryable_error,
        tcode_udp_port=tcode_udp_port,
    )
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
    session, _auto_mode, logger = _build_session(monotonic=lambda: clock[0])
    real_port = MagicMock()
    lock = threading.Lock()
    sock = object()

    session.handle_broker_command("PARK", sock)
    # Not written yet — still pending
    session.tick_command_and_stale_timeout(sock, real_port=real_port, serial_write_lock=lock)
    real_port.write.assert_not_called()

    # Advance past the delay
    clock[0] = 12.0
    session.tick_command_and_stale_timeout(sock, real_port=real_port, serial_write_lock=lock)
    real_port.write.assert_called_once_with(b"L00000I500\n")


def test_park_suppresses_mfp_forwarding():
    clock = [10.0]
    session, _auto_mode, _logger = _build_session(monotonic=lambda: clock[0])
    real_port = MagicMock()
    lock = threading.Lock()
    sock = object()

    session.handle_broker_command("PARK", sock)
    clock[0] = 12.0
    session.tick_command_and_stale_timeout(sock, real_port=real_port, serial_write_lock=lock)
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
    session.tick_command_and_stale_timeout(sock, real_port=real_port, serial_write_lock=lock)
    real_port.write.assert_not_called()


def test_retract_schedules_the_far_end_instead_of_home():
    """RETRACT is PARK's antonym: same settle delay, opposite end of the travel.

    Park sends the device home (position 0); retract sends it as far away as it
    goes (9999), which is what the sensation emergency asks for.
    """
    clock = [10.0]
    session, _auto_mode, _logger = _build_session(monotonic=lambda: clock[0])
    real_port = MagicMock()
    lock = threading.Lock()

    sock = object()

    session.handle_broker_command("RETRACT", sock)
    session.tick_command_and_stale_timeout(sock, real_port=real_port, serial_write_lock=lock)
    real_port.write.assert_not_called()

    clock[0] = 12.0
    session.tick_command_and_stale_timeout(sock, real_port=real_port, serial_write_lock=lock)
    real_port.write.assert_called_once_with(b"L09999I500\n")


def test_fired_hold_is_logged_as_the_position_it_actually_wrote():
    """The log names the end the device went to, so a retract is never read back
    as a park at position 0 when someone is tracing where the OSR2 went."""
    clock = [10.0]
    session, _auto_mode, logger = _build_session(monotonic=lambda: clock[0])
    lock = threading.Lock()
    sock = object()

    session.handle_broker_command("RETRACT", sock)
    clock[0] = 12.0
    session.tick_command_and_stale_timeout(sock, real_port=MagicMock(), serial_write_lock=lock)

    fired = [call.args[0] for call in logger.info.call_args_list]
    assert any("retracting" in msg and "9999" in msg for msg in fired), fired
    assert not any("parking" in msg for msg in fired), fired


def test_auto_mode_deactivation_schedules_park():
    clock = [10.0]
    session, auto_mode, _logger = _build_session(auto_active=True, monotonic=lambda: clock[0])
    real_port = MagicMock()
    lock = threading.Lock()
    sock = object()

    # Deactivate auto mode via stale timeout
    session.last_real_rx_time = 7.0
    session.tick_command_and_stale_timeout(sock, real_port=real_port, serial_write_lock=lock)

    # Park is pending now (auto went inactive), and the settle delay is not up
    real_port.write.assert_not_called()

    # Advance past delay
    clock[0] = 12.0
    session.tick_command_and_stale_timeout(sock, real_port=real_port, serial_write_lock=lock)
    real_port.write.assert_called_once_with(b"L00000I500\n")


def test_auto_mode_deactivation_between_ticks_schedules_park():
    """Auto mode going inactive on the real thread (between ticks) must still be detected."""
    clock = [10.0]
    session, auto_mode, _logger = _build_session(auto_active=True, monotonic=lambda: clock[0])
    real_port = MagicMock()
    lock = threading.Lock()
    sock = object()

    # Simulate auto mode going inactive on the real-serial thread
    auto_mode.set_auto(sock, False)

    # Next tick should detect the deactivation via the flag
    session.tick_command_and_stale_timeout(sock, real_port=real_port, serial_write_lock=lock)
    real_port.write.assert_not_called()

    clock[0] = 12.0
    session.tick_command_and_stale_timeout(sock, real_port=real_port, serial_write_lock=lock)
    real_port.write.assert_called_once_with(b"L00000I500\n")


def test_handle_broker_command_toggles_genau_enablement():
    session, auto_mode, logger = _build_session()
    sock = object()

    session.handle_broker_command("GENAU_DISABLE", sock)
    session.handle_broker_command("GENAU_ENABLE", sock)

    assert auto_mode.set_enabled_calls == [(sock, False), (sock, True)]
    logger.info.assert_not_called()


def test_a_verb_the_broker_does_not_know_is_ignored():
    """The command file is a shared channel: fun_time, genau and clipper all
    write into it, and one of them growing a verb this broker has no handler for
    must be a no-op, not a crash inside the 50 ms tick."""
    session, auto_mode, logger = _build_session()

    session.handle_broker_command("TELEPORT", object())

    assert auto_mode.set_enabled_calls == []
    assert not session.broker_paused.is_set()
    logger.info.assert_not_called()
    logger.warning.assert_not_called()


def test_an_empty_tick_with_no_command_is_a_no_op():
    """Almost every tick reads no command at all -- twenty times a second, all
    session long -- so `None` has to fall through the whole table quietly."""
    session, auto_mode, logger = _build_session()

    session.handle_broker_command(None, object())

    assert auto_mode.set_enabled_calls == []
    assert not session.broker_paused.is_set()
    logger.info.assert_not_called()


def test_sync_genau_enabled_reads_shared_file_state():
    session, auto_mode, _logger = _build_session()
    session.read_genau_enabled = lambda _path: False
    sock = object()

    session.sync_genau_enabled(sock)

    assert auto_mode.set_enabled_calls == [(sock, False)]


def test_maybe_disable_stale_auto_turns_off_auto_when_stale():
    session, auto_mode, logger = _build_session(auto_active=True, monotonic=lambda: 10.0)
    session.last_real_rx_time = 7.0
    sock = object()

    session.maybe_disable_stale_auto(sock)

    assert auto_mode.set_auto_calls == [(sock, False)]
    logger.warning.assert_called_once_with("AUTO stale timeout reached after %.2fs", 2.0)


def test_maybe_disable_stale_auto_leaves_a_paused_broker_alone():
    """Paused means the user took over; even a genuinely stale rx must not
    flip AUTO without them knowing."""
    session, auto_mode, logger = _build_session(auto_active=True, monotonic=lambda: 10.0)
    session.broker_paused.set()
    session.last_real_rx_time = 7.0  # stale: 3s old against a 2s timeout

    session.maybe_disable_stale_auto(object())

    assert auto_mode.set_auto_calls == []
    logger.warning.assert_not_called()


def test_maybe_disable_stale_auto_keeps_auto_on_while_rx_is_fresh():
    """The fresh side of the timeout, pinned on its own: before this, deleting
    the staleness comparison outright left the suite green (audit finding
    broker/all/tests/001) — the timeout could degrade into 'AUTO off on every
    tick' unnoticed."""
    session, auto_mode, logger = _build_session(auto_active=True, monotonic=lambda: 10.0)
    session.last_real_rx_time = 10.0 - 1.9  # 0.1s inside the 2s timeout

    session.maybe_disable_stale_auto(object())

    assert auto_mode.set_auto_calls == []
    logger.warning.assert_not_called()


def test_maybe_disable_stale_auto_waits_until_something_has_been_received():
    """Before the first real byte there is nothing to be stale relative to."""
    session, auto_mode, logger = _build_session(auto_active=True, monotonic=lambda: 10.0)
    session.last_real_rx_time = 0.0

    session.maybe_disable_stale_auto(object())

    assert auto_mode.set_auto_calls == []
    logger.warning.assert_not_called()


def test_maybe_disable_stale_auto_ignores_an_inactive_auto_mode():
    session, auto_mode, logger = _build_session(auto_active=False, monotonic=lambda: 10.0)
    session.last_real_rx_time = 7.0  # stale, but there is no AUTO to turn off

    session.maybe_disable_stale_auto(object())

    assert auto_mode.set_auto_calls == []
    logger.warning.assert_not_called()


def test_forward_real_to_virtual_updates_timestamp_and_handles_lines():
    session, auto_mode, _logger = _build_session(monotonic=lambda: 12.5)
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

    assert session.last_real_rx_time == 12.5
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


def test_forward_virtual_to_real_skips_writes_while_tcode_udp_active():
    clock = [9.9]
    session, _auto_mode, _logger = _build_session(monotonic=lambda: clock[0])
    session._tcode_window.mark()
    clock[0] = 10.0  # 0.1s ago — within suppression window
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


def test_forward_virtual_to_real_allows_writes_when_tcode_udp_idle():
    clock = [9.0]
    session, _auto_mode, _logger = _build_session(monotonic=lambda: clock[0])
    session._tcode_window.mark()
    clock[0] = 10.0  # 1.0s ago — outside suppression window
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
    """A lost RESUME must not mute MFP forever. Within the grace window after a
    PARK, MFP is swallowed (so it can't immediately un-park the device); once the
    window elapses, sustained MFP data clears the latch and forwarding resumes."""
    clock = [100.0]
    session, _auto_mode, _logger = _build_session(monotonic=lambda: clock[0])
    session.handle_broker_command("PARK", object())  # suppressed at t=100
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

    clock[0] = 100.0 + HoldScheduler.SUPPRESS_GRACE_SECONDS + 0.1  # past grace
    real = FakeReal()
    session.forward_virtual_to_real(FakeVirt(), real, session_stop, retry_state, threading.Lock())

    assert real.writes == [b"L05000\n"]


def test_park_suppression_holds_within_grace_window():
    """The tail of an in-flight script right after PARK is still swallowed, so the
    park write is not immediately undone by MFP's continuing stream."""
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

    clock[0] = 100.0 + 1.0  # still within grace
    real = FakeReal()
    session.forward_virtual_to_real(FakeVirt(), real, session_stop, retry_state, threading.Lock())

    assert real.writes == []


def test_resume_hands_mfp_back_without_waiting_out_the_grace():
    """RESUME undoes the whole hold. Cancelling only the pending write would
    leave MFP muted for the rest of the grace window with nothing on the way to
    clear it -- the user asks for motion and the device stays still."""
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

    clock[0] = 100.0 + 1.0  # still well inside the grace window
    real = FakeReal()
    session.forward_virtual_to_real(FakeVirt(), real, session_stop, retry_state, threading.Lock())

    assert real.writes == [b"L05000\n"]


def test_the_connected_event_is_set_while_the_ports_are_open_and_clear_after():
    """The heartbeat file is only written while this event is set, and fun_time
    reads that file to decide whether the broker is alive. Only the clearing
    half was pinned, so a session that never set it would have looked fine here
    and shown up as a broker that never starts."""
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
    session.start_thread = lambda *, target, args, name: NotActuallyRunning()

    session.run(object())

    assert seen_inside == [True]
    assert not session.connected_event.is_set()


def test_a_retryable_read_error_asks_the_caller_for_another_session():
    """The classifier is the caller's -- app.py's is_retryable_serial_error --
    and the forwarding thread's only job is to run it over what it caught and
    put the answer where `run` will return it."""
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

    should_retry = session.run(object())

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

    session.run(object())

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

    should_retry = session.run(object())

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
    """Drive `run` through a single poll and report what it put on threads.

    The names are recorded rather than run: `run` only ever joins what it is
    handed back.
    """
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
        return NotActuallyRunning()

    session.serial_factory = lambda *a, **kw: FakePort()
    session.sleep = lambda _s: session.stop_event.set()
    session.start_thread = _start
    session.run(object())
    return started


def test_a_configured_tcode_port_gets_a_listener_thread():
    """Genau's datagrams arrive on a thread of their own, and nothing else in
    the suite starts one -- so without this the port could stop being listened
    on and every other test would stay green."""
    session, _auto_mode, _logger = _build_session(tcode_udp_port=50557)

    assert _thread_names_started_by_one_run(session) == [
        "broker-real", "broker-virtual", "broker-tcode-udp",
    ]


def test_no_tcode_port_means_no_listener_thread():
    """Port 0 is how the listener is turned off; binding it would take an
    ephemeral port nobody can address and spin a thread on nothing."""
    session, _auto_mode, _logger = _build_session(tcode_udp_port=0)

    assert _thread_names_started_by_one_run(session) == ["broker-real", "broker-virtual"]
