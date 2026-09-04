"""This repo's lint gate. The config and the check it runs are `app_support.lint`."""
from __future__ import annotations

from pathlib import Path

from app_support.lint import assert_config_is_the_familys, assert_lint_is_clean

ROOT = Path(__file__).resolve().parent.parent


def test_the_ruff_config_is_the_familys():
    assert_config_is_the_familys(ROOT / "ruff.toml")


def test_ruff_finds_nothing():
    assert_lint_is_clean(ROOT, ROOT / "osr2_broker", ROOT / "tests")
