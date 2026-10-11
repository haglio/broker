"""The idle warning, shown by a process of its own: Qt wants its application on
its process's main thread, and the broker's monitor runs on another."""
from __future__ import annotations

import subprocess
import sys

from app_support.cli import preparse_config_path
from shared_ui.preview import Preview, preview_of, window_title

from .config import PROJECT_DIR, BrokerConfig, load_config
from .win32 import ICON_PATH, claim_taskbar_identity


def show_until_closed(config: BrokerConfig, *, run=subprocess.run) -> subprocess.CompletedProcess:
    return run(
        [sys.executable, "-m", __spec__.name, "--config", str(config.config_path)],
        cwd=PROJECT_DIR,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def show_warning(title: str, message: str, *, button_text: str,
                 shown_as: Preview | None) -> None:
    """Show the family's warning dialog under the broker's own identity.

    Blocks until dismissed.  The taskbar identity goes first: Windows reads it
    when a window of this process first appears, and without one the dialog's
    taskbar button wears the python host's icon rather than the broker's.
    """
    from PyQt6.QtWidgets import QApplication  # noqa: PLC0415
    from shared_ui.alert import Level, show_alert  # noqa: PLC0415
    from shared_ui.preview_icon import app_icon  # noqa: PLC0415

    claim_taskbar_identity(shown_as)
    _the_app_its_icon_is_drawn_in = QApplication.instance() or QApplication([])
    show_alert(
        window_title(title, shown_as), message,
        level=Level.WARNING, icon=app_icon(ICON_PATH, shown_as), button_text=button_text,
    )


def main(argv: list[str] | None = None) -> int:
    config = load_config(preparse_config_path(argv))
    show_warning(
        "OSR2 Broker",
        f"Your OSR2 has been idle for {int(config.idle_minutes)} minutes.\n"
        "Did you forget to turn it off?",
        button_text="I don't know, did you?",
        shown_as=preview_of(PROJECT_DIR),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
