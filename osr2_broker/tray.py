from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app_support import production_update
from app_support.cli import preparse_config_path
from app_support.logging_utils import configure_logging, install_exception_logging
from app_support.osr2_device import Osr2Mode, Osr2Trouble, mode, trouble
from app_support.threading_utils import start_daemon_thread
from app_support.win32 import is_mutex_held, mutex_name, try_acquire_mutex
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from shared_ui.chrome import menu_rules
from shared_ui.colors import TEXT_SECONDARY
from shared_ui.icons import qt_icon
from shared_ui.loading_window import Loading, LoadingCanceled
from shared_ui.preview import Preview, preview_of, taskbar_identity, window_title
from shared_ui.preview_icon import app_icon

from . import branch_session, peer_watch
from .config import PROJECT_DIR, load_config
from .process_names import APP_NAME, BROKER_ROLE, NAMER, TRAY_ROLE, end_the_processes_running
from .single_instance import MUTEX_BROKER, MUTEX_TRAY
from .win32 import APP_USER_MODEL_ID, ICON_PATH, claim_taskbar_identity

WATCHDOG_INTERVAL_MS = 5_000
STEPS = (("Loading Broker...", 1.0),)


_WHAT_THE_OSR2_IS_DOING = {
    Osr2Mode.OFF: "OSR2 off",
    Osr2Mode.AUTO: "but OSR2 in auto mode",
    Osr2Mode.CONTROLLED: "controlling OSR2",
}
_WHY_THE_OSR2_IS_UNHEARD = {
    Osr2Trouble.NOT_FOUND: "OSR2 unplugged",
    Osr2Trouble.NOT_ANSWERING: "OSR2 no answer",
}


def what_the_osr2_is_doing(config) -> str:
    unheard = trouble(config.state_dir)
    if unheard is not None:
        return _WHY_THE_OSR2_IS_UNHEARD[unheard]
    return _WHAT_THE_OSR2_IS_DOING[mode(config.state_dir)]


def open_in_editor(path: Path) -> None:
    # The one editor a stock Windows always has.
    subprocess.Popen(["notepad.exe", str(path)])


def build_menu() -> QMenu:
    menu = QMenu()
    menu.setStyleSheet(menu_rules())
    return menu


def _family_icon(name: str) -> QIcon:
    return qt_icon(name, color=TEXT_SECONDARY)


class BrokerSupervisor:
    def __init__(self, config, *, launch, terminate, is_held=is_mutex_held):
        self._config = config
        self._mutex_name = mutex_name(MUTEX_BROKER, config.config_path)
        self._launch = launch
        self._terminate = terminate
        self._is_held = is_held

    def is_running(self) -> bool:
        return self._is_held(self._mutex_name)

    def _broker_argv(self) -> list[str]:
        return [
            NAMER.named_exe(sys.executable, BROKER_ROLE), "-m", "osr2_broker.app",
            "--config", str(self._config.config_path),
        ]

    def start(self) -> None:
        if not self.is_running():
            self._launch(self._broker_argv())
        elif self._running_from() != str(PROJECT_DIR):
            self.restart()

    def _running_from(self) -> str | None:
        try:
            return self._config.broker_checkout_file.read_text(encoding="utf-8")
        except OSError:
            return None

    def stop(self) -> None:
        self._terminate()

    def restart(self) -> None:
        self._terminate()
        self._launch(self._broker_argv())


class BrokerTray(QSystemTrayIcon):
    def __init__(self, name: str = APP_NAME):
        super().__init__()
        self._name = name

        self._menu = build_menu()

        self.status_action = QAction("Broker status: unknown", self._menu)
        self.status_action.setEnabled(False)
        self._menu.addAction(self.status_action)

        self._menu.addSeparator()

        self._start_icon = _family_icon("play")
        self._restart_icon = _family_icon("restart")
        self.start_action = QAction(self._start_icon, "Start Broker", self._menu)
        self._menu.addAction(self.start_action)

        self.pause_action = QAction(_family_icon("pause"), "Pause Broker", self._menu)
        self._menu.addAction(self.pause_action)

        self.log_action = QAction(_family_icon("log"), "Open Broker Log", self._menu)
        self._menu.addAction(self.log_action)

        self._menu.addSeparator()

        self.quit_action = QAction(_family_icon("power"), "Quit", self._menu)
        self._menu.addAction(self.quit_action)

        self.setContextMenu(self._menu)

    def set_status(self, running: bool, osr2: str) -> None:
        status = f"running ({osr2})" if running else "stopped"
        self.status_action.setText(f"Broker status: {status}")
        self.setToolTip(f"{self._name}: {status}")

        self.start_action.setText("Restart Broker" if running else "Start Broker")
        self.start_action.setIcon(self._restart_icon if running else self._start_icon)
        self.pause_action.setEnabled(running)


