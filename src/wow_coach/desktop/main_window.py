"""The main window: a sidebar on the left, one page at a time on the right.

The window itself holds no coaching logic. It builds the sidebar from the pages' titles,
switches pages, and hands every new state and event from the bridge to all pages.
"""

from collections.abc import Mapping, Sequence
from typing import Final

from PySide6.QtWidgets import (
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
from wow_coach.desktop.pages import build_pages
from wow_coach.desktop.pages.base import Page
from wow_coach.desktop.state import StateView
from wow_coach.desktop.theme import SIDEBAR_WIDTH, SPACE, SPACE_SMALL

APP_TITLE: Final = "WoW Coach"
DEFAULT_SIZE: Final = (1040, 720)
MINIMUM_SIZE: Final = (760, 540)


class MainWindow(QMainWindow):
    """The app's one main window."""

    def __init__(self, bridge: CoreBridge, pages: Sequence[Page] | None = None) -> None:
        """Build the window.

        Args:
            bridge: The bridge to the coach's brain.
            pages: The pages to show (default: every page, from ``build_pages``).
        """
        super().__init__()
        self.bridge = bridge
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
        if self.pages:
            self.show_page(self.pages[0].name)

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

    def current_page(self) -> Page | None:
        """The page on screen now."""
        widget = self._stack.currentWidget()
        return widget if isinstance(widget, Page) else None

    def on_theme_changed(self) -> None:
        """Tell every page that the computer switched between light and dark mode."""
        for page in self.pages:
            page.on_theme_changed()

    def _show_state(self, state: object) -> None:
        if isinstance(state, StateView):
            for page in self.pages:
                page.show_state(state)

    def _on_event(self, kind: str, data: object) -> None:
        details: Mapping[str, object] = data if isinstance(data, Mapping) else {}
        for page in self.pages:
            page.on_event(kind, details)
