"""The T-Code UDP listener, and the window a direct write opens behind it.

Genau drives the OSR2 straight over a loopback datagram, bypassing MFP. So does
a fired hold. Either way the device has just been told where to go, and MFP's
own stream has to be dropped for a moment rather than allowed to argue with it.
"""
from __future__ import annotations

import socket
import threading
import time
from unittest.mock import MagicMock

from osr2_broker.session import SessionRetryState
from osr2_broker.tcode_udp import TCodeWriteWindow, UdpTCodeListener

# `tcode_udp` reaches its socket through the stdlib module, so the tests that
# want to watch how one is set up have to replace it there -- which is the same
# object this file builds its own sockets from. Held here before anything is
# patched, so the stand-in has something real to delegate to.
_REAL_SOCKET = socket.socket


class _StampSpy:
    def __init__(self):
        self.marks = 0

    def mark(self) -> None:
        self.marks += 1


def test_a_fresh_window_is_shut():
    """Nothing has written directly yet, so MFP is the only voice and is heard."""
    window = TCodeWriteWindow(monotonic=lambda: 10.0)

    assert window.is_open() is False


def test_marking_opens_the_window():
    window = TCodeWriteWindow(monotonic=lambda: 10.0)

    window.mark()

    assert window.is_open() is True


def test_the_window_shuts_once_the_suppression_time_has_passed():
    """The other side of the same comparison: a direct write mutes MFP for a
    moment, not for the rest of the session."""
    clock = [10.0]
    window = TCodeWriteWindow(monotonic=lambda: clock[0])

    window.mark()
    clock[0] += TCodeWriteWindow.SUPPRESS_SECONDS

    assert window.is_open() is False


def test_the_window_stays_open_to_the_last_moment():
    clock = [10.0]
    window = TCodeWriteWindow(monotonic=lambda: clock[0])

    window.mark()
    clock[0] += TCodeWriteWindow.SUPPRESS_SECONDS - 0.001

    assert window.is_open() is True


