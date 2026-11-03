"""T-Code arriving over loopback UDP, the inlet the OSR2's slot replaces.

Genau sends the OSR2 its moves as datagrams, bypassing MFP entirely, and so do
the Funestras and Origenerator, until each connects to the slot instead. Until
then the inlet stays, but only while nobody holds the slot.
"""
from __future__ import annotations

import socket
from collections.abc import Callable

from .motion_log import UDP, RunLog


def lets_through_unless_held(held_by: Callable[[], str | None], dropped: RunLog) -> Callable[[], bool]:
    def lets_through() -> bool:
        holder = held_by()
        if holder is None:
            return True
        dropped.happened(holder)
        return False
    return lets_through


class UdpTCodeListener:
    def __init__(self, *, port: int, stop_event, logger, is_retryable_error,
                 lets_through: Callable[[], bool]):
        self.port = port
        self._stop_event = stop_event
        self._logger = logger
        self._is_retryable_error = is_retryable_error
        self._lets_through = lets_through

    def run(self, write, session_stop, retry_state) -> None:
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.settimeout(0.2)
        try:
            udp_sock.bind(("127.0.0.1", self.port))
            while not self._stop_event.is_set() and not session_stop.is_set():
                try:
                    data, _addr = udp_sock.recvfrom(4096)
                except TimeoutError:
                    continue
                for part in data.decode("ascii", errors="replace").split("\n"):
                    line = part.strip()
                    if line and self._lets_through():
                        write(UDP, line)
        except Exception as exc:
            self._logger.exception("T-Code UDP listener error")
            retry_state.value = self._is_retryable_error(exc)
            session_stop.set()
        finally:
            udp_sock.close()
