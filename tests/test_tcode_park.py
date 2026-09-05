"""The park command the broker writes is the one player_core publishes.

The T-Code format is player_core's: every driver in the family spells a move
through `player_core.tcode`, and the rest command a stopped driver leaves the
device with is `player_core.tcode.PARK_COMMAND`. The broker parks with the same
string on its own, when a room is paused, and it does not install player_core
-- a device daemon has no use for a video engine -- so the two spellings are
held together here by reading the sibling checkout, the way this family's
consumer gates do. Where no player_core checkout sits beside this one, which is
what CI clones, there is nothing to compare against and this skips.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from app_support.siblings import sibling_checkout

from osr2_broker.hold import PARK


def _published_park_command() -> str:
    try:
        checkout = sibling_checkout("player_core", near=Path(__file__))
    except RuntimeError:
        pytest.skip("no player_core checkout beside this one to read the format from")
    tree = ast.parse((checkout / "player_core" / "tcode.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PARK_COMMAND" for target in node.targets
        ):
            return node.value.value
    raise AssertionError("player_core.tcode publishes no PARK_COMMAND")


def test_the_broker_parks_with_the_familys_park_command():
    assert PARK.tcode == (_published_park_command() + "\n").encode("ascii")
