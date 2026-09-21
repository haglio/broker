"""The document this repo publishes about itself, held against the repo.

Fun Time reads ``broker_contract.json`` to date this package's sources and to
find the two processes in the task list.  It cannot import anything here, so
the document is the whole agreement -- and a document that no longer matches
the package is exactly the silent failure it exists to end.  These hold it to
what is actually on disk.
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path, PurePosixPath

from osr2_broker import contract

REPO_ROOT = Path(__file__).resolve().parents[1]


def _document() -> dict:
    return json.loads(
        contract.contract_path(REPO_ROOT).read_text(encoding="utf-8"))


def test_the_published_document_is_what_this_package_says():
    """Run ``python -m osr2_broker.contract`` when this fails."""
    published = contract.contract_path(REPO_ROOT)

    assert published.read_text(encoding="utf-8") == contract.published_text()


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


def test_the_launcher_starts_the_tray_module_the_document_names():
    """The two ways this repo says what the tray runs, held together: the spec
    the launcher is rendered from, and the document Fun Time sweeps by."""
    spec = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    launchers = spec["tool"]["haglio"]["launchers"]
    run = launchers[contract.declaration()["tray_launcher"]]["run"]

    assert run.startswith(f"-m {contract.declaration()['tray_module']} ")


def test_the_name_it_publishes_is_the_one_the_tray_actually_runs_under():
    """Fun Time builds its image-name filter from the published name, so it has
    to be the name the launcher's own interpreter copy already wears."""
    spec = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    launchers = spec["tool"]["haglio"]["launchers"]
    named = launchers[contract.declaration()["tray_launcher"]]["named-interpreter"]

    assert named.startswith(contract.declaration()["app_name"] + "-")


def test_publishing_writes_the_document_where_a_supervisor_would_look(tmp_path):
    """``python -m osr2_broker.contract`` is how the tracked copy is refreshed."""
    written = contract.publish(tmp_path)

    assert written == tmp_path / contract.CONTRACT_FILE
    assert written.read_text(encoding="utf-8") == contract.published_text()


class TestWhereTheseFilesLive:
    """The directory the six state files sit in, which three apps meet at.

    This one writes them, a session and Origenerator read them, and only one of
    the three is always running -- so they live in the orchestrator's state
    directory rather than under this checkout.  A session and this app are each
    configured with the path; Origenerator had it written out in its own source.
    """

    def test_the_document_names_the_checkout_the_example_config_points_into(self):
        """The example is what a new install is set up from, so a document
        disagreeing with it sets one side up wrong from the first run."""
        configured = PurePosixPath(
            json.loads((REPO_ROOT / "osr2_broker_config.example.json")
                       .read_text(encoding="utf-8"))["state_dir"])
        named = _document()["state_dir"]

        assert configured.name == named["name"]
        assert configured.parent.name == named["checkout"]