@dataclass(frozen=True)
class TrayHooks:
    open_file: Callable[[Path], None] = open_in_editor
    peer: peer_watch.PeerWatch | None = None
    updates: production_update.UpdateWatch | None = None
    stand_down: Callable[[], None] = peer_watch.stand_broker_down
    hand_back: Callable[[], None] | None = None
    quit_app: Callable[[], None] = QApplication.quit


class BrokerTrayApp:
    def __init__(self, config, supervisor, tray: BrokerTray, hooks: TrayHooks | None = None):
        hooks = hooks or TrayHooks()
        self._config = config
        self._supervisor = supervisor
        self._tray = tray
        self._open_file = hooks.open_file
        self._peer = hooks.peer
        self._updates = hooks.updates
        self._stand_down = hooks.stand_down
        self._hand_back = hooks.hand_back
        self._quit_app = hooks.quit_app
        self._paused = False
        _taken(config.stop_request_file)

        tray.start_action.triggered.connect(self.start_or_restart)
        tray.pause_action.triggered.connect(self.pause)
        tray.log_action.triggered.connect(self.open_log)

    def tick(self) -> None:
        if _taken(self._config.stop_request_file):
            self._stop_as_asked()
            return
        if not self._paused:
            self._supervisor.start()
        if self._peer is not None:
            self._peer.tick()
        self.refresh()
        if self._updates is not None and not self._paused:
            self._updates.tick()

    def refresh(self) -> None:
        self._tray.set_status(
            running=self._supervisor.is_running(),
            osr2=what_the_osr2_is_doing(self._config),
        )

    def start_or_restart(self) -> None:
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
        log_path = self._config.log_file("broker")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.touch(exist_ok=True)
        self._open_file(log_path)

    def quit(self) -> None:
        if self._hand_back is not None:
            self._hand_back()
        else:
            self._stand_down()
            self._supervisor.stop()
        self._tray.hide()
        self._quit_app()

    def make_way_for_an_update(self, *, start_the_next_tray) -> None:
        self._supervisor.stop()
        start_the_next_tray()
        self._tray.hide()
        self._quit_app()

    def _stop_as_asked(self) -> None:
        self._supervisor.stop()
        self._tray.hide()
        self._quit_app()


def _taken(request: Path) -> bool:
    try:
        request.unlink()
    except FileNotFoundError:
        return False
    return True


class LaunchedBrokers:
    def __init__(self, config, logger, *, popen=None, end_them=None):
        self._config = config
        self._logger = logger
        self._popen = popen or subprocess.Popen
        self._end_them = end_them or (lambda: end_the_processes_running("osr2_broker.app"))
        self._lock = threading.Lock()
        self._running: set[int] = set()
        self._asked_to_end: set[int] = set()

    def launch(self, argv: list[str]) -> None:
        launcher_log = self._config.log_file("broker_service_launcher").open("a", encoding="utf-8")
        broker = self._popen(
            argv,
            cwd=str(PROJECT_DIR),
            stdout=launcher_log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        )
        with self._lock:
            self._running.add(broker.pid)
        self._logger.info("Launched broker (pid %d)", broker.pid)
        start_daemon_thread(target=self._say_how_it_ended, args=(broker,), name="broker-ended")

    def terminate(self) -> None:
        with self._lock:
            self._asked_to_end |= self._running
        self._end_them()
        self._logger.info("Terminated broker")

    def _say_how_it_ended(self, broker: subprocess.Popen) -> None:
        code = broker.wait()
        with self._lock:
            self._running.discard(broker.pid)
            asked = broker.pid in self._asked_to_end
            self._asked_to_end.discard(broker.pid)
        if asked:
            self._logger.info("Broker (pid %d) ended as the tray asked", broker.pid)
        else:
            self._logger.log(logging.INFO if code == 0 else logging.WARNING,
                             "Broker (pid %d) ended: exit code %#x", broker.pid, code)


