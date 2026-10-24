"""The broker wears the family's look: shared_ui's colors, marks, lettering and spacing, none of its own."""
from __future__ import annotations

from pathlib import Path

from shared_ui.look_guard import assert_the_look_is_shared_uis

_CHECKOUT = Path(__file__).resolve().parents[1]


def test_everything_broker_draws_with_comes_from_shared_ui():
    assert_the_look_is_shared_uis(_CHECKOUT, [_CHECKOUT / "osr2_broker", _CHECKOUT / "tools"])
