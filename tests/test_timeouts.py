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
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


_JOB = re.compile(r'  "?([A-Za-z0-9_-]+)"?:\s*(#.*)?')
_CLOCK = re.compile(r'    "?timeout-minutes"?:\s*"?[1-9][0-9]*"?\s*(#.*)?')
# A job that calls the family's gate is clocked by it: the clock is that workflow's
# to declare, and a caller may not declare one of its own.
_THE_FAMILYS_GATE = re.compile(r'    "?uses"?:\s*"?haglio/\.github/\.github/workflows/merge-gate\.yml@\S+"?\s*(#.*)?')


def _jobs_without_a_clock(workflow: str) -> list[str]:
    """The jobs in one workflow that do not declare ``timeout-minutes``.

    A scan rather than a YAML parse: PyYAML is not a dependency here, and adding
    one to read a single key would cost more than the key is worth. Comments are
    skipped wherever they sit, including at column 0 -- a full-line separator
    between two jobs is legal YAML, and reading it as the end of the block would
    wave through every job below it without ever looking.
    """
    unclocked: list[str] = []
    current: str | None = None
    in_jobs = False
    for line in workflow.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("jobs:"):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if not line.startswith(" "):
            break
        named = _JOB.fullmatch(line)
        if named:
            current = named.group(1)
            unclocked.append(current)
        elif current in unclocked and (_CLOCK.fullmatch(line) or _THE_FAMILYS_GATE.fullmatch(line)):
            unclocked.remove(current)
    return unclocked


def test_every_test_runs_under_its_own_clock(pytestconfig):
    """Declared, not merely in effect: a command line can override the option,
    and what this guards is that the configuration still asks for it."""
    addopts = pytestconfig.getini("addopts")

    assert "--timeout=60" in addopts
    assert "--timeout-method=thread" in addopts


def test_every_workflow_job_runs_under_its_own_clock():
    """The other half, and not only for the gate. A run that hangs before
    pytest's timer is armed -- in collection, in a plugin, in pip -- is caught by
    nothing but the job's clock, and that is as true of a workflow nobody is
    watching as of the required check."""
    unclocked = {path.name: _jobs_without_a_clock(path.read_text(encoding="utf-8"))
                 for path in sorted(WORKFLOWS.glob("*.y*ml"))}

    assert unclocked, f"no workflows found in {WORKFLOWS}"
    assert {name: jobs for name, jobs in unclocked.items() if jobs} == {}


def test_the_plugin_that_keeps_the_clock_is_declared_where_ci_installs_it():
    """The half no run of this suite can catch by failing.

    pytest rejects an option it does not recognise before it collects anything,
    so a `--timeout` in the config with no `pytest-timeout` in the dev extra is
    not a red test -- it is a usage error, and the required check goes red with
    no suite behind it. It cannot happen locally either, because the shared
    development venv has the plugin whether this repo asks for it or not. So the
    declaration is checked here, where a run that works can still say it is
    missing.
    """
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    dev = project["optional-dependencies"]["dev"]

    assert "pytest-timeout" in {name.split(";")[0].strip().lower().replace("_", "-")
                                for name in dev}
