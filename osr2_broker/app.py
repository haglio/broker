from __future__ import annotations

import argparse
import logging
import socket
import threading
import time
from pathlib import Path

import serial

from .ports import resolve_virtual_port, ensure_mfp_serial_port
from .protocol import BrokerAutoController
from .session import BrokerSerialSession
from .config import load_config
from .logging_utils import configure_logging, install_exception_logging
from .runtime_support import consume_command_file as _consume_command_file
from .runtime_support import preparse_config_path
from .threading_utils import start_daemon_thread

SERIAL_RETRY_DELAY_SECONDS = 1.0


def _preparse_config(argv: list[str] | None) -> str | None:
    return preparse_config_path(argv)


def build_parser(config) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="OSR2 serial broker with idle monitor.")
    ap.add_argument("--config", help="Path to a JSON config file.")
    ap.add_argument("--virtual-port", default=config.virtual_port)
    ap.add_argument("--real-port", default=config.real_port)
    ap.add_argument("--baud", type=int, default=config.baud)
    ap.add_argument("--udp-host", default=config.udp_host)
    ap.add_argument("--udp-port", type=int, default=config.udp_port)
    ap.add_argument("--auto-stale-timeout", type=float, default=config.auto_stale_timeout)
    ap.add_argument("--tcode-udp-port", type=int, default=config.tcode_udp_port)
    ap.add_argument("--serial-retry-delay", type=float, default=SERIAL_RETRY_DELAY_SECONDS, help=argparse.SUPPRESS)
    ap.add_argument("--state-file", default=str(config.genau_mode_file))
    ap.add_argument("--genau-enabled-file", default=str(config.genau_enabled_file))
    ap.add_argument("--broker-cmd-file", default=str(config.broker_cmd_file))
    ap.add_argument("--heartbeat-file", default=str(config.broker_heartbeat_file))
    return ap


def write_mode(path: Path, value: str, logger: logging.Logger) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    except Exception:
        logger.exception("Failed to write mode file %s", path)


def consume_broker_cmd(path: Path) -> str | None:
    return _consume_command_file(path)


def read_genau_enabled(path: Path) -> bool:
    try:
        if not path.exists():
            return True
        return path.read_text(encoding="utf-8").replace("\ufeff", "").strip() != "0"
    except Exception:
        return True


def ensure_genau_enabled_file(path: Path, logger: logging.Logger) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or not path.read_text(encoding="utf-8").replace("\ufeff", "").strip():
            path.write_text("1", encoding="utf-8")
    except Exception:
        logger.exception("Failed to initialize Genau enabled file %s", path)


def write_heartbeat(path: Path, logger: logging.Logger) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()), encoding="utf-8")
    except Exception:
        logger.exception("Failed to write broker heartbeat %s", path)


def heartbeat_loop(
    path: Path, stop_event: threading.Event, logger: logging.Logger,
    sleep=time.sleep, connected: threading.Event | None = None,
) -> None:
    while not stop_event.is_set():
        if connected is None or connected.is_set():
            write_heartbeat(path, logger)
        sleep(0.5)


def udp_send(sock: socket.socket, host: str, port: int, msg: str) -> None:
    sock.sendto(msg.encode("utf-8"), (host, port))


def is_retryable_serial_error(exc: BaseException) -> bool:
    return isinstance(exc, (serial.SerialException, PermissionError, OSError))


