"""What every page of the desktop app has in common.

A page is one screen on the right of the sidebar (the Coach chat, Settings...). Each page:

* gets the ``CoreBridge`` and does every action through it;
* redraws itself in ``show_state`` (called after every change, so keep it quick);
* may react to single live events in ``on_event`` (for example "an answer arrived");
* may restyle custom-painted parts in ``on_theme_changed`` (light or dark mode changed);
* may ask the window to show another page by emitting ``navigate`` with that page's name
  (for example a "Sign in" button on the Coach page emits ``navigate("chatgpt")``).
"""

from collections.abc import Mapping
from typing import ClassVar

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.state import StateView


class Page(QWidget):
    """The base of every page."""

    name: ClassVar[str] = ""  # a short id, for example "coach"
    title: ClassVar[str] = ""  # the label in the sidebar, for example "Coach"

    # Emit with a page's name to switch to that page.
    navigate = Signal(str)

    def __init__(self, bridge: CoreBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bridge = bridge
        self.setObjectName("page")  # the stylesheet gives pages the window background

    def show_state(self, state: StateView) -> None:
        """Redraw from the newest state. The default does nothing."""

    def on_event(self, kind: str, data: Mapping[str, object]) -> None:
        """React to one live event from the core. The default does nothing."""

    def on_theme_changed(self) -> None:
        """The computer switched between light and dark mode. The default does nothing."""
