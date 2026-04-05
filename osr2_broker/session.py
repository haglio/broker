from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable



@dataclass
class SessionRetryState:
    value: bool = False


class BrokerSerialSession:
    def __init__(
        self,
        *,
        serial_factory,
        virtual_port: str,
        real_port: str,
        baud: int,
        broker_cmd_file: Path,
        genau_enabled_file: Path,
        auto_stale_timeout: float,
        stop_event,
        broker_paused,
        auto_mode,
        logger,
        start_thread,
        consume_command,
        read_genau_enabled,
        monotonic=time.monotonic,
        sleep=time.sleep,
        is_retryable_error=None,
        activity_rx_file: Path | None = None,
        activity_tx_file: Path | None = None,
        tcode_udp_port: int = 0,
    ):
        self.serial_factory = serial_factory
        self.virtual_port = virtual_port
        self.real_port = real_port
        self.baud = baud
        self.broker_cmd_file = broker_cmd_file
        self.genau_enabled_file = genau_enabled_file
        self.auto_stale_timeout = auto_stale_timeout
        self.stop_event = stop_event
        self.broker_paused = broker_paused
        self.auto_mode = auto_mode
        self.logger = logger
        self.start_thread = start_thread
        self.consume_command = consume_command
        self.read_genau_enabled = read_genau_enabled
        self.monotonic = monotonic
        self.sleep = sleep
        self.is_retryable_error = is_retryable_error or (lambda _exc: False)
        self.connected_event: threading.Event | None = None
        self.last_real_rx_time = 0.0
        self.poll_interval_seconds = 0.05
        self._activity_rx_file = activity_rx_file
        self._activity_tx_file = activity_tx_file
        self._last_rx_write: float = 0.0
        self._last_tx_write: float = 0.0
        self._wall_clock: Callable[[], float] = time.time
        self.tcode_udp_port = tcode_udp_port
        self._last_tcode_udp_time: float = 0.0
        self._pending_park_time: float | None = None

    @staticmethod
    def _peer_connected(port) -> bool:
        try:
            return port.dsr
        except (OSError, AttributeError):
            return True

    def run(self, udp_sock) -> bool:
        session_stop = threading.Event()
        retry_state = SessionRetryState()
        thread_real = None
        thread_virtual = None
        thread_tcode = None
        serial_write_lock = threading.Lock()
        peer_disconnected = False

        try:
            with self.serial_factory(self.virtual_port, self.baud, timeout=0.02) as virt, self.serial_factory(
                self.real_port,
                self.baud,
                timeout=0.02,
            ) as real:
                self.last_real_rx_time = 0.0
                virt.write_timeout = 0.1
                if self.connected_event is not None:
                    self.connected_event.set()
                try:
                    thread_real = self.start_thread(
                        target=self.forward_real_to_virtual,
                        args=(real, virt, udp_sock, session_stop, retry_state),
                        name="broker-real",
                    )
                    thread_virtual = self.start_thread(
                        target=self.forward_virtual_to_real,
                        args=(virt, real, session_stop, retry_state, serial_write_lock),
                        name="broker-virtual",
                    )
                    if self.tcode_udp_port:
                        thread_tcode = self.start_thread(
                            target=self.forward_udp_tcode_to_real,
                            args=(real, session_stop, retry_state, serial_write_lock),
                            name="broker-tcode-udp",
                        )

                    peer_was_connected = False
                    while not self.stop_event.is_set() and not session_stop.is_set():
                        self.sleep(self.poll_interval_seconds)
                        peer_up = self._peer_connected(virt)
                        if peer_up:
                            peer_was_connected = True
                        if not peer_up and peer_was_connected:
                            self.logger.warning("Virtual port peer disconnected (DSR low), ending session")
                            peer_disconnected = True
                            break
                        self.tick_command_and_stale_timeout(
                            udp_sock, real_port=real, serial_write_lock=serial_write_lock,
                        )
                finally:
                    session_stop.set()
                    if thread_real is not None:
                        thread_real.join(timeout=1.0)
                    if thread_virtual is not None:
                        thread_virtual.join(timeout=1.0)
                    if thread_tcode is not None:
                        thread_tcode.join(timeout=1.0)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            self.logger.exception("Failed to open or run serial session")
            retry_state.value = self.is_retryable_error(exc)
        finally:
            if self.connected_event is not None:
                self.connected_event.clear()

        return peer_disconnected or retry_state.value

    _ACTIVITY_WRITE_INTERVAL = 5.0
    _TCODE_UDP_SUPPRESS_SECONDS = 0.5

    def _write_activity(self, path: Path | None, last_attr: str) -> None:
        if path is None:
            return
        now = self._wall_clock()
        if now - getattr(self, last_attr) < self._ACTIVITY_WRITE_INTERVAL:
            return
        setattr(self, last_attr, now)
        try:
            path.write_text(str(now), encoding="utf-8")
        except OSError:
            pass

    def forward_real_to_virtual(self, real, virt, udp_sock, session_stop, retry_state: SessionRetryState) -> None:
        buf = bytearray()
        while not self.stop_event.is_set() and not session_stop.is_set():
            try:
                data = real.read(real.in_waiting or 1)
                if not data:
                    continue

                self.last_real_rx_time = self.monotonic()
                self._write_activity(self._activity_rx_file, "_last_rx_write")
                try:
                    virt.write(data)
                except OSError:
                    pass

                buf.extend(data)
                while b"\n" in buf:
                    raw_line, _, rest = buf.partition(b"\n")
                    buf[:] = rest
                    line = raw_line.rstrip(b"\r").decode("utf-8", errors="replace").strip()
                    if line:
                        self.auto_mode.handle_line(udp_sock, line)
            except Exception as exc:
                self.logger.exception("REAL->VIRT error")
                retry_state.value = self.is_retryable_error(exc)
                session_stop.set()
                return

    def forward_virtual_to_real(self, virt, real, session_stop, retry_state: SessionRetryState,
                               serial_write_lock: threading.Lock | None = None) -> None:
        while not self.stop_event.is_set() and not session_stop.is_set():
            try:
                queued = virt.in_waiting
                data = virt.read(queued or 1)
                if not data:
                    continue
                tcode_suppressed = (
                    self._last_tcode_udp_time > 0.0
                    and (self.monotonic() - self._last_tcode_udp_time) < self._TCODE_UDP_SUPPRESS_SECONDS
                )
                if not self.auto_mode.is_active and not tcode_suppressed:
                    if serial_write_lock is not None:
                        with serial_write_lock:
                            real.write(data)
                    else:
                        real.write(data)
                    if queued:
                        self._write_activity(self._activity_tx_file, "_last_tx_write")
            except Exception as exc:
                self.logger.exception("VIRT->REAL error")
                retry_state.value = self.is_retryable_error(exc)
                session_stop.set()
                return

    def forward_udp_tcode_to_real(self, real, session_stop, retry_state: SessionRetryState,
                                  serial_write_lock: threading.Lock) -> None:
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.settimeout(0.2)
        try:
            udp_sock.bind(("127.0.0.1", self.tcode_udp_port))
            while not self.stop_event.is_set() and not session_stop.is_set():
                try:
                    data, _addr = udp_sock.recvfrom(4096)
                except TimeoutError:
                    continue
                for line in data.decode("ascii", errors="replace").split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    self._last_tcode_udp_time = self.monotonic()
                    with serial_write_lock:
                        real.write((line + "\n").encode("ascii"))
                    self._write_activity(self._activity_tx_file, "_last_tx_write")
        except Exception as exc:
            self.logger.exception("T-Code UDP listener error")
            retry_state.value = self.is_retryable_error(exc)
            session_stop.set()
        finally:
            udp_sock.close()

    _PARK_DELAY_SECONDS = 1.0

    def tick_command_and_stale_timeout(self, udp_sock, *,
                                       real_port=None, serial_write_lock=None) -> None:
        cmd = self.consume_command(self.broker_cmd_file)
        was_auto = self.auto_mode.is_active
        self.handle_broker_command(cmd, udp_sock)
        self.sync_genau_enabled(udp_sock)
        self.maybe_disable_stale_auto(udp_sock)
        if was_auto and not self.auto_mode.is_active:
            self._pending_park_time = self.monotonic() + self._PARK_DELAY_SECONDS
            self.logger.info("Auto mode deactivated: park scheduled")
        self._maybe_fire_park(real_port, serial_write_lock)

    _PARK_TCODE = b"L00000I500\n"

    def handle_broker_command(self, cmd: str | None, udp_sock) -> None:
        if cmd == "PAUSE":
            self.broker_paused.set()
            self.logger.info("OmniPause: broker paused")
        elif cmd == "RESUME":
            self.broker_paused.clear()
            self._pending_park_time = None
            self.logger.info("OmniPause: broker resumed")
        elif cmd == "PARK":
            self._pending_park_time = self.monotonic() + self._PARK_DELAY_SECONDS
            self.logger.info("OmniPause: park scheduled")
        elif cmd == "ROBOT_HAND_DISABLE":
            self.auto_mode.set_enabled(udp_sock, False)
        elif cmd == "ROBOT_HAND_ENABLE":
            self.auto_mode.set_enabled(udp_sock, True)

    def _maybe_fire_park(self, real_port, serial_write_lock) -> None:
        if self._pending_park_time is None:
            return
        if self.monotonic() < self._pending_park_time:
            return
        self._pending_park_time = None
        if real_port is not None and serial_write_lock is not None:
            with serial_write_lock:
                real_port.write(self._PARK_TCODE)
            self._last_tcode_udp_time = self.monotonic()
            self.logger.info("OmniPause: parking OSR2 at position 0")
        else:
            self.logger.warning("Park fired but serial port not available")

    def sync_genau_enabled(self, udp_sock) -> None:
        enabled = self.read_genau_enabled(self.genau_enabled_file)
        self.auto_mode.set_enabled(udp_sock, enabled)

    def maybe_disable_stale_auto(self, udp_sock) -> None:
        if not self.auto_mode.is_active:
            return
        if self.broker_paused.is_set():
            return
        if not self.last_real_rx_time:
            return
        if self.monotonic() - self.last_real_rx_time <= self.auto_stale_timeout:
            return
        self.logger.warning("AUTO stale timeout reached after %.2fs", self.auto_stale_timeout)
        self.auto_mode.set_auto(udp_sock, False)