def _guarded_tick(tray_app: BrokerTrayApp, logger) -> None:
    try:
        tray_app.tick()
    except Exception:
        logger.exception("Watchdog tick failed")


def _name_this_process() -> None:
    NAMER.name_this_process(TRAY_ROLE)


def start_the_tray(config, logger, *, preview_claim: int | None, shown_as: Preview | None,
                   quit_app):
    hands_back = preview_claim is not None
    tray = BrokerTray(window_title(APP_NAME, shown_as))
    tray.setIcon(app_icon(ICON_PATH, shown_as))

    brokers = LaunchedBrokers(config, logger)
    supervisor = BrokerSupervisor(
        config,
        launch=brokers.launch,
        terminate=brokers.terminate,
    )

    updates = None if hands_back else production_update.UpdateWatch(
        PROJECT_DIR, a_good_moment=lambda: mode(config.state_dir) is Osr2Mode.OFF,
        start_again=lambda: tray_app.make_way_for_an_update(
            start_the_next_tray=lambda: production_update.start_again_after(
                os.getpid(), PROJECT_DIR / "launch_broker_tray.vbs")),
        logger=logger)
    tray_app = BrokerTrayApp(
        config, supervisor, tray,
        TrayHooks(
            peer=peer_watch.watch_evolver(config, logger), updates=updates,
            hand_back=(lambda: branch_session.hand_back(config, preview_claim)) if hands_back else None,
            quit_app=quit_app))
    tray.quit_action.triggered.connect(tray_app.quit)
    hand_back_timer = branch_session.hand_back_later(tray_app.quit) if hands_back else None
    return tray, tray_app, hand_back_timer


def shown_as(*, preview: bool) -> Preview | None:
    return preview_of(PROJECT_DIR) if preview else None


def open_the_loading_screen(shown_as: Preview | None):
    from shared_ui.loading_process import LoadingProcess  # noqa: PLC0415

    return LoadingProcess.open(
        caption="Broker Loading", wordmark=APP_NAME, icon=ICON_PATH, preview=shown_as, steps=STEPS,
        cancel_hint="Press Esc to cancel opening Broker",
        app_id=taskbar_identity(APP_USER_MODEL_ID, shown_as))


def main(argv: list[str] | None = None) -> int:
    preview = branch_session.take_the_flag()
    if not preview:
        _name_this_process()

    config = load_config(preparse_config_path(argv))
    logger = configure_logging("osr2_broker.tray", config.log_file("broker_tray"))
    install_exception_logging(logger)

    if preview:
        _mutex_handle = branch_session.take_the_tray_over(
            end_the_other_trays=branch_session.end_the_other_trays)
    else:
        _mutex_handle = try_acquire_mutex(MUTEX_TRAY)
    if _mutex_handle is None:
        logger.info("Another tray is already running; exiting")
        return 0

    peer_watch.clear_broker_stand_down()

    marked = shown_as(preview=preview)
    claim_taskbar_identity(marked)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    loading = Loading.at_the_click(app, logger, lambda: open_the_loading_screen(marked))
    try:
        for step, _weight in STEPS:
            loading.say(step)
    except LoadingCanceled:
        return 0

    tray, tray_app, _hand_back_timer = start_the_tray(
        config, logger, preview_claim=_mutex_handle if preview else None, shown_as=marked,
        quit_app=app.quit)

    timer = QTimer()
    timer.setInterval(WATCHDOG_INTERVAL_MS)
    timer.timeout.connect(lambda: _guarded_tick(tray_app, logger))
    timer.start()

    logger.info("Tray started (pid %d)", os.getpid())
    tray.show()
    loading.done()
    tray_app.tick()
    try:
        return app.exec()
    finally:
        logger.info("Tray exiting (pid %d)", os.getpid())


if __name__ == "__main__":
    raise SystemExit(main())
