from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .activity import ActivityStamp
from .hold import PARK, RETRACT, HoldScheduler
from .tcode_udp import TCodeWriteWindow, UdpTCodeListener


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
        rx_activity: ActivityStamp,
        tx_activity: ActivityStamp,
        connected_event: threading.Event,
        is_retryable_error,
        monotonic=time.monotonic,
        sleep=time.sleep,
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
        self.is_retryable_error = is_retryable_error
        self.connected_event = connected_event
        self.last_real_rx_time = 0.0
        self.poll_interval_seconds = 0.05
        self._rx_activity = rx_activity
        self._tx_activity = tx_activity
        self._holds = HoldScheduler(monotonic=monotonic, logger=logger)
        self._tcode_window = TCodeWriteWindow(monotonic=monotonic)
        self._tcode_listener = UdpTCodeListener(
            port=tcode_udp_port,
            stop_event=stop_event,
            logger=logger,
            is_retryable_error=self.is_retryable_error,
            window=self._tcode_window,
            tx_activity=tx_activity,
        ) if tcode_udp_port else None

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
                    if self._tcode_listener is not None:
                        thread_tcode = self.start_thread(
                            target=self._tcode_listener.run,
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
        except Exception as exc:
            self.logger.exception("Failed to open or run serial session")
            retry_state.value = self.is_retryable_error(exc)
        finally:
            self.connected_event.clear()

        return peer_disconnected or retry_state.value

    def forward_real_to_virtual(self, real, virt, udp_sock, session_stop, retry_state: SessionRetryState) -> None:
        buf = bytearray()
        while not self.stop_event.is_set() and not session_stop.is_set():
            try:
                data = real.read(real.in_waiting or 1)
                if not data:
                    continue

                self.last_real_rx_time = self.monotonic()
                self._rx_activity.mark()
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
                                serial_write_lock: threading.Lock) -> None:
        while not self.stop_event.is_set() and not session_stop.is_set():
            try:
                queued = virt.in_waiting
                data = virt.read(queued or 1)
                if not data:
                    continue
                if (not self.auto_mode.is_active
                        and not self._tcode_window.is_open()
                        and not self._holds.suppresses_mfp()):
                    with serial_write_lock:
                        real.write(data)
                    if queued:
                        self._tx_activity.mark()
            except Exception as exc:
                self.logger.exception("VIRT->REAL error")
                retry_state.value = self.is_retryable_error(exc)
                session_stop.set()
                return

    def tick_command_and_stale_timeout(self, udp_sock, *, real_port, serial_write_lock) -> None:
        for cmd in self.consume_command(self.broker_cmd_file):
            self.handle_broker_command(cmd, udp_sock)
        self.sync_genau_enabled(udp_sock)
        self.maybe_disable_stale_auto(udp_sock)
        if self.auto_mode.consume_deactivation():
            self._holds.schedule_without_muting(PARK, "Auto mode deactivated: park scheduled")
        self._holds.fire_due(real_port, serial_write_lock, self._tcode_window.mark)

    def handle_broker_command(self, cmd: str | None, udp_sock) -> None:
        """Act on one verb off the command file, or on nothing at all.

        Most ticks bring no command, and a sibling may write a verb this broker
        has no handler for; both fall through to a no-op.
        """
        verb = self._VERBS.get(cmd)
        if verb is not None:
            verb(self, udp_sock)

    def _pause(self, _udp_sock) -> None:
        self.broker_paused.set()
        self.logger.info("OmniPause: broker paused")

    def _resume(self, _udp_sock) -> None:
        self.broker_paused.clear()
        self._holds.cancel()
        self.logger.info("OmniPause: broker resumed")

    def _park(self, _udp_sock) -> None:
        self._holds.schedule(PARK, "OmniPause: park scheduled")

    def _retract(self, _udp_sock) -> None:
        self._holds.schedule(RETRACT, "OmniPause: retract scheduled")

    def _genau_disable(self, udp_sock) -> None:
        self.auto_mode.set_enabled(udp_sock, False)

    def _genau_enable(self, udp_sock) -> None:
        self.auto_mode.set_enabled(udp_sock, True)

    # The whole vocabulary, in one place. fun_time, genau and clipper write
    # these into broker_cmd.txt; the family's consumer upper-cases whatever it reads,
    # so the keys are the verbs as they arrive.
    _VERBS = MappingProxyType({
        "PAUSE": _pause,
        "RESUME": _resume,
        "PARK": _park,
        "RETRACT": _retract,
        "GENAU_DISABLE": _genau_disable,
        "GENAU_ENABLE": _genau_enable,
    })

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
