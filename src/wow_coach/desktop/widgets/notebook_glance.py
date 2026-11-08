"""The "At a glance" card: the important stuff of the Notebook in one small parchment card.

It is meant to sit beside the chat (narrow, about 300 px) and also at the top of the Notebook
page (``compact=False``: full width, no "Open the notebook" button, since the player is
already there). It never reads files: whoever owns it hands over a ``NotebookSummary``.

Security: the summary comes from AI-written notes, so every piece is a plain-text label.
"""

from typing import Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from wow_coach.desktop.forms import make_button, make_label
from wow_coach.desktop.notebook_summary import NotebookSummary
from wow_coach.desktop.theme import RADIUS, SPACE, SPACE_SMALL, Colors, current_colors

TITLE: Final = "At a glance"
EMPTY: Final = "Your coach hasn't saved notes about this character yet."
OPEN_TEXT: Final = "Open the notebook"
NARROW_MIN: Final = 260
NARROW_MAX: Final = 320


def _style(c: Colors) -> str:
    """Parchment with dark ink, like the coach's answers; small gold-brown field names."""
    return f"""
QFrame#glanceCard {{
    background: {c.parchment}; border: 1px solid {c.parchment_edge}; border-radius: {RADIUS}px;
}}
QFrame#glanceCard QLabel {{ color: {c.on_parchment}; background: transparent; border: none; }}
QFrame#glanceCard QLabel[role="field"] {{
    color: {c.parchment_muted}; font-size: 8.5pt; font-weight: 700;
}}
QFrame#glanceCard QLabel[role="empty"] {{ color: {c.parchment_muted}; font-style: italic; }}
QFrame#glanceCard QPushButton {{
    background: transparent; border: none; color: {c.parchment_muted};
    text-decoration: underline; text-align: left; padding: 2px 0px;
}}
QFrame#glanceCard QPushButton:hover {{ color: {c.on_parchment}; }}
"""


def _plain(text: str, role: str | None = None) -> QLabel:
    """A word-wrapped plain-text label that may shrink below its text's width."""
    label = make_label(text, role)
    label.setMinimumWidth(1)  # lets a long unbroken word wrap instead of widening the card
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    return label


class NotebookGlance(QFrame):
    """A small card with the notebook's goal, next steps, place, choices and latest progress."""

    # The player clicked "Open the notebook" (the window connects it to the Notebook page).
    open_requested = Signal()

    def __init__(self, parent: QWidget | None = None, *, compact: bool = True) -> None:
        """Create the card.

        Args:
            parent: The owning widget.
            compact: True for the narrow side card with the "Open the notebook" link; False
                for a full-width card without it (used on the Notebook page itself).
        """
        super().__init__(parent)
        self.setObjectName("glanceCard")
        self.setStyleSheet(_style(current_colors()))
        if compact:
            self.setMinimumWidth(NARROW_MIN)
            self.setMaximumWidth(NARROW_MAX)
        # Never grow taller than the text: beside a tall chat the card stays at its top.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(SPACE, SPACE, SPACE, SPACE)
        self._column.setSpacing(SPACE_SMALL)
        self._column.addWidget(_plain(TITLE, "subtitle"))
        self._content = QWidget()  # replaced on every show_summary
        self._column.addWidget(self._content)
        self.open_button = make_button(OPEN_TEXT, "ghost", "Show everything the coach saved.")
        self.open_button.clicked.connect(self.open_requested)
        self.open_button.setVisible(compact)
        self._column.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._column.addStretch(1)  # spare height goes below the text, not between the lines
        self.show_summary(NotebookSummary())

    def show_summary(self, summary: NotebookSummary) -> None:
        """Show ``summary``; an empty one shows the friendly "nothing saved yet" text."""
        fresh = QWidget()
        layout = QVBoxLayout(fresh)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SMALL)
        if summary.is_empty:
            layout.addWidget(_plain(EMPTY, "empty"))
        else:
            self._fill(layout, summary)
        self._column.replaceWidget(self._content, fresh)
        self._content.setParent(None)  # leave the card at once; Qt frees it when idle
        self._content.deleteLater()
        self._content = fresh

    def _fill(self, layout: QVBoxLayout, summary: NotebookSummary) -> None:
        """Add one small field name plus its text for each part that has something."""
        if summary.goal:
            self._add(layout, "Goal", summary.goal)
        if summary.next_steps:
            numbered = "\n".join(f"{n}. {step}" for n, step in enumerate(summary.next_steps, 1))
            self._add(layout, "Next steps", numbered)
        if summary.where:
            self._add(layout, "Where you are", summary.where)
        if summary.choices:
            self._add(layout, "Choices", "\n".join(summary.choices))
        if summary.latest:
            self._add(layout, "Latest progress", summary.latest)
        if summary.about_you:
            self._add(layout, "About you", summary.about_you)

    @staticmethod
    def _add(layout: QVBoxLayout, field: str, text: str) -> None:
        if layout.count():
            layout.addSpacing(SPACE_SMALL)  # a little air between one field and the next
        layout.addWidget(_plain(field.upper(), "field"))
        layout.addWidget(_plain(text))
