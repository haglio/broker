"""The T-Code UDP listener: datagrams taken off loopback, split into lines and
handed on. How a line is written once it is in is the session's, in
tests/test_session.py.
"""
from __future__ import annotations

import socket
import threading
import time
from unittest.mock import MagicMock

from osr2_broker.motion_log import UDP
from osr2_broker.session import SessionRetryState
from osr2_broker.tcode_udp import UdpTCodeListener

# `tcode_udp` reaches its socket through the stdlib module, so the tests that
# want to watch how one is set up have to replace it there -- which is the same
# object this file builds its own sockets from. Held here before anything is
# patched, so the stand-in has something real to delegate to.
_REAL_SOCKET = socket.socket


def _free_port() -> int:
    """A port nobody is bound to, released before the listener claims it."""
    probe = _REAL_SOCKET(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _nobody() -> None:
    """Who holds the OSR2's slot, where nobody does."""


class _Dropped:
    """The log of what was dropped while the slot was held: whose it was, a line
    at a time."""

    def __init__(self):
        self.while_held_by: list[str] = []

    def happened(self, holder: str) -> None:
        self.while_held_by.append(holder)


def _build_listener(port: int, *, held_by=_nobody, dropped=None):
    return UdpTCodeListener(
        port=port,
        stop_event=threading.Event(),
        logger=MagicMock(),
        is_retryable_error=lambda _exc: False,
        held_by=held_by,
        dropped=dropped or _Dropped(),
    )


class _Written:
    """The session's writer, as the listener is handed it: what it was given,
    and the session ended once it has been given ``enough``."""

    def __init__(self, session_stop: threading.Event, *, enough: int = 1):
        self.lines: list[tuple[str, str]] = []
        self._session_stop = session_stop
        self._enough = enough

    def __call__(self, source: str, line: str) -> None:
        self.lines.append((source, line))
        if len(self.lines) >= self._enough:
            self._session_stop.set()


def _offer_until_taken(sender, port: int, payload: bytes, session_stop: threading.Event) -> None:
    """Keep offering ``payload`` on a thread until the listener has taken it.

    ``run`` binds its own socket inside the call under test, so there is no
    moment a test can watch for from outside -- and a datagram sent before that
    bind is dropped rather than queued. So it is re-offered rather than timed,
    which lands the instant the socket is up and cannot go red on a machine
    where 0.05 s was not enough.

    Re-offering cannot double up: the loop rereads ``session_stop`` before every
    receive, and the writers here set it, so anything still in flight is never
    read.

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


def _listen_for(payload: bytes, *, enough: int = 1, **listener) -> list[tuple[str, str]]:
    port = _free_port()
    listener = _build_listener(port, **listener)
    session_stop = threading.Event()
    written = _Written(session_stop, enough=enough)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _offer_until_taken(sender, port, payload, session_stop)

    listener.run(written, session_stop, SessionRetryState())

    sender.close()
    return written.lines


def test_a_datagram_is_handed_on_as_t_code_udp():
    assert _listen_for(b"L05000I33") == [(UDP, "L05000I33")]


def test_a_datagram_arriving_while_a_sender_holds_the_slot_is_dropped_and_told():
    """The UDP inlet stays for the senders not yet moved to the OSR2's slot, and
    only while nobody holds it.

    Proved positively rather than by waiting a datagram out: the same line is
    re-offered until one is written, and the slot is held only for the first.
    """
    asked = []

    def held_by() -> str | None:
        asked.append(True)
        return "portrait" if len(asked) == 1 else None

    dropped = _Dropped()

    written = _listen_for(b"L05000I33", held_by=held_by, dropped=dropped)

    assert dropped.while_held_by == ["portrait"]
    assert written == [(UDP, "L05000I33")]


def test_one_datagram_carrying_several_lines_becomes_several_writes():
    assert _listen_for(b"L05000I33\nL09999I33", enough=2) == [
        (UDP, "L05000I33"), (UDP, "L09999I33"),
    ]


def test_blank_lines_around_a_command_are_dropped_and_it_is_not():
    """One datagram carries both, so the proof is positive and needs no waiting
    out: if a blank line could reach the writer, what it was handed would not be
    exactly the one real command. Splitting them across two datagrams would leave
    the blank half unverified whenever the socket bound between the two.
    """
    assert _listen_for(b"\n\nL05000I33\n\n") == [(UDP, "L05000I33")]


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


def test_the_listener_binds_loopback_only_and_gives_itself_a_way_out(monkeypatch):
    """T-Code drives the device, so a listener reachable from the network is one
    anybody on it can drive: the address is pinned, not just the port. The
    receive timeout is pinned here too, because it is the only thing that gets
    `session_stop` looked at again once the loop is in `recvfrom`."""
    record: dict = {}
    monkeypatch.setattr(
        "osr2_broker.tcode_udp.socket.socket",
        lambda *_a, **_kw: _RecordingSocket(record),
    )
    port = _free_port()
    listener = _build_listener(port)
    session_stop = threading.Event()
    session_stop.set()  # one pass through the guard and out

    listener.run(MagicMock(), session_stop, SessionRetryState())

    assert record["bound_to"] == ("127.0.0.1", port)
    assert record["timeout"] == 0.2, "the receive timeout is the session's only way out of recvfrom"
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
    listener.run(MagicMock(), session_stop, SessionRetryState())
    took = time.monotonic() - started

    # The bound is `run()`'s own `thread_tcode.join(timeout=1.0)`: past it the join
    # returns with the listener still holding the port and the next session cannot
    # bind it. One receive timeout is 0.2 s, and this measures 0.20-0.21 s.
    assert took < 1.0, f"the listener took {took:.1f}s to notice the session had ended"


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

    listener.run(MagicMock(), session_stop, retry_state)

    assert session_stop.is_set()
    assert retry_state.value is True
    assert record["closed"] is True