def _free_port() -> int:
    """A port nobody is bound to, released before the listener claims it."""
    probe = _REAL_SOCKET(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _build_listener(port: int, *, tx_activity=None, window=None):
    return UdpTCodeListener(
        port=port,
        stop_event=threading.Event(),
        logger=MagicMock(),
        is_retryable_error=lambda _exc: False,
        window=window or TCodeWriteWindow(monotonic=lambda: 10.0),
        tx_activity=tx_activity or _StampSpy(),
    )


def _offer_until_taken(sender, port: int, payload: bytes, session_stop: threading.Event) -> None:
    """Keep offering ``payload`` on a thread until the listener has taken it.

    ``run`` binds its own socket inside the call under test, so there is no
    moment a test can watch for from outside -- and a datagram sent before that
    bind is dropped rather than queued. So it is re-offered rather than timed,
    which lands the instant the socket is up and cannot go red on a machine
    where 0.05 s was not enough.

    Re-offering cannot double up: the loop rereads ``session_stop`` before every
    receive, and the fakes here set it from the write, so anything still in
    flight is never read.

    Offering into a port nobody has bound draws an ICMP port-unreachable, which
    Windows reports back on the *sending* socket -- and an unhandled one here
    would kill this thread quietly, leaving the call under test to block until
    the whole run is cut down. So a failed offer is simply the next offer.
    """
    def _offer() -> None:
        while True:
            try:
                sender.sendto(payload, ("127.0.0.1", port))
            except OSError:
                pass
            if session_stop.wait(0.02):
                return

    threading.Thread(target=_offer, daemon=True).start()


def test_a_datagram_reaches_the_serial_port():
    port = _free_port()
    listener = _build_listener(port)
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeReal:
        def __init__(self):
            self.writes: list[bytes] = []

        def write(self, data: bytes):
            self.writes.append(data)
            session_stop.set()

    real = FakeReal()
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _offer_until_taken(sender, port, b"L05000I33", session_stop)

    listener.run(real, session_stop, retry_state, threading.Lock())

    sender.close()
    assert real.writes == [b"L05000I33\n"]


def test_one_datagram_carrying_several_lines_becomes_several_writes():
    port = _free_port()
    listener = _build_listener(port)
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    received: list[bytes] = []

    class FakeReal:
        def write(self, data: bytes):
            received.append(data)
            if len(received) >= 2:
                session_stop.set()

    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _offer_until_taken(sender, port, b"L05000I33\nL09999I33", session_stop)

    listener.run(FakeReal(), session_stop, retry_state, threading.Lock())

    sender.close()
    assert received == [b"L05000I33\n", b"L09999I33\n"]


def test_blank_lines_around_a_command_are_dropped_and_it_is_not():
    """One datagram carries both, so the proof is positive and needs no waiting
    out: if a blank line could reach the port, the writes would not be exactly
    the one real command. Splitting them across two datagrams would leave the
    blank half unverified whenever the socket bound between the two.
    """
    port = _free_port()
    listener = _build_listener(port)
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeReal:
        def __init__(self):
            self.writes: list[bytes] = []

        def write(self, data: bytes):
            self.writes.append(data)
            session_stop.set()

    real = FakeReal()
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _offer_until_taken(sender, port, b"\n\nL05000I33\n\n", session_stop)

    listener.run(real, session_stop, retry_state, threading.Lock())

    sender.close()
    assert real.writes == [b"L05000I33\n"]


def test_a_forwarded_datagram_stamps_the_tx_activity_file(tmp_path):
    from osr2_broker.activity import ActivityStamp

    port = _free_port()
    tx_file = tmp_path / "osr2_serial_tx.txt"
    listener = _build_listener(
        port, tx_activity=ActivityStamp(tx_file, wall_clock=lambda: 1711900000.0),
    )
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeReal:
        def write(self, data: bytes):
            session_stop.set()

    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _offer_until_taken(sender, port, b"L05000I33", session_stop)

    listener.run(FakeReal(), session_stop, retry_state, threading.Lock())

    sender.close()
    assert float(tx_file.read_text()) == 1711900000.0


def test_a_forwarded_datagram_mutes_mfp_behind_it():
    """MFP and Genau both drive the same device. Whichever spoke last wins for
    the length of the window, and here that is the datagram."""
    port = _free_port()
    window = TCodeWriteWindow(monotonic=lambda: 10.0)
    listener = _build_listener(port, window=window)
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    class FakeReal:
        def write(self, data: bytes):
            session_stop.set()

    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _offer_until_taken(sender, port, b"L05000I33", session_stop)

    listener.run(FakeReal(), session_stop, retry_state, threading.Lock())

    sender.close()
    assert window.is_open() is True


class _RecordingSocket:
    """A real datagram socket that keeps a note of how it was set up."""

    def __init__(self, record: dict, *, bind_error: Exception | None = None):
        self._record = record
        self._bind_error = bind_error
        self._real = _REAL_SOCKET(socket.AF_INET, socket.SOCK_DGRAM)
        record["closed"] = False

    def settimeout(self, seconds):
        self._record["timeout"] = seconds
        self._real.settimeout(seconds)

    def bind(self, address):
        self._record["bound_to"] = address
        if self._bind_error is not None:
            raise self._bind_error
        self._real.bind(address)

    def recvfrom(self, size):
        return self._real.recvfrom(size)

    def close(self):
        self._record["closed"] = True
        self._real.close()


def test_the_listener_binds_loopback_only(monkeypatch):
    """T-Code drives the device. A listener reachable from the network is one
    anybody on it can drive, so the address is pinned, not just the port."""
    record: dict = {}
    monkeypatch.setattr(
        "osr2_broker.tcode_udp.socket.socket",
        lambda *_a, **_kw: _RecordingSocket(record),
    )
    port = _free_port()
    listener = _build_listener(port)
    session_stop = threading.Event()
    session_stop.set()  # one pass through the guard and out

    listener.run(MagicMock(), session_stop, SessionRetryState(), threading.Lock())

    assert record["bound_to"] == ("127.0.0.1", port)
    assert record["closed"] is True


def test_a_quiet_listener_still_notices_the_session_ending():
    """The receive is what the loop blocks in, so its timeout is the only thing
    that gets the stop flag looked at again. Without one, `run` sits in
    `recvfrom` forever and `run()`'s `thread_tcode.join(timeout=1.0)` returns
    with the thread still holding the port -- so the next session cannot bind
    it."""
    port = _free_port()
    listener = _build_listener(port)
    session_stop = threading.Event()

    threading.Timer(0.05, session_stop.set).start()
    started = time.monotonic()
    listener.run(MagicMock(), session_stop, SessionRetryState(), threading.Lock())
    took = time.monotonic() - started

    assert took < 5.0, f"the listener took {took:.1f}s to notice the session had ended"


def test_a_listener_that_cannot_bind_ends_the_session_and_says_whether_to_retry(monkeypatch):
    """Its port is usually still held by the session that just died, so this is
    the ordinary case on a reconnect, not an exotic one: the session has to end
    and the caller has to be told it is worth opening another."""
    record: dict = {}
    monkeypatch.setattr(
        "osr2_broker.tcode_udp.socket.socket",
        lambda *_a, **_kw: _RecordingSocket(record, bind_error=OSError("address in use")),
    )
    listener = _build_listener(_free_port())
    listener._is_retryable_error = lambda _exc: True
    session_stop = threading.Event()
    retry_state = SessionRetryState()

    listener.run(MagicMock(), session_stop, retry_state, threading.Lock())

    assert session_stop.is_set()
    assert retry_state.value is True
    assert record["closed"] is True
