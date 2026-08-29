"""Tests for osr2_broker.app."""
from __future__ import annotations

import importlib
import logging
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

class FakeSocket:
    def sendto(self, _data, _addr):
        return None

    def close(self):
        return None


def make_fake_serial(open_ports: list[str], fail_once_on: tuple[str, type[Exception]] | None = None):
    """A serial.Serial stand-in that records every port it is asked to open."""

    class FakeSerial:
        def __init__(self, port, _baud, timeout=0.02):
            open_ports.append(port)
            if fail_once_on is not None:
                failing_port, error = fail_once_on
                if port == failing_port and open_ports.count(port) == 1:
                    raise error("Access is denied")
            self.port = port
            self.timeout = timeout
            self.in_waiting = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _size):
            return b""

        def write(self, _data):
            return None

    return FakeSerial


@pytest.fixture()
def broker_app_module():
    fake_serial = types.SimpleNamespace(
        Serial=None,
        SerialException=type("FakeSerialException", (Exception,), {}),
    )
    with patch.dict(sys.modules, {"serial": fake_serial}):
        module = importlib.import_module("osr2_broker.app")
        module = importlib.reload(module)
    return module


def _start_monitor_with_fake_guard(broker_app_module, config, *, auto_active=False):
    """Run _start_monitor against a guard that hands back its two closures.

    The real ShutdownGuard would pump Win32 messages; what the tests need is
    what the guard is given — should_block_fn and poll_fn — driven directly.
    """
    captured: dict = {}

    class FakeShutdownGuard:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            return None

    with patch("osr2_broker.win32.ShutdownGuard", FakeShutdownGuard), \
         patch.object(broker_app_module, "start_daemon_thread"):
        broker_app_module._start_monitor(
            config, types.SimpleNamespace(is_active=auto_active),
            logging.getLogger("test.broker"),
        )
    return captured


def test_shutdown_is_blocked_while_the_device_is_on(broker_app_module, cfg_path):
    """A fresh rx stamp means the OSR2 is still powered — Windows must wait."""
    import time as _time
    from osr2_broker.config import load_config

    config = load_config(str(cfg_path))
    config.osr2_serial_rx_file.write_text(str(_time.time()), encoding="utf-8")

    captured = _start_monitor_with_fake_guard(broker_app_module, config)

    assert captured["should_block_fn"]() is True


def test_shutdown_is_allowed_once_the_rx_stamp_goes_stale(broker_app_module, cfg_path):
    """Past RX_STALE_THRESHOLD the device counts as off — shutdown proceeds.
    With the fresh case above, this pins the comparison from both sides, so
    its sign cannot flip unseen (audit finding broker/all/tests/005)."""
    import time as _time
    from osr2_broker.config import load_config

    config = load_config(str(cfg_path))
    stale = _time.time() - (broker_app_module.RX_STALE_THRESHOLD + 10.0)
    config.osr2_serial_rx_file.write_text(str(stale), encoding="utf-8")

    captured = _start_monitor_with_fake_guard(broker_app_module, config)

    assert captured["should_block_fn"]() is False


def test_shutdown_is_allowed_when_the_device_has_never_reported(broker_app_module, cfg_path):
    from osr2_broker.config import load_config

    config = load_config(str(cfg_path))

    captured = _start_monitor_with_fake_guard(broker_app_module, config)

    assert captured["should_block_fn"]() is False


def test_a_restarted_broker_resumes_the_idle_countdown_from_disk(broker_app_module, cfg_path):
    """The idle state seeded from osr2_idle_state.txt must feed the poll: a
    countdown that had already elapsed before the restart alerts on the first
    beat instead of starting the 15 minutes over."""
    import json
    import threading
    import time as _time

    import osr2_broker.monitor as monitor_mod
    from osr2_broker.config import load_config

    config = load_config(str(cfg_path))
    now = _time.time()
    idle_threshold = config.idle_minutes * 60.0
    monitor_mod.save_idle_state(
        config.osr2_idle_state_file, idle_since=now - idle_threshold - 1.0, alerted=False,
    )
    config.osr2_serial_rx_file.write_text(str(now), encoding="utf-8")  # device on

    warned = threading.Event()
    with patch("osr2_broker.win32.show_warning", side_effect=lambda *a, **kw: warned.set()):
        captured = _start_monitor_with_fake_guard(broker_app_module, config)
        captured["poll_fn"]()

    assert warned.wait(timeout=5.0), "the idle alert never reached show_warning"
    persisted = json.loads(config.osr2_idle_state_file.read_text(encoding="utf-8"))
    assert persisted["alerted"] is True


def test_no_idle_alert_before_the_threshold_has_elapsed(broker_app_module, cfg_path):
    import json
    import time as _time

    import osr2_broker.monitor as monitor_mod
    from osr2_broker.config import load_config

    config = load_config(str(cfg_path))
    now = _time.time()
    monitor_mod.save_idle_state(
        config.osr2_idle_state_file, idle_since=now - 300.0, alerted=False,
    )
    config.osr2_serial_rx_file.write_text(str(now), encoding="utf-8")

    warned = []
    with patch("osr2_broker.win32.show_warning", side_effect=lambda *a, **kw: warned.append(True)):
        captured = _start_monitor_with_fake_guard(broker_app_module, config)
        captured["poll_fn"]()

    assert warned == []
    persisted = json.loads(config.osr2_idle_state_file.read_text(encoding="utf-8"))
    assert persisted["alerted"] is False


