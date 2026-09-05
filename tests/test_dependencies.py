"""Every third-party import in osr2_broker is a dependency pyproject declares.

A launcher that imports a package nobody declared works on the machine that
happened to have it and dies on the merge gate, which installs exactly what the
pyproject says.  The gate is the family's (``app_support.dependencies``); what
is here is which packages are this repo's own.
"""
from __future__ import annotations

from pathlib import Path

from app_support.dependencies import assert_every_import_is_declared

ROOT = Path(__file__).resolve().parent.parent


def test_every_third_party_import_is_declared():
    assert_every_import_is_declared(
        ROOT, [ROOT / "osr2_broker"], ROOT / "pyproject.toml", local=("osr2_broker",))
