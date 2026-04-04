"""Shared pytest fixtures for OSR2 Broker tests."""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

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
