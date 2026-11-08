from __future__ import annotations

import json
import tomllib
from pathlib import Path, PurePosixPath

from osr2_broker import contract
from osr2_broker.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def _document() -> dict:
    return json.loads(
        contract.contract_path(REPO_ROOT).read_text(encoding="utf-8"))


def test_the_published_document_is_what_this_package_says():
    published = contract.contract_path(REPO_ROOT)

    assert published.read_text(encoding="utf-8") == contract.published_text(), (
        "run python -m osr2_broker.contract to rewrite the tracked copy; never edit it by hand")


def test_the_package_directory_it_names_is_this_package():
    named = REPO_ROOT / contract.declaration()["package_dir"]

    assert (named / "__init__.py").is_file()


def test_both_module_paths_it_names_are_importable_files_here():
    for key in ("broker_module", "tray_module"):
        module = contract.declaration()[key]
        package, _, leaf = module.rpartition(".")
        assert (REPO_ROOT / package / f"{leaf}.py").is_file(), module


def test_the_launcher_it_names_is_the_one_in_this_checkout():
    assert (REPO_ROOT / contract.declaration()["tray_launcher"]).is_file()


def test_the_stop_request_it_names_is_the_file_the_tray_answers(cfg_path):
    assert _document()["stop_request"] == load_config(cfg_path).stop_request_file.name


def test_the_launcher_starts_the_tray_module_the_document_names_which_fun_time_sweeps_the_task_list_by():
    spec = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    launchers = spec["tool"]["haglio"]["launchers"]
    run = launchers[contract.declaration()["tray_launcher"]]["run"]

    assert run.startswith(f"-m {contract.declaration()['tray_module']} ")


def test_the_name_it_publishes_is_the_one_the_tray_runs_under_fun_time_filters_processes_by_it():
    spec = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    launchers = spec["tool"]["haglio"]["launchers"]
    named = launchers[contract.declaration()["tray_launcher"]]["named-interpreter"]

    assert named.startswith(contract.declaration()["app_name"] + "-")


def test_the_document_sits_beside_the_tray_launcher_the_one_path_a_supervisor_that_cannot_import_us_is_told(tmp_path):
    written = contract.publish(tmp_path)

    assert written == tmp_path / contract.CONTRACT_FILE
    assert written.read_text(encoding="utf-8") == contract.published_text()


class TestTheStateFilesLiveInTheOrchestratorsStateDirWhereThreeAppsMeetAndOneIsAlwaysRunning:
    def test_the_place_is_published_for_origenerator_which_has_no_setting_and_matches_the_example_a_new_install_is_set_up_from(self):
        configured = PurePosixPath(
            json.loads((REPO_ROOT / "osr2_broker_config.example.json")
                       .read_text(encoding="utf-8"))["state_dir"])
        named = _document()["state_dir"]

        assert configured.name == named["name"]
        assert configured.parent.name == named["checkout"]


def test_the_document_carries_what_fun_time_needs_to_date_find_and_start_the_broker_without_importing_it():
    document = _document()

    assert document["package_dir"] == "osr2_broker"
    assert document["broker_module"] == "osr2_broker.app"
    assert document["tray_module"] == "osr2_broker.tray"
    assert document["tray_launcher"] == "launch_broker_tray.vbs"
