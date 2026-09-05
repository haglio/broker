"""Tests for osr2_broker.config — the defaults and path resolution were unpinned.

Every other test writes a config through conftest's _write_config, which
supplies every optional key explicitly, so until here the defaults were never
read (audit finding broker/all/tests/015: changing idle_minutes 15.0 -> 10.0
and tcode_udp_port 50557 -> 1 left the full suite green).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from osr2_broker.config import load_config

REQUIRED_KEYS: dict = {
    "state_dir": "state",
    "virtual_port": "COM15",
    "real_port": "COM4",
    "baud": 115200,
    "udp_host": "127.0.0.1",
    "udp_port": 50555,
    "auto_stale_timeout": 8.0,
}


def _write_minimal_config(tmp_path: Path, extra: dict | None = None) -> Path:
    cfg = dict(REQUIRED_KEYS)
    if extra:
        cfg.update(extra)
    config_path = tmp_path / "osr2_broker_config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")
    return config_path


def test_idle_minutes_defaults_to_fifteen(tmp_path: Path):
    config = load_config(_write_minimal_config(tmp_path))
    assert config.idle_minutes == 15.0


def test_tcode_udp_port_defaults_to_50557(tmp_path: Path):
    config = load_config(_write_minimal_config(tmp_path))
    assert config.tcode_udp_port == 50557


def test_mfp_config_path_is_none_when_the_config_names_none(tmp_path: Path):
    """An omitted (or empty) key used to resolve to the config's own directory,
    a path that names no file: every start then read a directory as MFP's
    config and warned twice about a failure that was not one (bug 26)."""
    assert load_config(_write_minimal_config(tmp_path)).mfp_config_path is None
    assert load_config(_write_minimal_config(tmp_path, {"mfp_config_path": ""})).mfp_config_path is None


def test_a_relative_state_dir_resolves_against_the_config_s_directory(tmp_path: Path):
    config = load_config(_write_minimal_config(tmp_path, {"state_dir": "state"}))
    assert config.state_dir == (tmp_path / "state").resolve()


def test_a_relative_mfp_config_path_resolves_against_the_config_s_directory(tmp_path: Path):
    config = load_config(
        _write_minimal_config(tmp_path, {"mfp_config_path": "mfp/MultiFunPlayer.config.json"})
    )
    assert config.mfp_config_path == (tmp_path / "mfp" / "MultiFunPlayer.config.json").resolve()


def test_an_absolute_state_dir_passes_through_untouched(tmp_path: Path):
    absolute = (tmp_path / "elsewhere").resolve()
    config = load_config(_write_minimal_config(tmp_path, {"state_dir": str(absolute)}))
    assert config.state_dir == absolute


def test_a_missing_config_file_raises_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "no_such_config.json")


def test_ports_and_numbers_are_coerced_to_their_types(tmp_path: Path):
    config = load_config(
        _write_minimal_config(tmp_path, {"baud": "115200", "udp_port": "50555"})
    )
    assert config.baud == 115200
    assert config.udp_port == 50555


def test_config_exposes_idle_state_file(cfg_path):
    config = load_config(str(cfg_path))
    assert config.osr2_idle_state_file == config.state_dir / "osr2_idle_state.txt"
