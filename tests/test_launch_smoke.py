"""The launch smoke test: everything the tray launch imports, imported.

The suite can be entirely green while nothing appears in the notification area,
and this is the gap. The scheduled task, the Start Menu shortcut and fun_time
all start the broker the same way -- ``launch_broker_tray.vbs`` running
``pythonw -m osr2_broker.tray`` -- and ``main()`` there reaches the config, the
logging setup and the icon through imports *inside* the function, so a break in
any of them never touches a test that imports ``osr2_broker.tray`` and stops at
module level. The tray then spawns the broker itself as ``-m osr2_broker.app``,
so that module is on the same launch path.

``pythonw`` is what makes this invisible rather than merely broken: it has no
console, so an import that fails writes its traceback nowhere at all and the
tray icon simply never shows up.

So this drives the launch's import phase the way the launcher does: a fresh
interpreter, this repo as the working directory, no inherited ``PYTHONPATH``.

The statements come off the AST of the files the launch executes rather than a
list maintained here, because a hand-written list is exactly what would drift.
They are replayed as whole ``from X import a, b`` statements, not as ``import
X``, so a symbol the launch names but the module no longer defines fails here
too.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "osr2_broker"
LAUNCHER = REPO_ROOT / "launch_broker_tray.vbs"

# ``-m osr2_broker.tray`` runs tray.py, which is both the entrypoint and the
# module holding main(); it spawns the broker as ``-m osr2_broker.app``, whose
# own entrypoint is __main__.py.
LAUNCH_FILES = (
    REPO_ROOT / PACKAGE / "tray.py",
    REPO_ROOT / PACKAGE / "__main__.py",
    REPO_ROOT / PACKAGE / "app.py",
)

# Reached only from inside a main(), so a module-level import test never saw
# them. Asserted present, so a walk that silently found nothing -- a renamed
# file, a parse that returned an empty tree -- cannot pass as a clean launch.
_REACHED_ONLY_FROM_INSIDE_MAIN = (
    "osr2_broker.config",
    "osr2_broker.win32",
    "osr2_broker.monitor",
)

# Only these two. A broad ``except Exception`` around a launch body is an error
# *reporter* -- it puts a dialog on screen or writes a crash log -- so an import
# inside it is required, not optional: it failing is exactly the launch failure
# this file exists to catch.
_TOLERATED_BY = {"ImportError", "ModuleNotFoundError"}


# --------------------------------------------------------------------------
# What the launch imports
# --------------------------------------------------------------------------

def _is_type_checking(test: ast.expr) -> bool:
    """``if TYPE_CHECKING:`` bodies are never executed, at launch or anywhere."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _tolerates_a_missing_module(handlers: list[ast.ExceptHandler]) -> bool:
    for handler in handlers:
        if handler.type is None:  # bare except -- catches everything, promises nothing
            return False
        caught = (
            handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        )
        if any(isinstance(n, ast.Name) and n.id in _TOLERATED_BY for n in caught):
            return True
    return False


def _optional_imports(tree: ast.Module) -> set[int]:
    """Imports whose absence the module already handles, so the launch survives
    them and this test must not insist on them."""
    optional: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            body = node.body
        elif isinstance(node, ast.Try) and _tolerates_a_missing_module(node.handlers):
            body = node.body
        else:
            continue
        for statement in body:
            for inner in ast.walk(statement):
                optional.add(id(inner))
    return optional


def _render(node: ast.Import | ast.ImportFrom, package: str) -> str:
    """The import statement as the launch executes it, relative made absolute.

    Every launch file here sits at the top of its package, so a relative import
    is never deeper than one level.
    """
    names = ", ".join(
        alias.name + (f" as {alias.asname}" if alias.asname else "")
        for alias in node.names
    )
    if isinstance(node, ast.Import):
        return f"import {names}"
    assert node.level <= 1, f"unexpected relative import depth in {package}"
    module = node.module or ""
    if node.level:
        module = f"{package}.{module}" if module else package
    return f"from {module} import {names}"


def _is_a_compiler_directive(node: ast.Import | ast.ImportFrom) -> bool:
    """``from __future__ import ...`` loads no module -- it is a flag to the
    compiler, and it is only legal at the top of a file, so replaying it among
    the others is a SyntaxError rather than a check of anything."""
    return isinstance(node, ast.ImportFrom) and node.module == "__future__"


def _launch_imports(package: str, launch_files) -> list[str]:
    statements: list[str] = []
    for path in launch_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        optional = _optional_imports(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if id(node) in optional or _is_a_compiler_directive(node):
                continue
            statements.append(_render(node, package))
    return statements


def _run_the_launchs_way(statements: list[str]) -> subprocess.CompletedProcess:
    """Run them the way ``launch_broker_tray.vbs`` runs the tray.

    The launcher sets this repo as the working directory and runs the venv's
    pythonw with nothing else, so the working directory is the whole path story
    -- any ``PYTHONPATH`` a developer or pytest happens to be carrying is
    dropped, because the scheduled task does not get it.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["QT_QPA_PLATFORM"] = "offscreen"

    return subprocess.run(
        [sys.executable, "-c", "\n".join(statements)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_the_launch_imports_everything_it_names():
    """Failing here means no tray icon and no explanation: pythonw has no
    console, so the traceback from a failed import goes nowhere."""
    result = _run_the_launchs_way(_launch_imports(PACKAGE, LAUNCH_FILES))

    assert result.returncode == 0, result.stderr


def test_the_walk_reaches_the_imports_buried_in_main():
    """The guard above is only worth anything if the walk found the lazy ones --
    which is where the config, the icon and the shutdown guard are."""
    found = "\n".join(_launch_imports(PACKAGE, LAUNCH_FILES))

    for module in _REACHED_ONLY_FROM_INSIDE_MAIN:
        assert module in found, f"the launch imports {module}; the walk missed it"


def test_a_launch_import_that_cannot_resolve_fails_here():
    """A negative control: if the subprocess reported success regardless, every
    assertion above would pass vacuously and the guard would be decorative."""
    result = _run_the_launchs_way(
        [*_launch_imports(PACKAGE, LAUNCH_FILES), "from osr2_broker.config import NoSuchSymbol"]
    )

    assert result.returncode != 0
    assert "NoSuchSymbol" in result.stderr


def test_the_launcher_runs_the_tray_from_this_repo_on_its_own_venv():
    """A python off PATH misses the editable siblings the tray imports and dies
    while importing -- which under pythonw is a launch that leaves no trace at
    all. The working directory is what this test's ``cwd`` mirrors, so a
    launcher that stopped setting it would leave this checking a fiction."""
    text = LAUNCHER.read_text(encoding="utf-8", errors="replace")

    assert ".venv\\Scripts\\pythonw.exe" in text
    assert "-m osr2_broker.tray" in text
    assert "shell.CurrentDirectory = projectRoot" in text
