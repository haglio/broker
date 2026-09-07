"""Every module defers its annotations, so 3.12 and 3.14 read this repo the same way.

The gate is the family's (``app_support.annotations``); what is here is which
trees to read.
"""
from __future__ import annotations

from pathlib import Path

from app_support.annotations import assert_every_module_defers_annotations

ROOT = Path(__file__).resolve().parent.parent
TREES = [ROOT / "osr2_broker", ROOT / "tests", ROOT / "tools", ROOT / "scripts",
         ROOT / "vulture_whitelist.py"]


def test_every_module_defers_its_annotations():
    assert_every_module_defers_annotations(ROOT, TREES)
