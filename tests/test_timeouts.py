"""A hung test has to die and name itself, not hold the merge queue for six hours.

No repo in this family put a clock on a test, on suites that block on threads,
sockets and child processes. A required check with no budget stalls until
GitHub's own six-hour job limit and prints nothing that says which test stopped
-- so the budget lives here, where removing it goes red rather than quiet.

The number is a ceiling, not a target: it clears this suite's slowest test
several times over, so it can bite on a hang and on nothing else.
"""
from __future__ import annotations


def test_every_test_runs_under_its_own_clock(pytestconfig):
    """Declared, not merely in effect: a command line can override the option,
    and what this guards is that the configuration still asks for it."""
    addopts = pytestconfig.getini("addopts")

    assert "--timeout=60" in addopts
    assert "--timeout-method=thread" in addopts
