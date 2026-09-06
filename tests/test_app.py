"""Tests for osr2_broker.app."""
from __future__ import annotations

import importlib
import logging
import sys
import types
from contextlib import ExitStack, contextmanager
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


@pytest.fixture
def broker_app_module():
    """app.py, imported against a stand-in for pyserial.

    Only the one name is swapped, and only for the duration of the import. The
    obvious `patch.dict(sys.modules, ...)` is wrong here: it restores the whole
    mapping on exit, which evicts every module the import reached for the first
    time -- see
    `test_the_module_fixture_puts_back_only_the_name_it_borrowed`.
    """
    fake_serial = types.SimpleNamespace(
        Serial=None,
        SerialException=type("FakeSerialException", (Exception,), {}),
    )
    borrowed_from = sys.modules.get("serial")
    sys.modules["serial"] = fake_serial
    try:
        return importlib.reload(importlib.import_module("osr2_broker.app"))
    finally:
        if borrowed_from is None:
            del sys.modules["serial"]
        else:
            sys.modules["serial"] = borrowed_from


def test_the_module_fixture_puts_back_only_the_name_it_borrowed(broker_app_module):
    """Importing app.py without pyserial means lending `sys.modules` a fake, and
    the loan has to be that narrow.

    Undoing it by restoring the whole of `sys.modules` also evicts every module
    the import pulled in for the *first* time. An evicted submodule leaves its
    parent package still holding the old object, so `from app_support import
    logging_utils` keeps returning it while `from app_support.logging_utils
    import x` -- which goes through `sys.modules` -- imports a second copy. A
    test that patches one of the two then watches the code under test call the
    other, and the patch does nothing at all.

    That is not hypothetical: it is how `test_a_second_tray_stands_down` came to
    run the tray's `main()` with its logging patches inert, leaving an
    excepthook and an open log file for the rest of the session. It went
    unnoticed because a later test in this file happened to pull the evicted
    module back in before the tray tests ran.
    """
    for name in ("app_support.cli", "app_support.logging_utils", "app_support.threading_utils"):
        assert name in sys.modules, f"the fixture evicted {name} from sys.modules"
        package, _, attribute = name.rpartition(".")
        assert getattr(sys.modules[package], attribute) is sys.modules[name], (
            f"{package} and sys.modules disagree about which {attribute} is the real one"
        )


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


@contextmanager
def _main_running(broker_app_module, *, fake_serial, sleep, mfp_config_error=None,
                  retry_delay_seconds=None):
    """main(), with everything it installs process-wide held off.

    `configure_logging` and `install_exception_logging` replace both excepthooks
    and open a rotating file handler inside a state directory the test is about
    to delete, so they are patched here rather than cleaned up afterwards; the
    mutex is granted; the monitor's Win32 message pump is skipped; and `socket`
    is a stand-in so no datagram leaves the machine. `sleep` is how a test ends
    the run loop -- raising KeyboardInterrupt out of it is main()'s ordinary
    shutdown path.
    """
    patches = [
        patch.object(broker_app_module, "configure_logging",
                     return_value=logging.getLogger("test.broker")),
        patch.object(broker_app_module, "install_exception_logging"),
        patch("app_support.win32.try_acquire_mutex", return_value=42),
        patch.object(broker_app_module, "resolve_virtual_port",
                     side_effect=lambda _config, port, _logger: port),
        patch.object(broker_app_module, "ensure_mfp_serial_port",
                     side_effect=mfp_config_error),
        patch.object(broker_app_module.serial, "Serial", side_effect=fake_serial),
        patch.object(broker_app_module, "_start_monitor"),
        patch.object(broker_app_module.time, "sleep", side_effect=sleep),
    ]
    if retry_delay_seconds is not None:
        patches.append(
            patch.object(broker_app_module, "SERIAL_RETRY_DELAY_SECONDS", retry_delay_seconds),
        )
    with ExitStack() as stack:
        for each in patches:
            stack.enter_context(each)
        mock_socket_mod = stack.enter_context(patch.object(broker_app_module, "socket"))
        mock_socket_mod.socket.return_value = FakeSocket()
        mock_socket_mod.AF_INET = 2
        mock_socket_mod.SOCK_DGRAM = 2
        yield


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

        with _main_running(broker_app_module, fake_serial=FakeSerial, sleep=fake_sleep,
                           retry_delay_seconds=0.0):
            result = broker_app_module.main(["--config", str(cfg_path)])

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

        with _main_running(broker_app_module, fake_serial=FakeSerial, sleep=fake_sleep,
                           mfp_config_error=PermissionError(13, "Access is denied")):
            result = broker_app_module.main(["--config", str(cfg_path)])

        assert result == 0
        assert "COM4" in open_ports


class TestMainConfiguredWithoutMfp:
    def test_a_broker_without_an_mfp_config_leaves_mfp_alone(self, broker_app_module, cfg_factory):
        """No MFP config named means nothing to read or point anywhere; the
        start says so once rather than warning about the file it has not got
        (bug 26)."""
        cfg_path = cfg_factory({"mfp_config_path": ""})
        FakeSerial = make_fake_serial([])

        def stop_on_first_sleep(_seconds):
            raise KeyboardInterrupt

        with _main_running(broker_app_module, fake_serial=FakeSerial, sleep=stop_on_first_sleep):
            broker_app_module.main(["--config", str(cfg_path)])
            broker_app_module.ensure_mfp_serial_port.assert_not_called()


class TestBrokerSingleInstance:
    def test_exits_when_already_running(self, broker_app_module, cfg_path):
        logger = logging.getLogger("test.broker")
        mock_socket_mod = MagicMock()
        with patch.object(broker_app_module, "configure_logging", return_value=logger), \
             patch.object(broker_app_module, "install_exception_logging"), \
             patch("app_support.win32.try_acquire_mutex", return_value=None), \
             patch.object(broker_app_module, "socket", mock_socket_mod):
            result = broker_app_module.main(["--config", str(cfg_path)])

        assert result == 0
        mock_socket_mod.socket.assert_not_called()


class TestMainPublishesItsStateFiles:
    def test_a_started_broker_leaves_the_mode_and_enable_files_where_the_family_looks(
        self, broker_app_module, cfg_path,
    ):
        """The two files main() writes before it starts bridging, under the two
        names the rest of the family opens by hand.

        Nothing else in the suite reads a state file after main(): the writers
        are all substituted in the tests below this one. So the wiring -- which
        config property feeds which of the two names -- could shift without a red
        anywhere.
        """
        from osr2_broker.config import load_config

        config = load_config(str(cfg_path))
        FakeSerial = make_fake_serial([])

        def stop_on_first_sleep(_seconds):
            raise KeyboardInterrupt

        with _main_running(broker_app_module, fake_serial=FakeSerial,
                           sleep=stop_on_first_sleep):
            broker_app_module.main(["--config", str(cfg_path)])

        assert (config.state_dir / "genau_mode.txt").read_text(encoding="utf-8") == "0"
        assert (config.state_dir / "genau_enabled.txt").read_text(encoding="utf-8") == "1"
