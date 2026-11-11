from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path

import pytest
from app_support.osr2_slot import Osr2Slot
from app_support.testing import stand_down_cleared, stand_down_written
from PySide6.QtWidgets import QApplication

from osr2_broker import tray as tray_module
from tests.scratch import scratch_dir


@pytest.fixture(scope="session")
def qapp():
    """Held for the run: Qt faults at the next QSystemTrayIcon once a QApplication is collected."""
    return QApplication.instance() or QApplication([])


class _Recorder(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def recorded_logger():
    logger = logging.getLogger("test.osr2_broker.recorded")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = _Recorder()
    logger.addHandler(handler)
    yield logger, handler
    logger.handlers.clear()


class FakePowerOnSayingNoUnlessToldSoNoStrayTestParksTheDevice:
    def __init__(self, *, breaks_silence: bool = False):
        self.breaks_silence = breaks_silence

    def rx_broke_the_silence(self) -> bool:
        return self.breaks_silence


def idle_slot() -> Osr2Slot:
    return Osr2Slot(port=0, logger=logging.getLogger("test.osr2_broker.idle_slot"),
                    start_thread=None)


@pytest.fixture(autouse=True)
def _no_test_may_keep_a_piece_of_the_process(request):
    hooks = (sys.excepthook, threading.excepthook)
    loggers_before = set(logging.Logger.manager.loggerDict)

    yield

    kept = []
    if (sys.excepthook, threading.excepthook) != hooks:
        kept.append("an exception hook")
    sys.excepthook, threading.excepthook = hooks
    for name in set(logging.Logger.manager.loggerDict) - loggers_before:
        logger = logging.Logger.manager.loggerDict.get(name)
        if not isinstance(logger, logging.Logger):
            continue
        for handler in list(logger.handlers):
            if isinstance(handler, logging.FileHandler):
                kept.append(f"an open log file on {name!r}")
            logger.removeHandler(handler)
            handler.close()

    assert not kept, (
        f"{request.node.name} left {', '.join(kept)}: every later exception would go there "
        "instead of to pytest, and Windows cannot delete a scratch tree a handler holds open; "
        "patch what installs it, the way tests/test_app.py does for the broker's main()"
    )


@pytest.fixture(autouse=True)
def stand_down_marker_kept_off_the_real_one_that_governs_the_production_broker():
    with (
        stand_down_written() as wrote,
        stand_down_cleared() as cleared,
    ):
        yield wrote, cleared


TMP_ROOT = Path(
    os.environ.get(
        "OSR2_BROKER_PYTEST_TMP_ROOT",
        str(Path(__file__).resolve().parent.parent / ".tmp-pytest-local"),
    )
).resolve()


@pytest.fixture
def tmp_path() -> Path:
    with scratch_dir(TMP_ROOT) as path:
        yield path


@pytest.fixture(autouse=True, scope="session")
def _cleanup_tmp_root():
    yield
    try:
        if TMP_ROOT.is_dir() and not any(TMP_ROOT.iterdir()):
            TMP_ROOT.rmdir()
    except OSError:
        pass


def _write_config(tmp_path: Path, overrides: dict | None = None) -> Path:
    (tmp_path / "state").mkdir(exist_ok=True)
    mfp_dir = tmp_path / "mfp"
    mfp_dir.mkdir(exist_ok=True)

    cfg: dict = {
        "state_dir": str(tmp_path / "state"),
        "virtual_port": "COM15",
        "baud": 115200,
        "udp_host": "127.0.0.1",
        "udp_port": 50555,
        "idle_minutes": 15.0,
        "mfp_config_path": str(mfp_dir / "MultiFunPlayer.config.json"),
        "tcode_udp_port": 50557,
    }

    if overrides:
        cfg.update(overrides)

    config_path = tmp_path / "osr2_broker_config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")
    return config_path


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    return _write_config(tmp_path)


@pytest.fixture
def cfg_factory(tmp_path: Path):
    def factory(overrides: dict | None = None) -> Path:
        return _write_config(tmp_path, overrides)
    return factory


@pytest.fixture
def the_trays_main_kept_from_the_excepthooks_the_log_file_and_a_copy_of_pythonw_into_the_live_venv(
        monkeypatch):
    monkeypatch.setattr(tray_module, "configure_logging",
                        lambda _name, _path: logging.getLogger("test.tray"))
    monkeypatch.setattr(tray_module, "install_exception_logging", lambda _logger: None)
    monkeypatch.setattr(tray_module, "_name_this_process", lambda: None)
