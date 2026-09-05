"""The two mutex names that say a broker, or a tray, is already running.

Claiming, holding and probing them is ``app_support.win32``'s.  The names are
the broker's, and they cannot change: a broker started before a change -- by
the scheduled task, say -- is not refused by one started after it, and two
brokers then drive one serial port.
"""
from __future__ import annotations

# The broker's, made per config by ``app_support.win32.mutex_name``, so one
# config blocks its own duplicates while a broker on another runs beside it.
MUTEX_BROKER = "Global\\OSR2Broker"
# The tray's, as it stands: one tray per machine.
MUTEX_TRAY = "Global\\OSR2Broker.Tray"
