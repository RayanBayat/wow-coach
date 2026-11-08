"""The ChatGPT page: Your ChatGPT sign-in.

Placeholder from the skeleton; the real page replaces this file.
"""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.pages.base import Page
from wow_coach.desktop.theme import SPACE_LARGE


class ChatGPTPage(Page):
    """Your ChatGPT sign-in."""

    name = "chatgpt"
    title = "ChatGPT"

    def __init__(self, bridge: CoreBridge, parent: QWidget | None = None) -> None:
        super().__init__(bridge, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_LARGE, SPACE_LARGE, SPACE_LARGE, SPACE_LARGE)
        heading = QLabel(self.title)
        heading.setProperty("role", "title")
        layout.addWidget(heading)
        layout.addStretch(1)
