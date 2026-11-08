"""The main window: a sidebar on the left, one page at a time on the right.

The window itself holds no coaching logic. It builds the sidebar from the pages' titles,
switches pages, and hands every new state and event from the bridge to all pages.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.icons import ICON_NAMES, app_icon, icon
from wow_coach.desktop.pages import build_pages
from wow_coach.desktop.pages.base import Page
from wow_coach.desktop.pages.setup import SetupPage
from wow_coach.desktop.state import StateView
from wow_coach.desktop.theme import SIDEBAR_WIDTH, SPACE, SPACE_SMALL, current_colors
from wow_coach.desktop.tray import AppTray

APP_TITLE: Final = "WoW Coach"
DEFAULT_SIZE: Final = (1040, 720)
MINIMUM_SIZE: Final = (760, 540)
NAV_ICON_SIZE: Final = 20


class MainWindow(QMainWindow):
    """The app's one main window."""

    # The player pressed "Restart WoW Coach" (on the Setup page). ``run.py`` does the restart.
    restart_requested = Signal()

    def __init__(
        self,
        bridge: CoreBridge,
        pages: Sequence[Page] | None = None,
        *,
        tray: AppTray | None = None,
        game_dir: Path | None = None,
    ) -> None:
        """Build the window.

        Args:
            bridge: The bridge to the coach's brain.
            pages: The pages to show (default: every page, from ``build_pages``).
            tray: The tray icon. With a working tray, closing the window hides it; without
                one, closing the window quits the app.
            game_dir: The game folder the app is watching (the Setup page shows it).
        """
        super().__init__()
        self.bridge = bridge
        self._tray = tray
        self._really_quitting = False
        self.setWindowIcon(app_icon())
        self.pages: list[Page] = list(pages) if pages is not None else build_pages(bridge)
        self.setWindowTitle(APP_TITLE)
        self.resize(*DEFAULT_SIZE)
        self.setMinimumSize(*MINIMUM_SIZE)

        self._stack = QStackedWidget()
        self._nav = QButtonGroup(self)
        self._nav.setExclusive(True)
        self._nav_buttons: dict[str, QPushButton] = {}

        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._build_sidebar())
        row.addWidget(self._stack, 1)
        self.setCentralWidget(central)

        for page in self.pages:
            self._stack.addWidget(page)
            page.navigate.connect(self.show_page)
        for page in self.pages:
            if isinstance(page, SetupPage) and game_dir is not None:
                page.set_game_dir(game_dir)
        for page in self.pages:
            if isinstance(page, SetupPage):
                page.restart_requested.connect(self.restart_requested)
        if self.pages:
            self.show_page(self.pages[0].name)
        self._paint_nav_icons()
        if tray is not None:
            tray.open_requested.connect(self.bring_to_front)
            tray.quit_requested.connect(self.quit_app)

        bridge.state_changed.connect(self._show_state)
        bridge.event_arrived.connect(self._on_event)

    # ---- building -----------------------------------------------------------------------

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        column = QVBoxLayout(sidebar)
        column.setContentsMargins(SPACE, SPACE + SPACE_SMALL, SPACE, SPACE)
        column.setSpacing(SPACE_SMALL)

        name = QLabel(APP_TITLE)
        name.setProperty("role", "subtitle")
        column.addWidget(name)
        column.addSpacing(SPACE)

        for page in self.pages:
            button = QPushButton(page.title)
            button.setProperty("kind", "nav")
            button.setCheckable(True)
            button.setIconSize(QSize(NAV_ICON_SIZE, NAV_ICON_SIZE))
            button.toggled.connect(self._paint_nav_icons)
            button.clicked.connect(lambda _checked=False, wanted=page.name: self.show_page(wanted))
            self._nav.addButton(button)
            self._nav_buttons[page.name] = button
            column.addWidget(button)
        column.addStretch(1)
        return sidebar

    # ---- using it -----------------------------------------------------------------------

    def show_page(self, name: str) -> None:
        """Switch to the page with this name (unknown names are ignored)."""
        for page in self.pages:
            if page.name == name:
                self._stack.setCurrentWidget(page)
                self._nav_buttons[name].setChecked(True)
                return

    def bring_to_front(self) -> None:
        """Show the window, raise it above other windows and give it the keyboard."""
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        """Really quit (the tray's Quit), instead of hiding to the tray."""
        self._really_quitting = True
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt's name
        """Closing the window hides it to the tray, so the coach keeps answering the game.

        Without a tray (some Linux desktops have none) a hidden window could never be
        found again, so closing quits the app.
        """
        if self._tray is not None and self._tray.available and not self._really_quitting:
            event.ignore()
            self.hide()
            self._tray.hint_once()
            return
        self._really_quitting = True
        event.accept()
        QApplication.quit()

    def current_page(self) -> Page | None:
        """The page on screen now."""
        widget = self._stack.currentWidget()
        return widget if isinstance(widget, Page) else None

    def on_theme_changed(self) -> None:
        """Tell every page that the computer switched between light and dark mode."""
        self._paint_nav_icons()
        for page in self.pages:
            page.on_theme_changed()

    def _paint_nav_icons(self, _checked: bool = False) -> None:
        """Give each sidebar button its icon: gold when selected, muted otherwise."""
        colors = current_colors()
        for name, button in self._nav_buttons.items():
            if name not in ICON_NAMES:
                continue  # a page without a drawn icon just shows its title
            color = colors.accent if button.isChecked() else colors.muted
            button.setIcon(icon(name, color, NAV_ICON_SIZE))

    def _show_state(self, state: object) -> None:
        if isinstance(state, StateView):
            for page in self.pages:
                page.show_state(state)

    def _on_event(self, kind: str, data: object) -> None:
        details: Mapping[str, object] = data if isinstance(data, Mapping) else {}
        for page in self.pages:
            page.on_event(kind, details)
