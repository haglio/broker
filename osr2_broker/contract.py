"""What a supervising app must know about this one, published where it can read it.

Fun Time starts the broker, decides whether a running one is stale, and stops
one it has to replace -- all without importing this package, because no app
here reaches into another's repo.  So it works from names: the name the two
processes are labelled with, the directory this package lives in (whose sources
it stats to date a running broker), the two module paths those processes run
under (which it matches in the task list), and the launcher that starts the
tray.

Spelled over there, those names were a copy of these: renaming this package
left the date unreadable and the sweep walking past the very process it came to
stop, with nothing red on either side.  Spelled here they come from the package
itself, and ``broker_contract.json`` beside the launcher is how they travel.
Run ``python -m osr2_broker.contract`` to rewrite it; the suite fails on a copy
that no longer matches.
"""
from __future__ import annotations

import json
from pathlib import Path

from .process_names import APP_NAME, PROJECT_DIR

#: Beside the tray launcher, which is the one path a supervisor is already told.
CONTRACT_FILE = "broker_contract.json"

#: Taken from the package rather than typed, so a rename carries into all three.
PACKAGE_DIR = __package__
BROKER_MODULE = f"{__package__}.app"
TRAY_MODULE = f"{__package__}.tray"

#: The file that starts the tray, which starts the broker.
TRAY_LAUNCHER = "launch_broker_tray.vbs"

#: Where this app's six state files sit, as a path under the checkout named
#: here rather than under this one.  Three apps meet at that directory -- this
#: one writes the files, a session and Origenerator read them -- and only one of
#: the three is always running, which is why they live in the orchestrator's
#: state directory and this app is configured to write there.  A session and
#: this app are each told the path outright; Origenerator has no such key and
#: walked to that checkout in its own source, so one app's directory layout was
#: a fact written down inside another, where a change to it would be found by
#: nobody and the only symptom is a device reading as switched off.
STATE_DIR_CHECKOUT = "fun_time"
STATE_DIR_NAME = "state"


def declaration() -> dict[str, str]:
    """The published document, as a supervisor reads it."""
    return {
        "app_name": APP_NAME,
        "package_dir": PACKAGE_DIR,
        "broker_module": BROKER_MODULE,
        "tray_module": TRAY_MODULE,
        "tray_launcher": TRAY_LAUNCHER,
        "state_dir": {"checkout": STATE_DIR_CHECKOUT, "name": STATE_DIR_NAME},
    }


def published_text() -> str:
    return json.dumps(declaration(), indent=2) + "\n"


def contract_path(root: Path | None = None) -> Path:
    return (root if root is not None else PROJECT_DIR) / CONTRACT_FILE


def publish(root: Path | None = None) -> Path:
    """Write the document out, in the shape the tracked copy holds."""
    path = contract_path(root)
    path.write_text(published_text(), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(publish())
