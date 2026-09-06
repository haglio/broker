"""T-Code arriving over loopback UDP, and the mute that outlasts a direct write.

Genau sends the OSR2 its moves as datagrams, bypassing MFP entirely. A fired
hold writes to the device the same way. Both are "someone drove the device
directly just now", which is what MFP's forwarder has to know: two writers
fighting over one serial port make the device stutter between them, so the
window says whose turn it is not.
"""
from __future__ import annotations

import socket


class TCodeWriteWindow:
    """How recently T-Code went straight to the OSR2, bypassing MFP."""

    SUPPRESS_SECONDS = 0.5

    def __init__(self, *, monotonic):
        self._monotonic = monotonic
        self._last = 0.0

    def mark(self) -> None:
        self._last = self._monotonic()

    def is_open(self) -> bool:
        return self._last > 0.0 and (self._monotonic() - self._last) < self.SUPPRESS_SECONDS


class UdpTCodeListener:
    def __init__(self, *, port: int, stop_event, logger, is_retryable_error,
                 window: TCodeWriteWindow, tx_activity):
        self.port = port
        self._stop_event = stop_event
        self._logger = logger
        self._is_retryable_error = is_retryable_error
        self._window = window
        self._tx_activity = tx_activity

    def run(self, real, session_stop, retry_state, serial_write_lock) -> None:
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.settimeout(0.2)
        try:
            udp_sock.bind(("127.0.0.1", self.port))
            while not self._stop_event.is_set() and not session_stop.is_set():
                try:
                    data, _addr = udp_sock.recvfrom(4096)
                except TimeoutError:
                    continue
                for line in data.decode("ascii", errors="replace").split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    self._window.mark()
                    with serial_write_lock:
                        real.write((line + "\n").encode("ascii"))
                    self._tx_activity.mark()
        except Exception as exc:
            self._logger.exception("T-Code UDP listener error")
            retry_state.value = self._is_retryable_error(exc)
            session_stop.set()
        finally:
            udp_sock.close()
