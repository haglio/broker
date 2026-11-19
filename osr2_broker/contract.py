from __future__ import annotations

import json
from pathlib import Path

from .process_names import APP_NAME, PROJECT_DIR

CONTRACT_FILE = "broker_contract.json"

PACKAGE_DIR = __package__
BROKER_MODULE = f"{__package__}.app"
TRAY_MODULE = f"{__package__}.tray"

TRAY_LAUNCHER = "launch_broker_tray.vbs"

STOP_REQUEST = "broker_stop_request.txt"

STATE_DIR_CHECKOUT = "fun_time"
STATE_DIR_NAME = "state"


def declaration() -> dict[str, str]:
    return {
        "app_name": APP_NAME,
        "package_dir": PACKAGE_DIR,
        "broker_module": BROKER_MODULE,
        "tray_module": TRAY_MODULE,
        "tray_launcher": TRAY_LAUNCHER,
        "stop_request": STOP_REQUEST,
        "state_dir": {"checkout": STATE_DIR_CHECKOUT, "name": STATE_DIR_NAME},
    }


def published_text() -> str:
    return json.dumps(declaration(), indent=2) + "\n"


def contract_path(root: Path | None = None) -> Path:
    return (root if root is not None else PROJECT_DIR) / CONTRACT_FILE


def publish(root: Path | None = None) -> Path:
    path = contract_path(root)
    path.write_text(published_text(), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(publish())
