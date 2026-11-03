from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from app_support import osr2_hold
from app_support.osr2_slot import Osr2Slot

from .activity import ActivityStamp
from .hold import PARK, RETRACT, HoldScheduler
from .motion_log import HOLD, MFP, driven_from_outside, dropped_udp_log, motion_log, tcode_from
from .not_answering import NotAnsweringWatch
from .power_on import PowerOnWatch
from .question import DeviceQuestion
from .tcode_udp import UdpTCodeListener, lets_through_unless_held
from .tcode_window import TCodeWriteWindow


@dataclass
class SessionRetryState:
    value: bool = False


@dataclass(frozen=True)
class SerialLink:
    serial_factory: Callable
    virtual_port: str
    baud: int
    is_retryable_error: Callable[[BaseException], bool]


@dataclass(frozen=True)
class SessionControls:
    broker_cmd_file: Path
    consume_command: Callable
    stop_event: threading.Event
    broker_paused: threading.Event
    connected_event: threading.Event


@dataclass(frozen=True)
class DeviceWatches:
    device_on: Callable[[], bool]
    rx_activity: ActivityStamp
    tx_activity: ActivityStamp
    power_on: PowerOnWatch
    question: DeviceQuestion | None = None
    not_answering: NotAnsweringWatch | None = None


@dataclass(frozen=True)
class SessionRuntime:
    logger: object
    start_thread: Callable
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


@dataclass(frozen=True)
class Senders:
    auto_mode: object
    slot: Osr2Slot
    tcode_udp_port: int = 0


