"""The broker wears the family's look: shared_ui's colors and marks, none of its own."""
from __future__ import annotations

from pathlib import Path

from shared_ui.look_guard import assert_the_look_is_shared_uis

_CHECKOUT = Path(__file__).resolve().parents[1]


def test_every_color_and_mark_broker_draws_comes_from_shared_ui():
    assert_the_look_is_shared_uis(_CHECKOUT, [_CHECKOUT / "osr2_broker", _CHECKOUT / "tools"])
