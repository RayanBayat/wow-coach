"""Starts the desktop app: builds the coach's brain, the bridge and the window, then runs Qt.

Nothing here is needed by the rest of wow-coach: ``cli.py`` and ``launcher.py`` import this
module only when the player runs the desktop app, so people without the ``desktop`` extra
never load Qt.
"""

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from PySide6.QtCore import QProcess
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from wow_coach.app.run import build_core
from wow_coach.app.watcher import Watcher
from wow_coach.config import config_path
from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.first_run import ask_with_dialog, find_game_folder_or_ask
from wow_coach.desktop.icons import app_icon
from wow_coach.desktop.main_window import APP_TITLE, MainWindow
from wow_coach.desktop.single_instance import SHOW_MESSAGE, TOGGLE_OVERLAY_MESSAGE, SingleInstance
from wow_coach.desktop.theme import apply_theme
from wow_coach.desktop.tray import AppTray, open_settings
from wow_coach.errors import GameFolderNotFound
from wow_coach.gamedir import resolve_game_folder

LAUNCHER_MODULE = "wow_coach.desktop.launcher"


def platform_arguments(environ: Mapping[str, str], system: str = sys.platform) -> list[str]:
    """Extra Qt arguments for this computer (usually none).

    On a Linux desktop that uses Wayland, apps are not allowed to keep their own window on top
    of other windows, and "Keep on top of the game" needs that. The same desktop also runs old
    X11 apps (through XWayland), and those may stay on top. So when XWayland is there, the app
    runs as an X11 app. Qt's X11 plugin needs extra system libraries that some desktops lack,
    so the answer is ``xcb;wayland``: Qt tries X11 first and falls back to Wayland (the window
    then just cannot stay on top). Setting ``QT_QPA_PLATFORM`` yourself always wins.
    """
    if not system.startswith("linux") or environ.get("QT_QPA_PLATFORM"):
        return []
    on_wayland = environ.get("XDG_SESSION_TYPE") == "wayland" or bool(
        environ.get("WAYLAND_DISPLAY")
    )
    if on_wayland and environ.get("DISPLAY"):
        return ["-platform", "xcb;wayland"]
    return []


def relaunch_command(
    wow_dir_flag: Path | None,
    *,
    executable: str | None = None,
    platform: str = sys.platform,
) -> tuple[str, list[str]]:
    """The program and arguments that start this app again (for "Restart WoW Coach").

    It runs the launcher module with the running Python, so it needs no script file and works
    the same however the app was started. It never adds ``--hidden``: the player just pressed
    a button, so they want to see the window. On Windows ``pythonw.exe`` is used when it
    exists, so no console window appears.
    """
    program = sys.executable if executable is None else executable
    if platform == "win32":
        windowless = Path(program).with_name("pythonw.exe")
        if windowless.is_file():
            program = str(windowless)
    arguments = ["-m", LAUNCHER_MODULE]
    if wow_dir_flag is not None:
        arguments += ["--wow-dir", str(wow_dir_flag)]
    return program, arguments


def run_desktop(
    *,
    wow_dir_flag: Path | None = None,
    environ: Mapping[str, str] | None = None,
    argv: Sequence[str] | None = None,
    start_hidden: bool = False,
    toggle_overlay: bool = False,
) -> int:
    """Open the desktop app and run until the player quits it. Returns the exit code.

    Args:
        wow_dir_flag: The ``--wow-dir`` option, or None. The game folder is looked up here, so
            when it cannot be found the player gets a window that helps (see ``first_run``).
        environ: Environment variables (default: the real ones).
        argv: The program name and Qt arguments (default: this program's name).
        start_hidden: Start in the tray without showing the window (used at login). Ignored
            when the computer has no tray, because the window could not be found again.
        toggle_overlay: The ``--toggle-overlay`` option. If a copy is already running, it is
            told to show or hide its overlay. If not, this copy starts in the tray and shows
            the overlay at once.
    """
    environ = os.environ if environ is None else environ
    arguments = list(argv) if argv is not None else sys.argv[:1]
    app = QApplication([*arguments, *platform_arguments(environ)])
    app.setApplicationName(APP_TITLE)
    app.setDesktopFileName("wow-coach")
    app.setWindowIcon(app_icon())
    # Closing the window hides it to the tray; the window itself decides when to quit.
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)

    # Two copies would both answer the same in-game question. If one is already running,
    # tell it to show its window (or its overlay) and leave.
    instance = SingleInstance(environ=environ)
    message = TOGGLE_OVERLAY_MESSAGE if toggle_overlay else SHOW_MESSAGE
    if not instance.claim(message):
        return 0
    try:
        return _run_as_the_only_copy(
            app, instance, wow_dir_flag, environ, start_hidden or toggle_overlay
        )
    finally:
        instance.close()


def _run_as_the_only_copy(
    app: QApplication,
    instance: SingleInstance,
    wow_dir_flag: Path | None,
    environ: Mapping[str, str],
    start_hidden: bool,
) -> int:
    config_file = config_path(environ=environ)
    tray = AppTray(open_settings())
    lookups_failed: list[bool] = []

    def find() -> Path:
        try:
            return resolve_game_folder(wow_dir_flag, environ=environ, config_file=config_file).path
        except GameFolderNotFound:
            lookups_failed.append(True)
            raise

    wow_dir = find_game_folder_or_ask(
        find,
        start_hidden=start_hidden,
        make_tray=lambda: tray,
        ask=lambda finder: ask_with_dialog(finder, config_file),
    )
    if wow_dir is None:
        return 0  # the player quit instead of choosing a folder

    # Show the tray icon before reading the game folder: on a sleeping hard disk that can take
    # a while, and without the icon the app would look as if it did not start.
    tray.show()
    app.processEvents()
    # If the player had to help with the folder, they are here and want to see the window.
    hidden = start_hidden and not lookups_failed

    core = build_core(wow_dir, environ)
    watcher = Watcher(core, wow_dir)
    bridge = CoreBridge(core)
    window = MainWindow(bridge, tray=tray, game_dir=wow_dir)
    instance.show_requested.connect(window.bring_to_front)

    def restart() -> None:
        """Start a fresh copy and quit this one. The lock is released first, or it would exit."""
        instance.close()
        program, relaunch_arguments = relaunch_command(wow_dir_flag)
        QProcess.startDetached(program, relaunch_arguments)
        window.quit_app()

    window.restart_requested.connect(restart)

    def on_scheme_changed() -> None:
        apply_theme(app)
        window.on_theme_changed()

    QGuiApplication.styleHints().colorSchemeChanged.connect(on_scheme_changed)
    watcher.start()
    bridge.start()
    if not (hidden and tray.available):
        window.show()
    try:
        return app.exec()
    finally:
        tray.hide()
        bridge.stop()
        watcher.stop()
