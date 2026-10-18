from __future__ import annotations

import logging
import threading
import time

from .ports import iter_serial_ports

# The OSR2's USB serial adapter, a CH340, which carries no serial number:
# Windows names it after the socket it is plugged into.
OSR2_ADAPTER = (0x1A86, 0x7523)
PLUGGED_IN_POLL_SECONDS = 1.0


def osr2_adapters() -> list[str]:
    return [port.device for port in iter_serial_ports() if (port.vid, port.pid) == OSR2_ADAPTER]


def wait_for_the_osr2(
    stop_event: threading.Event,
    logger: logging.Logger,
    *,
    last_port: str | None = None,
    poll_seconds: float = PLUGGED_IN_POLL_SECONDS,
) -> str | None:
    said = None
    while not stop_event.is_set():
        adapters = osr2_adapters()
        if (osr2_port := _the_osr2_among(adapters, last_port)) is not None:
            if osr2_port != last_port:
                logger.info("The OSR2 is plugged in on %s", osr2_port)
            return osr2_port
        if adapters != said:
            said = adapters
            _say_why_there_is_no_osr2(adapters, logger)
        time.sleep(poll_seconds)
    return None


def _the_osr2_among(adapters: list[str], last_port: str | None) -> str | None:
    if last_port in adapters:
        return last_port
    return adapters[0] if len(adapters) == 1 else None


def _say_why_there_is_no_osr2(adapters: list[str], logger: logging.Logger) -> None:
    if adapters:
        logger.warning("%d USB serial adapters of the OSR2's kind are plugged in (%s), and "
                       "nothing says which is the OSR2. Waiting until only one is",
                       len(adapters), ", ".join(adapters))
    else:
        logger.warning("The OSR2 is not plugged in: no USB serial adapter of its kind "
                       "is enumerated. Waiting for it")
