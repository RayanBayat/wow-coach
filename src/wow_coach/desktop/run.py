"""Starts the desktop app: builds the coach's brain, the bridge and the window, then runs Qt.

Nothing here is needed by the rest of wow-coach: ``cli.py`` imports this module only when the
player runs the desktop app, so people without the ``desktop`` extra never load Qt.
"""

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from wow_coach.app.run import build_core
from wow_coach.app.watcher import Watcher
from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.main_window import APP_TITLE, MainWindow
from wow_coach.desktop.theme import apply_theme


def platform_arguments(environ: Mapping[str, str], system: str = sys.platform) -> list[str]:
    """Extra Qt arguments for this computer (usually none).

    On a Linux desktop that uses Wayland, apps are not allowed to keep their own window on top
    of other windows, and "Keep on top of the game" needs that. The same desktop also runs old
    X11 apps (through XWayland), and those may stay on top. So when XWayland is there, the app
    runs as an X11 app. Setting ``QT_QPA_PLATFORM`` yourself always wins.
    """
    if not system.startswith("linux") or environ.get("QT_QPA_PLATFORM"):
        return []
    on_wayland = environ.get("XDG_SESSION_TYPE") == "wayland" or bool(
        environ.get("WAYLAND_DISPLAY")
    )
    if on_wayland and environ.get("DISPLAY"):
        return ["-platform", "xcb"]
    return []


def run_desktop(
    *,
    wow_dir: Path,
    environ: Mapping[str, str] | None = None,
    argv: Sequence[str] | None = None,
) -> int:
    """Open the desktop app and run until the player quits it. Returns the exit code.

    Args:
        wow_dir: The game folder (the one that contains ``WTF/``).
        environ: Environment variables (default: the real ones).
        argv: The program name and Qt arguments (default: this program's name).
    """
    environ = os.environ if environ is None else environ
    arguments = list(argv) if argv is not None else sys.argv[:1]
    app = QApplication([*arguments, *platform_arguments(environ)])
    app.setApplicationName(APP_TITLE)
    app.setDesktopFileName("wow-coach")
    apply_theme(app)

    core = build_core(wow_dir, environ)
    watcher = Watcher(core, wow_dir)
    bridge = CoreBridge(core)
    window = MainWindow(bridge)

    def on_scheme_changed() -> None:
        apply_theme(app)
        window.on_theme_changed()

    QGuiApplication.styleHints().colorSchemeChanged.connect(on_scheme_changed)
    watcher.start()
    bridge.start()
    window.show()
    try:
        return app.exec()
    finally:
        bridge.stop()
        watcher.stop()
