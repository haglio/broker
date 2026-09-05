"""The tray and the broker say which of the two they are, in the task list.

Both run as ``pythonw.exe``, so both arrived as identical anonymous "Python"
rows -- and a supervisor and the thing it supervises being indistinguishable is
exactly the pair you need to tell apart when one of them is stuck.  Windows
takes what it shows about a process from the file it was started from, so each
starts through a copy of the interpreter named, described and marked for its
part.

The two halves work differently and both are asserted here, by running them.
The broker is a child, so the tray names it outright as it launches it.  The
tray cannot name itself on the way in -- writing the copy takes the very
interpreter being named -- so it prepares its own for the next launch and the
launcher picks it up; the launcher's side is read off the ``.vbs``, which really
is a text file and really does contain the literal.
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app_support.process_identity_check import assert_the_app_names_its_process

from osr2_broker.process_names import APP_NAME, BROKER_ROLE, NAMER, TRAY_ROLE
from osr2_broker.tray import BrokerSupervisor, _name_this_process, terminate_broker

PROJECT_DIR = Path(__file__).resolve().parent.parent
LAUNCHER = (PROJECT_DIR / "launch_broker_tray.vbs").read_text(encoding="utf-8")


class TestWhatTheRowsSay:
    def test_each_part_reads_as_the_app_and_its_part(self):
        assert NAMER.description(TRAY_ROLE) == f"{APP_NAME} – Tray"
        assert NAMER.description(BROKER_ROLE) == APP_NAME

    def test_the_two_cannot_collide_on_one_file_name(self):
        # They share the venv the copies land in.
        assert (NAMER.exe_name("pythonw.exe", TRAY_ROLE)
                != NAMER.exe_name("pythonw.exe", BROKER_ROLE))

    def test_the_mark_is_the_broker_s_own(self):
        assert NAMER.icon == PROJECT_DIR / "broker_icon.ico"
        assert NAMER.icon.is_file()


class TestTheTray:
    def test_prepares_the_copy_its_launcher_will_use(self, tmp_path: Path):
        """From the windowed interpreter, which is what the launcher runs;
        described as the app and its part; carrying the broker's mark; and never
        taking the tray down when there is nothing to copy from."""
        assert_the_app_names_its_process(
            _name_this_process, tmp_path, app_name=APP_NAME, role=TRAY_ROLE,
            interpreter="pythonw.exe", row=f"{APP_NAME} – Tray", icon=NAMER.icon)

    def test_the_launcher_prefers_that_copy(self):
        expected = NAMER.exe_name("pythonw.exe", TRAY_ROLE)

        assert expected in LAUNCHER, f"the launcher does not look for {expected}"
        # After the plain interpreter is chosen, so the swap wins.
        assert LAUNCHER.rindex(expected) > LAUNCHER.index(r"\.venv\Scripts\pythonw.exe")

    def test_the_launcher_still_works_before_any_run_has_named_it(self):
        """The naming runs one launch behind, so a fresh checkout has no copy to
        find.  That must cost the name and nothing else."""
        assert r'pythonExe = projectRoot & "\.venv\Scripts\pythonw.exe"' in LAUNCHER


class TestTheBroker:
    def test_is_named_outright_when_the_tray_launches_it(self):
        """No one-launch delay for this one: the tray is holding the interpreter
        that writes the copy, and is not the process being named -- so the copy
        is made from the running interpreter, and the launch goes through it."""
        launched: list[list[str]] = []
        supervisor = BrokerSupervisor(
            SimpleNamespace(config_path=Path("C:/example/broker.json")),
            launch=launched.append, terminate=lambda: None, is_held=lambda name: False)

        with patch.object(NAMER, "named_exe", return_value="C:/example/Broker-Broker.exe") as named:
            supervisor.start()

        named.assert_called_once_with(sys.executable, BROKER_ROLE)
        assert launched[0][:3] == ["C:/example/Broker-Broker.exe", "-m", "osr2_broker.app"]

    def test_the_sweep_that_kills_it_knows_the_name_it_runs_under(self):
        """A broker running under a name the sweep does not match is a broker
        nothing here can stop -- so the sweep reads its pattern from the same
        namer that decides what a broker is launched as, rather than restating
        it and drifting."""
        with patch("osr2_broker.tray.subprocess.run") as run:
            terminate_broker(logging.getLogger("test"))

        assert NAMER.process_name_pattern in run.call_args.args[0][-1]
        assert re.match(NAMER.process_name_pattern,
                        NAMER.exe_name("pythonw.exe", BROKER_ROLE))

    def test_that_sweep_still_finds_an_unnamed_broker(self):
        # The copy is best-effort, so a broker can still arrive under the plain
        # interpreter and must stay reachable.
        assert all(re.match(NAMER.process_name_pattern, name)
                   for name in ("pythonw.exe", "python.exe", "py.exe"))

    def test_that_sweep_leaves_other_apps_alone(self):
        for name in ("notepad.exe", "FunTime-Nau.exe", "mypythonw.exe"):
            assert not re.match(NAMER.process_name_pattern, name), name