class BrokerSerialSession:
    # How many identical failures pass between summary lines; see
    # :meth:`_report_failure`.
    FAILURE_SUMMARY_EVERY = 60

    def __init__(
        self,
        *,
        link: SerialLink,
        controls: SessionControls,
        watches: DeviceWatches,
        runtime: SessionRuntime,
        senders: Senders,
    ):
        self.serial_factory = link.serial_factory
        self.virtual_port = link.virtual_port
        self.baud = link.baud
        self.is_retryable_error = link.is_retryable_error
        self.broker_cmd_file = controls.broker_cmd_file
        self.consume_command = controls.consume_command
        self.stop_event = controls.stop_event
        self.broker_paused = controls.broker_paused
        self.connected_event = controls.connected_event
        self.device_on = watches.device_on
        self.logger = logger = runtime.logger
        self.start_thread = runtime.start_thread
        self.monotonic = monotonic = runtime.monotonic
        self.sleep = runtime.sleep
        self.auto_mode = senders.auto_mode
        self.poll_interval_seconds = 0.05
        self._rx_activity = watches.rx_activity
        self._tx_activity = watches.tx_activity
        self._power_on = watches.power_on
        self._slot = senders.slot
        self._question = watches.question
        self._not_answering = watches.not_answering
        # Whether the last bytes forwarded from the virtual port stopped short
        # of a line's end: a question written then would land inside a command.
        self._mid_command = False
        self._motion = motion_log(logger=logger, monotonic=monotonic)
        self._udp_dropped = dropped_udp_log(logger=logger, monotonic=monotonic)
        self._holds = HoldScheduler(monotonic=monotonic, logger=logger)
        self._tcode_window = TCodeWriteWindow(monotonic=monotonic)
        # The open failure being reported, and how many times running it has
        # happened: see :meth:`_report_failure`.
        self._failure: tuple[str, str] | None = None
        self._failure_count = 0
        self._tcode_listener = UdpTCodeListener(
            port=senders.tcode_udp_port,
            stop_event=controls.stop_event,
            logger=logger,
            is_retryable_error=self.is_retryable_error,
            lets_through=lets_through_unless_held(lambda: self._slot.holder, self._udp_dropped),
        ) if senders.tcode_udp_port else None

    @staticmethod
    def _peer_connected(port) -> bool:
        try:
            return port.dsr
        except (OSError, AttributeError):
            return True

    def run(self, udp_sock, osr2_port: str) -> bool:
        session_stop = threading.Event()
        retry_state = SessionRetryState()
        thread_real = None
        thread_virtual = None
        thread_tcode = None
        serial_write_lock = threading.Lock()
        peer_disconnected = False

        try:
            with (
                self.serial_factory(self.virtual_port, self.baud, timeout=0.02) as virt,
                self.serial_factory(osr2_port, self.baud, timeout=0.02) as real,
            ):
                virt.write_timeout = 0.1
                self._report_recovery()
                self.connected_event.set()
                write = self.tcode_writer(real, serial_write_lock, session_stop, retry_state)
                self._slot.write_through(lambda sender, line: write(tcode_from(sender), line))
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
                            args=(write, session_stop, retry_state),
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
                        self.tick(
                            udp_sock, real_port=real, serial_write_lock=serial_write_lock,
                        )
                finally:
                    self._slot.write_through(None)
                    session_stop.set()
                    if thread_real is not None:
                        thread_real.join(timeout=1.0)
                    if thread_virtual is not None:
                        thread_virtual.join(timeout=1.0)
                    if thread_tcode is not None:
                        thread_tcode.join(timeout=1.0)
        except Exception as exc:
            self._report_failure(exc)
            retry_state.value = self.is_retryable_error(exc)
        finally:
            self.connected_event.clear()

        return peer_disconnected or retry_state.value

    def _report_failure(self, exc: BaseException) -> None:
        """Say a failed session once, then only count it.

        Every attempt against a port that is gone, or held by something else,
        raises the same error, and a traceback apiece wrote four megabytes in
        forty minutes -- rolling the log three times and taking every earlier
        session's record with it, so the one thing a reader came for was the
        one thing gone.  The first of a run is the full traceback, because that
        is what a reader needs; the rest are a line every
        ``FAILURE_SUMMARY_EVERY`` attempts saying how many there have been.
        A different failure starts a new run and gets its own traceback.
        """
        kind = (type(exc).__name__, str(exc))
        if kind != self._failure:
            self._failure = kind
            self._failure_count = 1
            self.logger.exception("Failed to open or run serial session")
            return
        self._failure_count += 1
        if self._failure_count % self.FAILURE_SUMMARY_EVERY == 0:
            self.logger.warning(
                "Still failing to open or run the serial session (%d attempts): %s",
                self._failure_count, exc,
            )

    def _report_recovery(self) -> None:
        """Close out a run of failures, now that a session has the ports."""
        if self._failure is None:
            return
        self.logger.info(
            "Serial session opened after %d failed attempt(s)", self._failure_count
        )
        self._failure = None
        self._failure_count = 0

    def _note_the_device_spoke(self) -> None:
        """Record the OSR2 having just spoken, and park it if that broke a silence.

        A switched-on OSR2 comes up half way along its travel, so the first
        thing it says is the cue to send it home.
        """
        self._rx_activity.mark()
        if self._not_answering is not None:
            self._not_answering.heard()
        if self._power_on.rx_broke_the_silence():
            self._holds.schedule_without_muting(PARK, "OSR2 powered on: park scheduled")

    def forward_real_to_virtual(self, real, virt, udp_sock, session_stop, retry_state: SessionRetryState) -> None:
        buf = bytearray()
        while not self.stop_event.is_set() and not session_stop.is_set():
            try:
                data = real.read(real.in_waiting or 1)
                if not data:
                    continue

                self._note_the_device_spoke()
                with contextlib.suppress(OSError):
                    virt.write(data)

                buf.extend(data)
                while b"\n" in buf:
                    raw_line, _, rest = buf.partition(b"\n")
                    buf[:] = rest
                    line = raw_line.rstrip(b"\r").decode("utf-8", errors="replace").strip()
                    if line:
                        self.auto_mode.handle_line(udp_sock, line)
                        if self._question is not None:
                            self._question.heard(line)
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
                        and self._slot.holder is None
                        and not self._holds.suppresses_mfp()):
                    with serial_write_lock:
                        real.write(data)
                        self._mid_command = not data.endswith(b"\n")
                    if queued:
                        self._tx_activity.mark()
                        self._motion.happened(MFP)
            except Exception as exc:
                self.logger.exception("VIRT->REAL error")
                retry_state.value = self.is_retryable_error(exc)
                session_stop.set()
                return

    def tcode_writer(self, real, serial_write_lock, session_stop,
                     retry_state: SessionRetryState) -> Callable[[str, str], None]:
        def write(source: str, line: str) -> None:
            if session_stop.is_set() or self.auto_mode.is_active or not line.isascii():
                return
            self._tcode_window.mark()
            try:
                with serial_write_lock:
                    real.write(f"{line}\n".encode("ascii"))
            except Exception as exc:
                self.logger.exception("%s could not be written to the OSR2", source)
                retry_state.value = self.is_retryable_error(exc)
                session_stop.set()
                return
            self._tx_activity.mark()
            self._motion.happened(source)
        return write

    def tick(self, udp_sock, *, real_port, serial_write_lock) -> None:
        for cmd in self.consume_command(self.broker_cmd_file):
            self.handle_broker_command(cmd, udp_sock)
        self.end_auto_mode_once_switched_off(udp_sock)
        self._motion.tick()
        self._udp_dropped.tick()
        if self._not_answering is not None:
            self._not_answering.tick(driving=driven_from_outside(self._motion))
        if self.auto_mode.consume_deactivation():
            self._holds.schedule_without_muting(PARK, "Auto mode deactivated: park scheduled")
        if self._holds.fire_due(real_port, serial_write_lock, self._tcode_window.mark):
            self._motion.happened(HOLD)
        self._ask_the_device(real_port, serial_write_lock)

    def _ask_the_device(self, real_port, serial_write_lock) -> None:
        if self._question is None:
            return
        if self.auto_mode.is_active:
            self._question.stand_down()
            return
        if not self._question.due():
            return
        with serial_write_lock:
            if self._mid_command:
                return
            real_port.write(DeviceQuestion.QUESTION)
        self._question.asked()

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
        self._slot.kick("The park")
        self._holds.schedule(PARK, "OmniPause: park scheduled")

    def _retract(self, _udp_sock) -> None:
        self._slot.kick("The retract")
        self._holds.schedule(RETRACT, "OmniPause: retract scheduled")

    # The whole vocabulary. Every app asks with app_support.osr2_hold's verbs;
    # the family's consumer upper-cases whatever it reads, so the keys are the
    # verbs as they arrive.
    _VERBS = MappingProxyType({
        "PAUSE": _pause,
        osr2_hold.RESUME: _resume,
        osr2_hold.PARK: _park,
        osr2_hold.RETRACT: _retract,
    })

    def end_auto_mode_once_switched_off(self, udp_sock) -> None:
        if not self.auto_mode.is_active:
            return
        if self.broker_paused.is_set():
            return
        if self.device_on():
            return
        self.logger.warning("AUTO ended: the OSR2 has been switched off")
        self.auto_mode.set_auto(udp_sock, False)
