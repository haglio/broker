"""System tray icon for the broker, dark-themed via shared_ui."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app_support.win32 import is_mutex_held, mutex_name, try_acquire_mutex
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon
from shared_ui.colors import BG_BUTTON, BG_TERTIARY, TEXT_MUTED, TEXT_PRIMARY

from . import peer_watch
from .single_instance import MUTEX_BROKER, MUTEX_TRAY

# The numbers the broker writes to its mode file, in the words the menu shows.
MODE_NAMES = {"0": "control", "1": "auto"}

# How often the watchdog checks the broker is still there.
WATCHDOG_INTERVAL_MS = 5_000


def mode_text(mode_file: Path) -> str:
    """Name the auto-mode the broker last recorded, or "unknown" if it hasn't."""
    try:
        raw = mode_file.read_text(encoding="utf-8")
    except OSError:
        return "unknown"

    mode = raw.replace("﻿", "").strip()
    return MODE_NAMES.get(mode, f"mode={mode}")


def open_in_editor(path: Path) -> None:
    """Open a file in Notepad — the one editor a stock Windows always has."""
    subprocess.Popen(["notepad.exe", str(path)])


def menu_stylesheet() -> str:
    """Qt style sheet painting a menu in the family's dark palette."""
    return f"""
        QMenu {{
            background: {BG_TERTIARY.name()};
            color: {TEXT_PRIMARY.name()};
        }}
        QMenu::item:selected {{
            background: {BG_BUTTON.name()};
        }}
        QMenu::item:disabled {{
            color: {TEXT_MUTED.name()};
            background: transparent;
        }}
    """


def build_menu() -> QMenu:
    """Build the tray's right-click menu."""
    menu = QMenu()
    menu.setStyleSheet(menu_stylesheet())
    return menu


class BrokerSupervisor:
    """Starts, stops and reports on the broker process for one config.

    Liveness comes from the broker's own single-instance mutex rather than a
    process scan: it is instant, and it cannot mistake a diagnostic command
    line mentioning the broker for the broker itself.
    """

    def __init__(self, config, *, launch, terminate, is_held=is_mutex_held):
        self._config = config
        self._mutex_name = mutex_name(MUTEX_BROKER, config.config_path)
        self._launch = launch
        self._terminate = terminate
        self._is_held = is_held

    def is_running(self) -> bool:
        return self._is_held(self._mutex_name)

    def _broker_argv(self) -> list[str]:
        # Named outright rather than one launch behind: the broker is a child,
        # so the tray is holding the interpreter that writes the copy and is not
        # the process being named.  See osr2_broker.process_names.
        from .process_names import BROKER_ROLE, NAMER
        return [
            NAMER.named_exe(sys.executable, BROKER_ROLE), "-m", "osr2_broker.app",
            "--config", str(self._config.config_path),
        ]

    def start(self) -> None:
        """Launch a broker, unless one is already up."""
        if self.is_running():
            return
        self._launch(self._broker_argv())

    def stop(self) -> None:
        self._terminate()

    def restart(self) -> None:
        self._terminate()
        self._launch(self._broker_argv())


class BrokerTray(QSystemTrayIcon):
    """Tray icon exposing the broker's status and controls."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._menu = build_menu()

        self.status_action = QAction("Broker status: unknown", self._menu)
        self.status_action.setEnabled(False)
        self._menu.addAction(self.status_action)

        self.start_action = QAction("Start broker", self._menu)
        self._menu.addAction(self.start_action)

        self.pause_action = QAction("Pause broker", self._menu)
        self._menu.addAction(self.pause_action)

        self.log_action = QAction("Open broker log", self._menu)
        self._menu.addAction(self.log_action)

        self._menu.addSeparator()

        self.quit_action = QAction("Quit", self._menu)
        self._menu.addAction(self.quit_action)

        self.setContextMenu(self._menu)

    def set_status(self, running: bool, mode: str) -> None:
        """Retitle the menu and tooltip for the broker's current state."""
        if running:
            self.status_action.setText(f"Broker status: running ({mode})")
            self.setToolTip(f"OSR2 Broker: running ({mode})")
        else:
            self.status_action.setText("Broker status: stopped")
            self.setToolTip("OSR2 Broker: stopped")

        self.start_action.setText("Restart broker" if running else "Start broker")
        self.pause_action.setEnabled(running)


