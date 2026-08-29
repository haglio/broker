from __future__ import annotations

import re
import socket
import threading
from pathlib import Path


RE_BPM = re.compile(r"\bbpm\s+(\d+),\s+beats\s+(\d+)", re.IGNORECASE)
RE_STROKE = re.compile(r"StrokeName:\s*([^,]+),\s*PatternDuration:\s*([0-9.]+)", re.IGNORECASE)


def parse_auto_transition(line: str) -> bool | None:
    compact = " ".join(line.lower().replace("!", " ").split())
    mentions_auto_mode = any(token in compact for token in ("freemode", "free mode", "auto mode"))
    if not mentions_auto_mode:
        return None
    if "tcode task started" in compact or "is on" in compact:
        return True
    if "tcode task is stopped" in compact or "is off" in compact:
        return False
    return None


class BrokerAutoController:
    def __init__(
        self,
        *,
        state_file: Path,
        udp_host: str,
        udp_port: int,
        logger,
        write_mode,
        udp_send,
        enabled: bool = True,
    ):
        self.state_file = state_file
        self.udp_host = udp_host
        self.udp_port = udp_port
        self.logger = logger
        self.write_mode = write_mode
        self.udp_send = udp_send
        self._lock = threading.Lock()
        self._auto_active = False
        self._enabled = enabled
        self._deactivated = False

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._auto_active

    _SEED_BPM = 87

    def publish_effective_state(self, sock: socket.socket) -> None:
        with self._lock:
            effective_active = self._auto_active and self._enabled

        self.write_mode(self.state_file, "1" if effective_active else "0", self.logger)
        self.udp_send(sock, self.udp_host, self.udp_port, f"AUTO {1 if effective_active else 0}")
        self.udp_send(sock, self.udp_host, self.udp_port, "SHOW" if effective_active else "HIDE")
        if effective_active:
            self.udp_send(sock, self.udp_host, self.udp_port, f"BPM {self._SEED_BPM}")

    def set_auto(self, sock: socket.socket, value: bool) -> None:
        with self._lock:
            changed = self._auto_active != value
            self._auto_active = value
            if changed and not value:
                self._deactivated = True

        self.publish_effective_state(sock)

        if changed:
            self.logger.info("AUTO %s", "ON" if value else "OFF")

    def consume_deactivation(self) -> bool:
        with self._lock:
            if self._deactivated:
                self._deactivated = False
                return True
            return False

    def set_enabled(self, sock: socket.socket, value: bool) -> None:
        with self._lock:
            changed = self._enabled != value
            self._enabled = value

        if not changed:
            return

        self.publish_effective_state(sock)
        self.logger.info("Genau %s", "ENABLED" if value else "DISABLED")

    def handle_line(self, sock: socket.socket, line: str) -> None:
        low = line.lower()
        auto_transition = parse_auto_transition(line)

        if auto_transition is True:
            self.set_auto(sock, True)

        if auto_transition is False:
            self.set_auto(sock, False)

        stroke_match = RE_STROKE.search(line)
        if stroke_match:
            self.set_auto(sock, True)
            self.udp_send(sock, self.udp_host, self.udp_port, f"STROKE {stroke_match.group(1).strip()}")
            self.udp_send(sock, self.udp_host, self.udp_port, f"PATTERN {stroke_match.group(2)}")
            self.udp_send(sock, self.udp_host, self.udp_port, "SYNC")

        bpm_match = RE_BPM.search(line)
        if bpm_match:
            self.set_auto(sock, True)
            self.udp_send(sock, self.udp_host, self.udp_port, f"BPM {bpm_match.group(1)}")
            self.udp_send(sock, self.udp_host, self.udp_port, f"BEATS {bpm_match.group(2)}")

        if "continue strokename:" in low or "start transition" in low:
            self.udp_send(sock, self.udp_host, self.udp_port, "SYNC")
