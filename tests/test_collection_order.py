"""The gate runs this suite in more than one order, and this pins the switch.

A test that leans on the one beside it is green until something renames a file,
and then it is red in a commit that had nothing to do with it -- so the gate
collects the suite a second time back to front, and `conftest.py` decides what
"back to front" means.

The reorderings themselves are checked here in process, against a list of
stand-in ids; one subprocess then proves pytest actually calls the hook, which is
the half that cannot be assumed -- a hook nothing calls is precisely how a suite
ends up with a fixture file nothing loads.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import conftest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# This file, whose tests are plain module-level functions collected in source
# order. Taking another file as the sample coupled this probe to that file's
# shape: a test added there inside a class collects in alphabetical order, not
# source order, and reds a check about something else entirely.
SAMPLE = Path(__file__).resolve()
IDS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]


def _reordered(**order_env: str) -> list[str]:
    items = list(IDS)
    for name in ("TEST_COLLECTION_ORDER", "TEST_COLLECTION_SEED"):
        os.environ.pop(name, None)
    os.environ.update(order_env)
    try:
        conftest.pytest_collection_modifyitems(items=items)
    finally:
        for name in order_env:
            os.environ.pop(name, None)
    return items


def test_nothing_asked_leaves_the_order_alone():
    assert _reordered() == IDS


def test_reverse_turns_the_order_back_to_front():
    assert _reordered(TEST_COLLECTION_ORDER="reverse") == list(reversed(IDS))


def test_shuffle_moves_the_tests_and_repeats_itself_from_its_seed():
    shuffled = _reordered(TEST_COLLECTION_ORDER="shuffle")

    assert sorted(shuffled) == sorted(IDS)
    assert shuffled != IDS
    assert shuffled == _reordered(TEST_COLLECTION_ORDER="shuffle")
    assert shuffled != _reordered(TEST_COLLECTION_ORDER="shuffle",
                                  TEST_COLLECTION_SEED="1")


def test_an_order_nobody_recognizes_is_refused_rather_than_ignored():
    """A typo in the gate must not read as a second green run of the first order."""
    with pytest.raises(pytest.UsageError, match="reversed"):
        _reordered(TEST_COLLECTION_ORDER="reversed")


def test_pytest_asks_the_hook_when_it_collects():
    """The half a unit test cannot reach: that the gate's env var moves real
    tests, not just the list above."""
    declared = [line.split("def ")[1].split("(")[0]
                for line in SAMPLE.read_text(encoding="utf-8").splitlines()
                if line.lstrip().startswith("def test_")]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(SAMPLE),
         "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "TEST_COLLECTION_ORDER": "reverse"},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    collected = [line.split("::")[-1] for line in result.stdout.splitlines()
                 if "::" in line]

    assert collected == list(reversed(declared))
