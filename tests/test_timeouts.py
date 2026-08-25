"""A hung test has to die and name itself, not hold the merge queue for six hours.

No repo in this family put a clock on a test, on suites that block on threads,
sockets and child processes. A required check with no budget stalls until
GitHub's own six-hour job limit and prints nothing that says which test stopped
-- so the budget lives here, where removing it goes red rather than quiet.

Both numbers are ceilings, not targets: the per-test budget clears this suite's
slowest test several times over, and the job budget is about three times a green
run. They bite on a hang and on nothing else.
"""
from __future__ import annotations

import re
from pathlib import Path

MERGE_GATE = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "merge-gate.yml"


def _jobs_and_whether_they_are_clocked(workflow: str) -> dict[str, bool]:
    """Map every job in a workflow to whether it declares ``timeout-minutes``.

    A scan rather than a YAML parse: PyYAML is not a dependency here, and adding
    one to read a single key would cost more than the key is worth.
    """
    jobs: dict[str, bool] = {}
    current: str | None = None
    in_jobs = False
    for line in workflow.splitlines():
        if line.startswith("jobs:"):
            in_jobs = True
            continue
        if not in_jobs or not line.strip():
            continue
        if not line.startswith(" "):
            break
        named = re.fullmatch(r"  ([A-Za-z0-9_-]+):", line)
        if named:
            current = named.group(1)
            jobs[current] = False
        elif current and re.fullmatch(r"    timeout-minutes: [1-9][0-9]*", line):
            jobs[current] = True
    return jobs


def test_every_test_runs_under_its_own_clock(pytestconfig):
    """Declared, not merely in effect: a command line can override the option,
    and what this guards is that the configuration still asks for it."""
    addopts = pytestconfig.getini("addopts")

    assert "--timeout=60" in addopts
    assert "--timeout-method=thread" in addopts


def test_the_merge_gate_runs_under_its_own_clock():
    """The other half. A run that hangs before pytest's timer is armed -- in
    collection, in a plugin, in pip -- is only ever caught by the job's clock."""
    jobs = _jobs_and_whether_they_are_clocked(MERGE_GATE.read_text(encoding="utf-8"))

    assert jobs, f"no jobs found in {MERGE_GATE.name}"
    assert [name for name, clocked in jobs.items() if not clocked] == []
