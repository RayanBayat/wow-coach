"""The scrolling conversation.

New messages fade in, and the view always glides down to the newest one (the player asked
for this: a new answer should never hide below the bottom edge). The coach's typing dots
are brought into view too.
"""

import time

from PySide6.QtCore import QPropertyAnimation, QSize, Qt, QTimer
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
    ReplyBubble,
    TypingBubble,
)

FOLLOW_SECONDS = 0.5  # how long after adding a message the view keeps following the growth
MIN_CHAT_WIDTH = 240


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
        self._coach_bubbles: list[CoachBubble | ReplyBubble] = []
        # Layout order: all message rows, then the typing dots, then a spring.
        self._typing = TypingBubble()
        self._typing_row = MessageRow(self._typing, on_right=False)
        self._typing_row.hide()
        self._column.addWidget(self._typing_row)
        self._column.addStretch(1)
        self.setWidget(content)

        self._glide: QPropertyAnimation | None = None
        self._follow_until = 0.0
        self._follow_animated = True
        self.verticalScrollBar().rangeChanged.connect(self._range_changed)

    # ---- reading ------------------------------------------------------------------------

    def message_count(self) -> int:
        """How many messages are in the chat."""
        return len(self._rows)

    def texts(self) -> list[str]:
        """The visible words of every message, oldest first (used by tests)."""
        return [_all_text(row.content) for row in self._rows]

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
        show_lookups: bool = True,
        animate: bool = True,
    ) -> MessageRow:
        """Add an answer from the coach (on the left)."""
        bubble = CoachBubble(answer, now=now, show_lookups=show_lookups)
        self._coach_bubbles.append(bubble)
        return self._add(bubble, on_right=False, animate=animate)

    def add_reply(
        self,
        text: str,
        *,
        tag: str | None,
        seconds: float | None,
        now: float,
        animate: bool = True,
    ) -> MessageRow:
        """Add a coach reply that is plain text (on the left)."""
        bubble = ReplyBubble(text, tag=tag, seconds=seconds, now=now)
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

    def set_typing(self, on: bool) -> None:
        """Show or hide the coach's typing dots, and keep them in view."""
        if not on:
            self._typing.set_activity("")
        if on == self.typing_visible:
            return
        self._typing_row.setVisible(on)
        if on:
            self._scroll_soon()  # the dots (and what the coach is looking up) stay in view

    def set_activity(self, text: str) -> None:
        """Show what the coach is looking up inside the typing bubble (while it is shown)."""
        if self.typing_visible:
            self._typing.set_activity(text)

    @property
    def activity_text(self) -> str:
        """The line next to the typing dots (for tests)."""
        return self._typing.activity_text

    def refresh_times(self, now: float) -> None:
        """Update "5 min ago" in every answer."""
        for bubble in self._coach_bubbles:
            bubble.update_time(now)

    # ---- scrolling ----------------------------------------------------------------------

    def scroll_to_newest(self) -> None:
        """Glide to the bottom."""
        if self._glide is not None:
            self._glide.stop()  # two glides at once would fight over the scrollbar
        bar = self.verticalScrollBar()
        animation = glide(bar, bar.maximum())
        self._glide = animation
        # The animation deletes itself when it stops; forget it first so we never touch
        # a deleted object.
        animation.stateChanged.connect(lambda *_: self._forget_glide(animation))

    def _forget_glide(self, animation: QPropertyAnimation) -> None:
        """A glide stopped: drop our reference to it (if it is still the current one)."""
        if self._glide is animation:
            self._glide = None

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
        row = MessageRow(content, on_right=on_right, share=share)
        self._column.insertWidget(len(self._rows), row)
        self._rows.append(row)
        if animate:
            fade_in(row)
        self._scroll_soon(animated=animate)  # every new message brings the view down
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


def _all_text(widget: QWidget) -> str:
    """All the label and button text inside a message, joined with spaces."""
    pieces = [label.text() for label in widget.findChildren(QLabel)]
    pieces += [button.text() for button in widget.findChildren(QPushButton)]
    return " ".join(piece for piece in pieces if piece)
