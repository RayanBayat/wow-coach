"""The icon in the system tray (the row of small icons next to the clock).

Closing the window only hides it, so the coach keeps answering questions from the game. The
tray icon is how the player gets the window back, or quits for real.
"""

from typing import Final

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from wow_coach.desktop.icons import app_icon

TRAY_MESSAGE: Final = (
    "WoW Coach keeps running here so it can answer questions from the game. Quit from this menu."
)
_MESSAGE_SHOWN_KEY: Final = "tray/hint_shown"
_MESSAGE_MS: Final = 8000


def open_settings() -> QSettings:
    """The app's small saved settings (for example "the tray hint was shown")."""
    return QSettings("wow-coach", "desktop")


class AppTray(QObject):
    """The tray icon with its menu. Tells the window what the player chose."""

    # The player wants the window (menu entry or click on the icon).
    open_requested = Signal()
    # The player chose Quit.
    quit_requested = Signal()

    def __init__(
        self,
        settings: QSettings,
        *,
        available: bool | None = None,
        icon: QIcon | None = None,
    ) -> None:
        """Create the tray icon.

        Args:
            settings: Where the "hint was shown" note is kept.
            available: Whether this computer has a tray (default: ask Qt).
            icon: The icon to show (default: the app icon).
        """
        super().__init__()
        self._settings = settings
        self.available = QSystemTrayIcon.isSystemTrayAvailable() if available is None else available
        self.last_message = ""  # the last hint shown (tests read it)
        self._tray: QSystemTrayIcon | None = None
        self._menu = QMenu()
        self._build_menu()
        if self.available:
            self._tray = QSystemTrayIcon(icon or app_icon(), self)
            self._tray.setToolTip("WoW Coach")
            self._tray.setContextMenu(self._menu)
            self._tray.activated.connect(self._on_activated)

    def _build_menu(self) -> None:
        open_action = QAction("Open WoW Coach", self._menu)
        open_action.setToolTip("Show the WoW Coach window")
        open_action.triggered.connect(self.open_requested)
        quit_action = QAction("Quit", self._menu)
        quit_action.setToolTip("Stop WoW Coach completely")
        quit_action.triggered.connect(self.quit_requested)
        self._menu.addAction(open_action)
        self._menu.addSeparator()
        self._menu.addAction(quit_action)

    @property
    def menu(self) -> QMenu:
        """The tray menu."""
        return self._menu

    def show(self) -> None:
        """Put the icon in the tray (does nothing when there is no tray)."""
        if self._tray is not None:
            self._tray.show()

    def hide(self) -> None:
        """Take the icon out of the tray (the app is closing)."""
        if self._tray is not None:
            self._tray.hide()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # A single or double click on the icon opens the window; right-click shows the menu.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_requested.emit()

    def show_message(self, text: str) -> None:
        """Pop up a short message next to the icon (does nothing when there is no tray)."""
        if self._tray is None:
            return
        self.last_message = text
        self._tray.showMessage(
            "WoW Coach", text, QSystemTrayIcon.MessageIcon.Information, _MESSAGE_MS
        )

    def hint_once(self) -> None:
        """Tell the player, the first time only, that the app went to the tray."""
        if self._tray is None or self._settings.value(_MESSAGE_SHOWN_KEY, False, type=bool):
            return
        self._settings.setValue(_MESSAGE_SHOWN_KEY, True)
        self._settings.sync()
        self.show_message(TRAY_MESSAGE)
