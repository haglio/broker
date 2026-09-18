"""This repo's coverage floor. The settings and the gate are `app_support.coverage_gate`."""
from __future__ import annotations

from pathlib import Path

from app_support.coverage_gate import assert_config_is_the_familys

ROOT = Path(__file__).resolve().parent.parent

# What this repo says it does not unit-test, with the reason it gives. One place,
# never a pragma scattered through the tree.
NOT_UNIT_TESTED = ()


def test_the_coverage_config_is_the_familys():
    assert_config_is_the_familys(ROOT / ".coveragerc", NOT_UNIT_TESTED)