def main(argv: list[str] | None = None) -> int:
    config = load_config(_preparse_config(argv))
    logger = configure_logging("osr2_broker", config.log_file("broker"))
    install_exception_logging(logger)

    from .single_instance import MUTEX_BROKER, mutex_name_for_config, try_acquire_mutex
    _mutex_handle = try_acquire_mutex(mutex_name_for_config(MUTEX_BROKER, config.config_path))
    if _mutex_handle is None:
        logger.warning("Another broker instance is already running; exiting")
        return 0

    args = build_parser(config).parse_args(argv)
    args.virtual_port = resolve_virtual_port(config.mfp_config_path, args.virtual_port, logger)

    # Configure MFP's serial port to match our virtual port
    ensure_mfp_serial_port(config.mfp_config_path, args.virtual_port, logger)

    state_file = Path(args.state_file)
    genau_enabled_file = Path(args.genau_enabled_file)
    broker_cmd_file = Path(args.broker_cmd_file)
    heartbeat_file = Path(args.heartbeat_file)
    ensure_genau_enabled_file(genau_enabled_file, logger)
    genau_enabled = read_genau_enabled(genau_enabled_file)
    stop_event = threading.Event()
    broker_paused = threading.Event()
    auto_mode = BrokerAutoController(
        state_file=state_file,
        udp_host=args.udp_host,
        udp_port=args.udp_port,
        logger=logger,
        write_mode=write_mode,
        udp_send=udp_send,
        enabled=genau_enabled,
    )
    session = BrokerSerialSession(
        serial_factory=serial.Serial,
        virtual_port=args.virtual_port,
        real_port=args.real_port,
        baud=args.baud,
        broker_cmd_file=broker_cmd_file,
        genau_enabled_file=genau_enabled_file,
        auto_stale_timeout=args.auto_stale_timeout,
        stop_event=stop_event,
        broker_paused=broker_paused,
        auto_mode=auto_mode,
        logger=logger,
        start_thread=start_daemon_thread,
        consume_command=consume_broker_cmd,
        read_genau_enabled=read_genau_enabled,
        monotonic=time.monotonic,
        sleep=time.sleep,
        is_retryable_error=is_retryable_serial_error,
        activity_rx_file=config.osr2_serial_rx_file,
        activity_tx_file=config.osr2_serial_tx_file,
        tcode_udp_port=args.tcode_udp_port,
    )

    write_mode(state_file, "0", logger)

    connected = threading.Event()
    session.connected_event = connected
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    heartbeat_thread = start_daemon_thread(
        target=heartbeat_loop,
        args=(heartbeat_file, stop_event, logger),
        kwargs={"connected": connected},
        name="broker-heartbeat",
    )

    # --- Monitor (idle alert + shutdown blocking) ---
    _start_monitor(config, auto_mode, logger)

    logger.info("Starting broker: %s <-> %s", args.virtual_port, args.real_port)
    logger.info("Genau UDP target: %s:%s", args.udp_host, args.udp_port)
    logger.info("T-Code UDP listener: 127.0.0.1:%s", args.tcode_udp_port)

    try:
        while not stop_event.is_set():
            should_retry = session.run(udp_sock)
            if not should_retry or stop_event.is_set():
                break
            logger.warning("Retrying serial session in %.2fs", args.serial_retry_delay)
            time.sleep(args.serial_retry_delay)
    except KeyboardInterrupt:
        logger.info("Broker interrupted")
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=1.0)
        udp_sock.close()

    return 0


# ---------------------------------------------------------------------------
# Monitor integration
# ---------------------------------------------------------------------------

RX_STALE_THRESHOLD = 30.0
MONITOR_POLL_INTERVAL_MS = 10_000


def _start_monitor(config, auto_mode, logger: logging.Logger) -> None:
    from .monitor import Action, MonitorState, read_timestamp
    from .win32 import ShutdownGuard, show_warning

    idle_threshold = config.idle_minutes * 60.0
    rx_file = config.osr2_serial_rx_file
    tx_file = config.osr2_serial_tx_file

    state = MonitorState(
        idle_threshold=idle_threshold,
        rx_stale_threshold=RX_STALE_THRESHOLD,
    )

    def poll():
        now = time.time()
        last_rx = read_timestamp(rx_file)
        last_tx = read_timestamp(tx_file)
        is_auto = auto_mode.is_active
        action = state.update(now, last_rx, last_tx, is_auto)

        if action == Action.IDLE_ALERT:
            logger.info("OSR2 idle for %.0f minutes — showing alert", idle_threshold / 60)

            def _show_and_acknowledge():
                show_warning(
                    "OSR2 Broker",
                    f"Your OSR2 has been idle for {int(config.idle_minutes)} minutes.\n"
                    "Did you forget to turn it off?",
                    button_text="I don't know, did you?",
                )
                state.acknowledge()

            import threading as _threading
            _threading.Thread(target=_show_and_acknowledge, daemon=True).start()

    def should_block_shutdown():
        now = time.time()
        last_rx = read_timestamp(rx_file)
        device_on = last_rx is not None and (now - last_rx) < RX_STALE_THRESHOLD
        if device_on:
            logger.info("Shutdown blocked — OSR2 is still on")
        return device_on

    guard = ShutdownGuard(
        should_block_fn=should_block_shutdown,
        poll_fn=poll,
        poll_interval_ms=MONITOR_POLL_INTERVAL_MS,
        block_reason="Your OSR2 is still powered on! Turn it off before shutting down.",
    )

    logger.info("Monitor started (idle threshold: %.0f min)", config.idle_minutes)
    start_daemon_thread(target=guard.run, name="monitor-guard")


if __name__ == "__main__":
    raise SystemExit(main())