class TestMainReconnect:
    def test_retries_after_retryable_serial_open_failure(self, broker_app_module, cfg_path):
        open_ports: list[str] = []
        FakeSerial = make_fake_serial(
            open_ports, fail_once_on=("COM4", broker_app_module.serial.SerialException),
        )

        sleep_calls = {"count": 0}

        def fake_sleep(_seconds):
            sleep_calls["count"] += 1
            if sleep_calls["count"] >= 4:
                raise KeyboardInterrupt

        with patch.object(broker_app_module, "configure_logging", return_value=logging.getLogger("test.broker")), \
             patch.object(broker_app_module, "install_exception_logging"), \
             patch("osr2_broker.single_instance.try_acquire_mutex", return_value=42), \
             patch.object(broker_app_module, "resolve_virtual_port", side_effect=lambda _c, port, _l: port), \
             patch.object(broker_app_module, "ensure_mfp_serial_port"), \
             patch.object(broker_app_module.serial, "Serial", side_effect=FakeSerial), \
             patch.object(broker_app_module, "socket") as mock_socket_mod, \
             patch.object(broker_app_module, "_start_monitor"), \
             patch.object(broker_app_module.time, "sleep", side_effect=fake_sleep):
            mock_socket_mod.socket.return_value = FakeSocket()
            mock_socket_mod.AF_INET = 2
            mock_socket_mod.SOCK_DGRAM = 2
            result = broker_app_module.main(["--config", str(cfg_path), "--serial-retry-delay", "0"])

        assert result == 0
        assert open_ports.count("COM4") >= 2
        assert open_ports.count("COM15") >= 2


class TestMainSurvivesMfpConfigTrouble:
    def test_starts_brokering_when_mfp_config_cannot_be_written(self, broker_app_module, cfg_path):
        """MFP's config sits under Program Files and MFP may hold it open. Being
        refused there must not stop the broker from bridging MFP to the OSR2."""
        open_ports: list[str] = []
        FakeSerial = make_fake_serial(open_ports)

        def fake_sleep(_seconds):
            raise KeyboardInterrupt

        with patch.object(broker_app_module, "configure_logging", return_value=logging.getLogger("test.broker")), \
             patch.object(broker_app_module, "install_exception_logging"), \
             patch("osr2_broker.single_instance.try_acquire_mutex", return_value=42), \
             patch.object(broker_app_module, "resolve_virtual_port", side_effect=lambda _c, port, _l: port), \
             patch.object(
                 broker_app_module, "ensure_mfp_serial_port",
                 side_effect=PermissionError(13, "Access is denied"),
             ), \
             patch.object(broker_app_module.serial, "Serial", side_effect=FakeSerial), \
             patch.object(broker_app_module, "socket") as mock_socket_mod, \
             patch.object(broker_app_module, "_start_monitor"), \
             patch.object(broker_app_module.time, "sleep", side_effect=fake_sleep):
            mock_socket_mod.socket.return_value = FakeSocket()
            mock_socket_mod.AF_INET = 2
            mock_socket_mod.SOCK_DGRAM = 2
            result = broker_app_module.main(["--config", str(cfg_path)])

        assert result == 0
        assert "COM4" in open_ports


class TestBrokerSingleInstance:
    def test_exits_when_already_running(self, broker_app_module, cfg_path):
        logger = logging.getLogger("test.broker")
        mock_socket_mod = MagicMock()
        with patch.object(broker_app_module, "configure_logging", return_value=logger), \
             patch.object(broker_app_module, "install_exception_logging"), \
             patch("osr2_broker.single_instance.try_acquire_mutex", return_value=None), \
             patch.object(broker_app_module, "socket", mock_socket_mod):
            result = broker_app_module.main(["--config", str(cfg_path)])

        assert result == 0
        mock_socket_mod.socket.assert_not_called()


def test_write_heartbeat_persists_current_timestamp(tmp_path: Path, broker_app_module):
    heartbeat_file = tmp_path / "state" / "broker_heartbeat.txt"
    logger = logging.getLogger("test.broker")

    with patch("osr2_broker.app.time.time", return_value=123.45):
        broker_app_module.write_heartbeat(heartbeat_file, logger)

    assert heartbeat_file.read_text(encoding="utf-8") == "123.45"


def test_heartbeat_loop_skips_write_when_connected_event_is_clear(tmp_path: Path, broker_app_module):
    import threading
    heartbeat_file = tmp_path / "broker_heartbeat.txt"
    stop = threading.Event()
    connected = threading.Event()
    ticks = []

    def fake_sleep(s):
        ticks.append(s)
        if len(ticks) >= 3:
            stop.set()

    logger = logging.getLogger("test.broker")
    broker_app_module.heartbeat_loop(heartbeat_file, stop, logger, sleep=fake_sleep, connected=connected)
    assert not heartbeat_file.exists(), "heartbeat must not be written while disconnected"


def test_heartbeat_loop_writes_when_connected_event_is_set(tmp_path: Path, broker_app_module):
    import threading
    heartbeat_file = tmp_path / "broker_heartbeat.txt"
    stop = threading.Event()
    connected = threading.Event()
    connected.set()
    ticks = []

    def fake_sleep(s):
        ticks.append(s)
        if len(ticks) >= 1:
            stop.set()

    logger = logging.getLogger("test.broker")
    broker_app_module.heartbeat_loop(heartbeat_file, stop, logger, sleep=fake_sleep, connected=connected)
    assert heartbeat_file.exists(), "heartbeat must be written while connected"
