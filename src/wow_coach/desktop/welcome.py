"""The one-time welcome message after the first ChatGPT sign-in.

OpenAI's program rules ask apps to tell the player, once, that the app uses their ChatGPT
plan. The words below follow OpenAI's guidelines, so keep them as they are.

Only the "Got it" button remembers that the player has read it. Closing the dialog some
other way (Esc, the window's close button) does not, so the message comes back next start.
"""

from typing import Final

from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QWidget

from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.forms import USAGE_URL, link_button, make_button, make_label
from wow_coach.desktop.theme import SPACE, SPACE_LARGE

WELCOME_TITLE: Final = "You're using your ChatGPT plan"
WELCOME_TEXT: Final = (
    "Eligible usage in this app uses your ChatGPT plan. Manage usage in your ChatGPT settings."
)
WELCOME_EXTRA: Final = (
    "WoW Coach has no charges of its own. You can sign out any time on the ChatGPT page."
)


class WelcomeDialog(QDialog):
    """A small modal window: what "using your plan" means, and a "Got it" button."""

    def __init__(self, bridge: CoreBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self.setWindowTitle(WELCOME_TITLE)
        self.setModal(True)
        self.setMinimumWidth(420)

        column = QVBoxLayout(self)
        column.setContentsMargins(SPACE_LARGE, SPACE_LARGE, SPACE_LARGE, SPACE_LARGE)
        column.setSpacing(SPACE)
        column.addWidget(make_label(WELCOME_TITLE, "title"))
        column.addWidget(make_label(WELCOME_TEXT))
        column.addWidget(make_label(WELCOME_EXTRA, "muted"))

        self.got_it = make_button(
            "Got it", "primary", "Close this message. You won't see it again."
        )
        self.got_it.setDefault(True)  # Enter presses it
        self.got_it.clicked.connect(self._confirm)
        buttons = QHBoxLayout()
        buttons.addWidget(
            link_button(
                "Manage usage",
                USAGE_URL,
                "Open your ChatGPT usage settings in the browser.",
            )
        )
        buttons.addStretch(1)
        buttons.addWidget(self.got_it)
        column.addLayout(buttons)

    def _confirm(self) -> None:
        """The "Got it" button: remember that the message was read, then close."""
        self._bridge.dismiss_welcome()
        self.accept()
