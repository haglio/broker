from __future__ import annotations

import contextlib
import socket
import threading
import time
from unittest.mock import MagicMock

from osr2_broker.motion_log import UDP
from osr2_broker.session import SessionRetryState
from osr2_broker.tcode_udp import UdpTCodeListener, lets_through_unless_held

_REAL_SOCKET = socket.socket


def _free_port() -> int:
    probe = _REAL_SOCKET(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _nobody() -> None:
    pass


class _Dropped:
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
        lets_through=lets_through_unless_held(held_by, dropped or _Dropped()),
    )


class _Written:
    def __init__(self, session_stop: threading.Event, *, enough: int = 1):
        self.lines: list[tuple[str, str]] = []
        self._session_stop = session_stop
        self._enough = enough

    def __call__(self, source: str, line: str) -> None:
        self.lines.append((source, line))
        if len(self.lines) >= self._enough:
            self._session_stop.set()


def _offer_until_taken(sender, port: int, payload: bytes, session_stop: threading.Event) -> None:
    def _offer() -> None:
        while True:
            # Windows reports a port nobody has bound as an error on the sending socket.
            with contextlib.suppress(OSError):
                sender.sendto(payload, ("127.0.0.1", port))
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
    assert _listen_for(b"\n\nL05000I33\n\n") == [(UDP, "L05000I33")]


class _RecordingSocket:
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
    record: dict = {}
    monkeypatch.setattr(
        "osr2_broker.tcode_udp.socket.socket",
        lambda *_a, **_kw: _RecordingSocket(record),
    )
    port = _free_port()
    listener = _build_listener(port)
    session_stop = threading.Event()
    session_stop.set()

    listener.run(MagicMock(), session_stop, SessionRetryState())

    assert record["bound_to"] == ("127.0.0.1", port)
    assert record["timeout"] == 0.2, "the receive timeout is the session's only way out of recvfrom"
    assert record["closed"] is True


def test_a_quiet_listener_still_notices_the_session_ending():
    port = _free_port()
    listener = _build_listener(port)
    session_stop = threading.Event()

    threading.Timer(0.05, session_stop.set).start()
    started = time.monotonic()
    listener.run(MagicMock(), session_stop, SessionRetryState())
    took = time.monotonic() - started

    assert took < 1.0, f"the listener took {took:.1f}s to notice the session had ended"


def test_a_listener_that_cannot_bind_ends_the_session_and_says_whether_to_retry(monkeypatch):
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
