"""The scrolling conversation.

New messages fade in. The view glides down to a new message, unless the player has scrolled
up to read: then it stays put and shows a small "New answer ↓" button instead.
"""

import time

from PySide6.QtCore import QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from wow_coach.desktop.state import AnswerView
from wow_coach.desktop.theme import SPACE, SPACE_SMALL
from wow_coach.desktop.widgets.animation import fade_in, glide
from wow_coach.desktop.widgets.bubbles import (
    CoachBubble,
    ErrorNotice,
    MessageRow,
    Notice,
    PlayerBubble,
    TypingBubble,
)

FOLLOW_SECONDS = 0.5  # how long after adding a message the view keeps following the growth
MIN_CHAT_WIDTH = 240
NEAR_BOTTOM_PIXELS = 40  # "at the bottom" means within this many pixels of it


class _Content(QWidget):
    """The widget inside the scroll area that holds all messages.

    Qt would add up the *smallest* height of every message (each squeezed into a narrow
    column), which makes the chat far taller than it needs to be. The real height comes from
    the layout's height-for-width, so this widget says it has no minimum height.
    """

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt's method name
        """No minimum height; a small minimum width."""
        return QSize(MIN_CHAT_WIDTH, 0)


class ChatView(QScrollArea):
    """A list of messages, oldest at the top."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        content = _Content()
        self._column = QVBoxLayout(content)
        self._column.setContentsMargins(SPACE_SMALL, SPACE, SPACE_SMALL, SPACE)
        self._column.setSpacing(SPACE)
        self._rows: list[MessageRow] = []
        self._coach_bubbles: list[CoachBubble] = []
        # Layout order: all message rows, then the typing dots, then a spring.
        self._typing_row = MessageRow(TypingBubble(), on_right=False)
        self._typing_row.hide()
        self._column.addWidget(self._typing_row)
        self._column.addStretch(1)
        self.setWidget(content)

        self._glide: QPropertyAnimation | None = None
        self._follow_until = 0.0
        self._follow_animated = True
        self.verticalScrollBar().rangeChanged.connect(self._range_changed)
        self._new_pill = QPushButton("New answer ↓", self)
        self._new_pill.setProperty("kind", "primary")
        self._new_pill.setToolTip("Jump down to the newest answer.")
        self._new_pill.clicked.connect(self.scroll_to_newest)
        self._new_pill.hide()
        self.verticalScrollBar().valueChanged.connect(self._hide_pill_at_bottom)

    # ---- reading ------------------------------------------------------------------------

    def message_count(self) -> int:
        """How many messages are in the chat."""
        return len(self._rows)

    def texts(self) -> list[str]:
        """The visible words of every message, oldest first (used by tests)."""
        return [_all_text(row.content) for row in self._rows]

    @property
    def pill_visible(self) -> bool:
        """True when the "New answer ↓" button is shown."""
        return not self._new_pill.isHidden()

    @property
    def typing_visible(self) -> bool:
        """True while the typing dots are shown."""
        return not self._typing_row.isHidden()

    # ---- adding messages ----------------------------------------------------------------

    def add_player(self, text: str, tag: str | None = None, *, animate: bool = True) -> MessageRow:
        """Add a question from the player (on the right)."""
        return self._add(PlayerBubble(text, tag), on_right=True, animate=animate)

    def add_answer(
        self,
        answer: AnswerView,
        *,
        now: float,
        note: str = "",
        written_to_game: bool = False,
        animate: bool = True,
    ) -> MessageRow:
        """Add an answer from the coach (on the left)."""
        bubble = CoachBubble(answer, note=note, written_to_game=written_to_game, now=now)
        self._coach_bubbles.append(bubble)
        return self._add(bubble, on_right=False, animate=animate)

    def add_notice(self, text: str, *, animate: bool = True) -> MessageRow:
        """Add a quiet line ("Waiting for fresh game data…")."""
        return self._add(Notice(text), on_right=False, animate=animate, share=1.0)

    def add_error(self, message: str, *, is_limit: bool = False) -> MessageRow:
        """Add a plain-words problem; a usage limit also gets a "Manage usage" button."""
        return self._add(ErrorNotice(message, is_limit=is_limit), on_right=False, animate=True)

    def remove(self, row: MessageRow) -> None:
        """Take a message out again (for example a finished "waiting" notice)."""
        if row in self._rows:
            self._rows.remove(row)
            row.hide()
            row.deleteLater()

    def clear(self) -> None:
        """Remove every message (another character was chosen)."""
        for row in self._rows:
            row.hide()
            row.deleteLater()
        self._rows.clear()
        self._coach_bubbles.clear()
        self._new_pill.hide()

    def set_typing(self, on: bool) -> None:
        """Show or hide the coach's typing dots, and keep them in view."""
        if on == self.typing_visible:
            return
        stick = self._at_bottom()
        self._typing_row.setVisible(on)
        if on and stick:
            self._scroll_soon()

    def refresh_times(self, now: float) -> None:
        """Update "5 min ago" in every answer."""
        for bubble in self._coach_bubbles:
            bubble.update_time(now)

    # ---- scrolling ----------------------------------------------------------------------

    def scroll_to_newest(self) -> None:
        """Glide to the bottom."""
        self._new_pill.hide()
        bar = self.verticalScrollBar()
        self._glide = glide(bar, bar.maximum())

    def jump_to_newest(self) -> None:
        """Go to the bottom at once, without gliding (when a chat is first filled)."""
        self._jump()
        self._scroll_soon(animated=False)

    def _jump(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _add(
        self, content: QWidget, *, on_right: bool, animate: bool, share: float = 0.7
    ) -> MessageRow:
        stick = self._at_bottom() or not self._rows
        row = MessageRow(content, on_right=on_right, share=share)
        self._column.insertWidget(len(self._rows), row)
        self._rows.append(row)
        if animate:
            fade_in(row)
            if stick or on_right:
                self._scroll_soon()  # the player's own question always brings us down
            else:
                self._new_pill.show()
                self._place_pill()
        else:
            self._scroll_soon(animated=False)
        return row

    def _scroll_soon(self, *, animated: bool = True) -> None:
        """Go to the bottom once the layout has measured the new message.

        The layout measures a moment *after* a message is added, and the scroll range grows
        then. So for a short while, every growth of the range moves the view to the new bottom.
        """
        self._follow_until = time.monotonic() + FOLLOW_SECONDS
        self._follow_animated = animated
        QTimer.singleShot(0, self._follow)

    def _follow(self) -> None:
        if self._follow_animated:
            self.scroll_to_newest()
        else:
            self._jump()

    def _range_changed(self) -> None:
        """The chat got taller: if we are following new messages, follow this growth too."""
        if time.monotonic() < self._follow_until:
            self._follow()

    def _at_bottom(self) -> bool:
        bar = self.verticalScrollBar()
        return bar.maximum() - bar.value() <= NEAR_BOTTOM_PIXELS

    def _hide_pill_at_bottom(self) -> None:
        if self._at_bottom():
            self._new_pill.hide()

    def _place_pill(self) -> None:
        self._new_pill.adjustSize()
        x = (self.width() - self._new_pill.width()) // 2
        y = self.height() - self._new_pill.height() - SPACE
        self._new_pill.move(x, y)
        self._new_pill.raise_()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt's method name
        """Keep the "New answer ↓" button at the bottom middle."""
        super().resizeEvent(event)
        if not self._new_pill.isHidden():
            self._place_pill()


def _all_text(widget: QWidget) -> str:
    """All the label text inside a message, joined with spaces."""
    return " ".join(label.text() for label in widget.findChildren(QLabel) if label.text())
