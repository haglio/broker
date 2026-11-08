from __future__ import annotations

import os
import uuid
from unittest.mock import patch

from app_support.win32 import is_mutex_held, try_acquire_mutex

from osr2_broker import branch_session
from osr2_broker.config import load_config
from osr2_broker.process_names import NAMER
from osr2_broker.single_instance import MUTEX_TRAY


def test_reading_the_flag_keeps_it_from_everything_the_preview_starts_the_broker_and_evolver_would_carry_it_and_evolver_would_hand_it_to_the_next_production_tray(monkeypatch):
    monkeypatch.setenv(branch_session.FLAG, "1")

    assert branch_session.take_the_flag() is True
    assert branch_session.FLAG not in os.environ


def test_a_tray_launched_without_the_flag_is_the_production_one(monkeypatch):
    monkeypatch.delenv(branch_session.FLAG, raising=False)

    assert branch_session.take_the_flag() is False


def test_a_preview_takes_the_tray_over_by_ending_the_one_running():
    claims = iter([None, None, 42])
    asked, ended = [], []

    handle = branch_session.take_the_tray_over(
        claim=lambda name: asked.append(name) or next(claims),
        end_the_other_trays=lambda: ended.append(True),
        sleep=lambda seconds: None,
    )

    assert handle == 42
    assert ended == [True, True]
    assert set(asked) == {MUTEX_TRAY}


def test_a_preview_that_cannot_take_the_tray_over_gives_up():
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    handle = branch_session.take_the_tray_over(
        claim=lambda name: None,
        end_the_other_trays=lambda: None,
        sleep=sleep,
        clock=lambda: now[0],
    )

    assert handle is None
    assert now[0] >= branch_session.PATIENCE_SECONDS


def test_handing_back_lets_go_of_the_tray_before_starting_the_production_one(cfg_path):
    config = load_config(cfg_path)
    happened = []

    branch_session.hand_back(
        config, 42,
        release=lambda handle: happened.append(("let go of", handle)),
        start_the_production_tray=lambda started: happened.append(("started", started)),
    )

    assert happened == [("let go of", 42), ("started", config)]


def test_ending_the_other_trays_spares_this_process_and_its_parent_a_venvs_pythonw_runs_the_real_interpreter_as_its_child_on_the_same_command_line_and_ending_it_ends_this_one():
    with patch.object(branch_session.subprocess, "run") as run:
        branch_session.end_the_other_trays()

    sweep = run.call_args.args[0][-1]
    assert NAMER.process_name_pattern in sweep
    assert r"-match 'osr2_broker\.tray'" in sweep
    assert f"$_.ProcessId -ne {os.getpid()}" in sweep
    assert f"$_.ProcessId -ne {os.getppid()}" in sweep
    assert sweep == (
        "Get-CimInstance Win32_Process | Where-Object { "
        f"$_.Name -match '{NAMER.process_name_pattern}' -and "
        "$_.CommandLine -match 'osr2_broker\\.tray' -and "
        f"$_.ProcessId -ne {os.getpid()} -and "
        f"$_.ProcessId -ne {os.getppid()} "
        "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
        "-ErrorAction SilentlyContinue }")


def test_letting_go_of_a_claim_frees_it_for_the_next_tray():
    name = f"Local\\OSR2Broker.Test.{uuid.uuid4()}"
    claim = try_acquire_mutex(name)
    assert is_mutex_held(name)

    branch_session.let_go_of(claim)

    assert not is_mutex_held(name)


def test_the_production_tray_starts_from_the_production_checkout_and_not_as_a_preview(
        cfg_path, monkeypatch):
    config = load_config(cfg_path)
    monkeypatch.setenv(branch_session.FLAG, "1")

    with patch.object(branch_session.subprocess, "Popen") as popen:
        branch_session.start_the_production_tray(config)

    (argv,), kwargs = popen.call_args
    assert argv == ["wscript.exe", str(config.project_dir / "launch_broker_tray.vbs")]
    assert branch_session.FLAG not in kwargs["env"]


def test_the_production_tray_loads_its_own_modules_rather_than_the_preview_s(cfg_path, monkeypatch):
    config = load_config(cfg_path)
    monkeypatch.setenv("PYTHONPATH", "C:/workspace/shared_ui/.claude/worktrees/a-change")

    with patch.object(branch_session.subprocess, "Popen") as popen:
        branch_session.start_the_production_tray(config)

    (_argv,), kwargs = popen.call_args
    assert "PYTHONPATH" not in kwargs["env"]


def test_a_preview_nobody_quits_hands_the_tray_back_after_an_hour(qapp):
    quits = []

    timer = branch_session.hand_back_later(lambda: quits.append(True))

    assert timer.isSingleShot()
    assert timer.interval() == 60 * 60 * 1000
    timer.timeout.emit()
    assert quits == [True]