class BrokerTrayApp:
    """Policy: keep a broker alive, and keep the tray telling the truth."""

    def __init__(self, config, supervisor, tray: BrokerTray, *, open_file=None,
                 peer=None, stand_down=peer_watch.stand_broker_down):
        self._config = config
        self._supervisor = supervisor
        self._tray = tray
        self._open_file = open_file or open_in_editor
        self._peer = peer
        self._stand_down = stand_down
        self._paused = False

        tray.start_action.triggered.connect(self.start_or_restart)
        tray.pause_action.triggered.connect(self.pause)
        tray.log_action.triggered.connect(self.open_log)

    def tick(self) -> None:
        """One watchdog beat: revive the broker unless the user paused it.

        Evolver gets looked at on the same beat, and is NOT covered by the pause
        -- pausing here is about the OSR2, and says nothing about the app next
        door. The watch throttles itself to its own interval, so passing every
        five-second beat through it costs one comparison.
        """
        if not self._paused:
            self._supervisor.start()
        if self._peer is not None:
            self._peer.tick()
        self.refresh()

    def refresh(self) -> None:
        self._tray.set_status(
            running=self._supervisor.is_running(),
            mode=mode_text(self._config.genau_mode_file),
        )

    def start_or_restart(self) -> None:
        """Honour the menu's Start/Restart, and take the broker off pause."""
        self._paused = False
        if self._supervisor.is_running():
            self._supervisor.restart()
        else:
            self._supervisor.start()
        self.refresh()

    def pause(self) -> None:
        self._paused = True
        self._supervisor.stop()
        self.refresh()

    def open_log(self) -> None:
        """Show the broker's log, even on a run that has yet to write one."""
        log_path = self._config.log_file("broker")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.touch(exist_ok=True)
        self._open_file(log_path)

    def quit(self, quit_app) -> None:
        """Take the broker down too — nothing else would supervise it.

        And leave the mark that tells Evolver this was asked for, so it does not
        start the tray again a quarter of an hour later. Every other way the tray
        dies leaves no mark and is undone, which is the point of the pairing.
        """
        self._stand_down()
        self._supervisor.stop()
        self._tray.hide()
        quit_app()


def launch_broker(argv: list[str], config, logger) -> None:
    """Start the broker detached, with its console output kept for post-mortems."""
    launcher_log = config.log_file("broker_service_launcher").open("a", encoding="utf-8")
    subprocess.Popen(
        argv,
        cwd=str(config.project_dir),
        stdout=launcher_log,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
    )
    logger.info("Launched broker")


def terminate_broker(logger) -> None:
    """Kill whichever process is running the broker.

    The tray does not necessarily own it: a tray that was itself restarted
    inherits the broker of the tray before it, so this matches on the command
    line rather than on a child handle we may not hold.

    The image-name half comes from the same namer that decides what a broker is
    launched under, because the two cannot be allowed to drift: a broker running
    under a name this sweep does not know is a broker nothing here can stop.
    """
    from .process_names import NAMER
    subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
            "Get-CimInstance Win32_Process | Where-Object { "
            f"$_.Name -match '{NAMER.process_name_pattern}' -and "
            "$_.CommandLine -match 'osr2_broker\\.app' "
            "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
            "-ErrorAction SilentlyContinue }",
        ],
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    logger.info("Terminated broker")


def _guarded_tick(tray_app: BrokerTrayApp, logger) -> None:
    """The tray is the broker's only supervisor; a bad beat must not end it."""
    try:
        tray_app.tick()
    except Exception:
        logger.exception("Watchdog tick failed")


def _name_this_process() -> None:
    """Leave ``launch_broker_tray.vbs`` an interpreter that says "Broker – Tray"
    next time.  Why it is one launch behind, and why it can never cost the
    launch: :meth:`ProcessNamer.name_this_process`."""
    from .process_names import NAMER, TRAY_ROLE
    NAMER.name_this_process(TRAY_ROLE)


def main(argv: list[str] | None = None) -> int:
    _name_this_process()
    from app_support.cli import preparse_config_path
    from app_support.logging_utils import configure_logging, install_exception_logging
    from PyQt6.QtCore import QTimer
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication

    from .config import load_config
    from .win32 import ICON_PATH, claim_taskbar_identity

    config = load_config(preparse_config_path(argv))
    logger = configure_logging("osr2_broker.tray", config.log_file("broker_tray"))
    install_exception_logging(logger)

    # The scheduled task relaunches us every couple of minutes so a killed tray
    # is revived; while one is alive each relaunch must be a no-op.
    _mutex_handle = try_acquire_mutex(MUTEX_TRAY)
    if _mutex_handle is None:
        logger.info("Another tray is already running; exiting")
        return 0

    # Whatever the user wanted the last time they quit this tray, starting it is
    # them wanting it up now -- and the scheduled task relaunches us every couple
    # of minutes, so the mutex check above is what makes this run once per
    # deliberate start rather than every two minutes.
    peer_watch.clear_broker_stand_down()

    claim_taskbar_identity()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    tray = BrokerTray()
    tray.setIcon(QIcon(str(ICON_PATH)))

    supervisor = BrokerSupervisor(
        config,
        launch=lambda argv_: launch_broker(argv_, config, logger),
        terminate=lambda: terminate_broker(logger),
    )
    tray_app = BrokerTrayApp(
        config, supervisor, tray, peer=peer_watch.watch_evolver(config, logger))
    tray.quit_action.triggered.connect(lambda: tray_app.quit(app.quit))

    timer = QTimer()
    timer.setInterval(WATCHDOG_INTERVAL_MS)
    timer.timeout.connect(lambda: _guarded_tick(tray_app, logger))
    timer.start()

    logger.info("Tray started (pid %d)", os.getpid())
    tray.show()
    tray_app.tick()
    try:
        return app.exec()
    finally:
        logger.info("Tray exiting (pid %d)", os.getpid())


if __name__ == "__main__":
    raise SystemExit(main())
