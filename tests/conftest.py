"""Shared pytest fixtures for OSR2 Broker tests."""
from __future__ import annotations

import json
import logging
import os
import random
import shutil
import sys
import threading
import uuid
from pathlib import Path

import pytest

from unittest.mock import patch


def pytest_collection_modifyitems(items):
    """Collect in a different order when asked, so a test that leans on the ones
    beside it fails on the commit that introduces the lean.

    ``TEST_COLLECTION_ORDER=reverse`` collects back to front;
    ``TEST_COLLECTION_ORDER=shuffle`` shuffles with ``TEST_COLLECTION_SEED`` (0
    unless given), so a red run can be repeated exactly.  Unset leaves the order
    alone; anything else is a typo, and a typo that silently ran forward would
    make the gate's second leg a green that proves nothing.
    """
    order = os.environ.get("TEST_COLLECTION_ORDER")
    if order is None:
        return
    if order == "reverse":
        items.reverse()
    elif order == "shuffle":
        random.Random(int(os.environ.get("TEST_COLLECTION_SEED", "0"))).shuffle(items)
    else:
        raise pytest.UsageError(
            f"TEST_COLLECTION_ORDER={order!r}: expected 'reverse' or 'shuffle'"
        )


@pytest.fixture(autouse=True)
def _no_test_may_keep_a_piece_of_the_process(request):
    """Fail the test that walks off with the process, and hand the next one a
    clean one either way.

    Both ``main()``s here call ``install_exception_logging`` and
    ``configure_logging``, so a test that reaches one leaves both excepthooks
    replaced by a hook writing into a state directory it is about to delete, and
    an open file handler on the logger it wrote through. From then on an
    exception on any thread goes there instead of to pytest's reporting, and on
    Windows the open handle also leaves case_* trees behind under
    .tmp-pytest-local because rmtree cannot take them.

    Restoring quietly would only move the problem: the next such test would
    change what the rest of the run sees and nothing would say which one. So the
    process is put back *and* the test that took it is named.
    """
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
            continue  # a placeholder for a child logger; it holds nothing
        for handler in list(logger.handlers):
            if isinstance(handler, logging.FileHandler):
                kept.append(f"an open log file on {name!r}")
            logger.removeHandler(handler)
            handler.close()

    assert not kept, (
        f"{request.node.name} left {', '.join(kept)} behind — patch what "
        "installs it, the way tests/test_app.py does for the broker's main()"
    )


@pytest.fixture(autouse=True)
def stand_down_marker():
    """Keep the real marker out of every run, and give tests a place to look.

    It lives under LOCALAPPDATA, outside this checkout, and it is the file that
    tells Evolver whether the broker on this machine was quit on purpose. This
    suite runs on that machine, so a run that wrote one would leave the user's
    broker down and a run that cleared one would put it back up. Gagged at
    app_support's two calls rather than at ``osr2_broker.peer_watch``'s own, so
    the broker's half stays real and a test can watch it being used.
    """
    with patch("app_support.peer_watch.stand_down") as wrote,          patch("app_support.peer_watch.clear_stand_down") as cleared:
        yield wrote, cleared


TMP_ROOT = Path(
    os.environ.get(
        "OSR2_BROKER_PYTEST_TMP_ROOT",
        str(Path(__file__).resolve().parent.parent / ".tmp-pytest-local"),
    )
).resolve()


@pytest.fixture()
def tmp_path() -> Path:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = (TMP_ROOT / f"case_{uuid.uuid4().hex}").resolve()
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


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
        "real_port": "COM4",
        "baud": 115200,
        "udp_host": "127.0.0.1",
        "udp_port": 50555,
        "auto_stale_timeout": 8.0,
        "idle_minutes": 15.0,
        "mfp_config_path": str(mfp_dir / "MultiFunPlayer.config.json"),
        "tcode_udp_port": 50557,
    }

    if overrides:
        cfg.update(overrides)

    config_path = tmp_path / "osr2_broker_config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")
    return config_path


@pytest.fixture()
def cfg_path(tmp_path: Path) -> Path:
    return _write_config(tmp_path)


@pytest.fixture()
def cfg_factory(tmp_path: Path):
    def factory(overrides: dict | None = None) -> Path:
        return _write_config(tmp_path, overrides)
    return factory
