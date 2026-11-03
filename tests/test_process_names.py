from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app_support.launcher import launchers
from app_support.process_identity_check import ProcessName, assert_the_process_is_named

from osr2_broker.process_names import APP_NAME, BROKER_ROLE, NAMER, TRAY_ROLE
from osr2_broker.tray import BrokerSupervisor, _name_this_process, terminate_broker

PROJECT_DIR = Path(__file__).resolve().parent.parent
LAUNCHER = next(launcher for launcher in launchers(PROJECT_DIR)
                if launcher.file == "launch_broker_tray.vbs")


class TestWhatTheRowsSay:
    def test_each_part_reads_as_the_app_and_its_part(self):
        assert NAMER.description(TRAY_ROLE) == f"{APP_NAME} \N{EN DASH} Tray"
        assert NAMER.description(BROKER_ROLE) == APP_NAME

    def test_the_two_cannot_collide_on_one_file_name(self):
        assert (NAMER.exe_name("pythonw.exe", TRAY_ROLE)
                != NAMER.exe_name("pythonw.exe", BROKER_ROLE))

    def test_the_icon_is_the_broker_s_own(self):
        assert NAMER.icon == PROJECT_DIR / "broker_icon.ico"
        assert NAMER.icon.is_file()


class TestTheTray:
    def test_prepares_the_copy_its_launcher_will_use(self, tmp_path: Path):
        assert_the_process_is_named(
            _name_this_process, tmp_path,
            ProcessName(
                app_name=APP_NAME,
                role=TRAY_ROLE,
                interpreter=LAUNCHER.interpreter,
                row=f"{APP_NAME} \N{EN DASH} Tray",
                icon=NAMER.icon,
            ),
        )

    def test_the_launcher_prefers_that_copy(self):
        assert LAUNCHER.named_interpreter == NAMER.exe_name(LAUNCHER.interpreter, TRAY_ROLE)

    def test_the_launcher_runs_the_windowed_interpreter(self):
        assert LAUNCHER.interpreter == "pythonw.exe"


class TestTheBroker:
    def test_is_named_outright_when_the_tray_launches_it(self):
        launched: list[list[str]] = []
        supervisor = BrokerSupervisor(
            SimpleNamespace(config_path=Path("C:/example/broker.json")),
            launch=launched.append, terminate=lambda: None, is_held=lambda name: False)

        with patch.object(NAMER, "named_exe", return_value="C:/example/Broker-Broker.exe") as named:
            supervisor.start()

        named.assert_called_once_with(sys.executable, BROKER_ROLE)
        assert launched[0][:3] == ["C:/example/Broker-Broker.exe", "-m", "osr2_broker.app"]

    def test_the_sweep_that_kills_it_knows_the_name_it_runs_under(self):
        with patch("osr2_broker.tray.subprocess.run") as run:
            terminate_broker(logging.getLogger("test"))

        assert NAMER.process_name_pattern in run.call_args.args[0][-1]
        assert run.call_args.args[0][-1] == (
            "Get-CimInstance Win32_Process | Where-Object { "
            f"$_.Name -match '{NAMER.process_name_pattern}' -and "
            "$_.CommandLine -match 'osr2_broker\\.app' "
            "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
            "-ErrorAction SilentlyContinue }")
        assert re.match(NAMER.process_name_pattern,
                        NAMER.exe_name("pythonw.exe", BROKER_ROLE))

    def test_that_sweep_still_finds_an_unnamed_broker(self):
        assert all(re.match(NAMER.process_name_pattern, name)
                   for name in ("pythonw.exe", "python.exe", "py.exe"))

    def test_that_sweep_leaves_other_apps_alone(self):
        for name in ("notepad.exe", "FunTime-MainFunestra.exe", "mypythonw.exe"):
            assert not re.match(NAMER.process_name_pattern, name), name
