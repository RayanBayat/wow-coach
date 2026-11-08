"""The things that appear in the chat: bubbles, notices, the typing dots.

SAFETY: answers come from an AI and questions come from the game, so they are untrusted
text. Every label here is plain text (``Qt.TextFormat.PlainText``): characters are shown as
characters and are never read as page code or turned into links.
"""

import math
import time
from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QHideEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from wow_coach.desktop.state import AnswerView
from wow_coach.desktop.theme import SPACE, SPACE_SMALL, current_colors
from wow_coach.desktop.widgets.formatting import relative_time

USAGE_URL = "https://chatgpt.com/settings/usage"  # where the player manages their plan's usage
BUBBLE_WIDTH_SHARE = 0.7  # a bubble is at most 70% as wide as the chat
MIN_BUBBLE_WIDTH = 120
BUBBLE_TEXT_SLACK = 80  # room for the bubble's padding and the step numbers
SAVED_IN_GAME_NOTE = "Also in your in-game panel after your next reload"


def plain_label(text: str, role: str | None = None, *, selectable: bool = False) -> QLabel:
    """A word-wrapping label that shows ``text`` exactly as it is (never as markup)."""
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if role:
        label.setProperty("role", role)
    if selectable:
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    # Wrapped labels must be allowed to shrink, or a long word would widen the whole chat.
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    return label


def _frame(name: str, margins: int = SPACE) -> tuple[QFrame, QVBoxLayout]:
    """A frame with an object name (the stylesheet looks at it) and a roomy vertical layout."""
    frame = QFrame()
    frame.setObjectName(name)
    column = QVBoxLayout(frame)
    column.setContentsMargins(margins, margins - 2, margins, margins - 2)
    column.setSpacing(SPACE_SMALL)
    return frame, column


class CoachBubble(QFrame):
    """One answer from the coach: title, numbered steps, text, warnings and a small meta line."""

    def __init__(self, answer: AnswerView, *, note: str, written_to_game: bool, now: float) -> None:
        super().__init__()
        self.setObjectName("coachBubble")
        self._answered_at = answer.answered_at
        self._meta_tail = _meta_tail(note, written_to_game)
        self._source = answer.source
        column = QVBoxLayout(self)
        column.setContentsMargins(SPACE, SPACE - 2, SPACE, SPACE - 2)
        column.setSpacing(SPACE_SMALL)

        if answer.title:
            title = plain_label(answer.title, "subtitle", selectable=True)
            column.addWidget(title)
        for number, step in enumerate(answer.steps, start=1):
            column.addLayout(_step_row(number, step))
        if answer.text:
            column.addWidget(plain_label(answer.text, selectable=True))
        for warning in answer.warnings:
            column.addWidget(_warning_callout(warning))
        self._meta = plain_label("", "small")
        column.addWidget(self._meta)
        self.update_time(now)

    def update_time(self, now: float) -> None:
        """Redraw the meta line, so "just now" slowly becomes "5 min ago"."""
        pieces: list[str] = []
        if self._source:
            pieces.append(f"From {self._source}")
        if self._answered_at:
            pieces.append(relative_time(now - self._answered_at))
        pieces.extend(self._meta_tail)
        self._meta.setText(" · ".join(pieces))
        self._meta.setVisible(bool(pieces))

    @property
    def meta_text(self) -> str:
        """The text of the small line under the answer (for tests)."""
        return self._meta.text()


def _meta_tail(note: str, written_to_game: bool) -> list[str]:
    tail = [note] if note else []
    if written_to_game:
        tail.append(SAVED_IN_GAME_NOTE)
    return tail


def _step_row(number: int, step: str) -> QHBoxLayout:
    """One numbered step: the number in its own column so wrapped lines line up."""
    row = QHBoxLayout()
    row.setSpacing(SPACE_SMALL)
    badge = QLabel(f"{number}.")
    badge.setProperty("role", "muted")
    badge.setFixedWidth(22)
    badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
    row.addWidget(badge)
    row.addWidget(plain_label(step, selectable=True), 1)
    return row


def _warning_callout(warning: str) -> QFrame:
    callout, column = _frame("warningCallout", SPACE - 2)
    column.addWidget(plain_label(f"Careful: {warning}"))
    return callout


class PlayerBubble(QFrame):
    """A question from the player, on the right. ``tag`` marks where it came from."""

    def __init__(self, text: str, tag: str | None = None) -> None:
        super().__init__()
        self.setObjectName("playerBubble")
        column = QVBoxLayout(self)
        column.setContentsMargins(SPACE, SPACE - 4, SPACE, SPACE - 4)
        column.setSpacing(2)
        if tag:
            column.addWidget(plain_label(tag, "small"))
        column.addWidget(plain_label(text, selectable=True))


class Notice(QFrame):
    """A quiet line in the middle of the chat ("Waiting for fresh game data…")."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.setObjectName("waitingNotice")
        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE, SPACE_SMALL, SPACE, SPACE_SMALL)
        label = plain_label(text, "muted")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(label)
        self.text = text


class ErrorNotice(QFrame):
    """What went wrong, in plain words. A usage-limit error offers "Manage usage"."""

    def __init__(self, message: str, *, is_limit: bool) -> None:
        super().__init__()
        self.setObjectName("errorNotice")
        column = QVBoxLayout(self)
        column.setContentsMargins(SPACE, SPACE - 2, SPACE, SPACE - 2)
        column.setSpacing(SPACE_SMALL)
        column.addWidget(plain_label(message))
        self.manage_button: QPushButton | None = None
        if is_limit:
            button = QPushButton("Manage usage")
            button.setProperty("kind", "secondary")
            button.setToolTip("Opens your ChatGPT usage page in your web browser.")
            button.clicked.connect(open_usage_page)
            row = QHBoxLayout()
            row.addWidget(button)
            row.addStretch(1)
            column.addLayout(row)
            self.manage_button = button
        self.message = message


def open_usage_page() -> None:
    """Open the fixed ChatGPT usage page in the player's browser."""
    QDesktopServices.openUrl(QUrl(USAGE_URL))


class MessageRow(QWidget):
    """Holds one message and keeps it at most ``share`` of the row's width.

    Player bubbles sit on the right, everything else on the left.
    """

    def __init__(
        self, content: QWidget, *, on_right: bool, share: float = BUBBLE_WIDTH_SHARE
    ) -> None:
        super().__init__()
        self.content = content
        self._share = share
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        if on_right:
            row.addStretch(1)
        row.addWidget(content, 0, Qt.AlignmentFlag.AlignTop)
        if not on_right:
            row.addStretch(1)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt's method name
        """Fit the message: as wide as its text wants, but never over its share of the row."""
        super().resizeEvent(event)
        widest_allowed = max(int(self.width() * self._share), MIN_BUBBLE_WIDTH)
        wanted = self._wanted_width()
        if wanted is None:
            return
        width = max(min(wanted, widest_allowed), MIN_BUBBLE_WIDTH)
        if width != self.content.width() or self.content.minimumWidth() != width:
            self.content.setFixedWidth(width)
            # Setting the width changes how tall the text wraps. Tell the layouts around us
            # once the current layout pass is over, or they keep the old (taller) size.
            QTimer.singleShot(0, self.updateGeometry)

    def _wanted_width(self) -> int | None:
        """The width at which the longest line of text fits without wrapping (None: no text).

        A wrapping label on its own would pick a narrow, tall shape, so the bubble is told
        how wide to be: long text then fills the allowed width and short text stays small.
        """
        widths = [
            max(label.fontMetrics().horizontalAdvance(line) for line in label.text().split("\n"))
            for label in self.content.findChildren(QLabel)
            if label.text()
        ]
        if not widths:
            return None
        return max(widths) + BUBBLE_TEXT_SLACK


class TypingIndicator(QWidget):
    """Three dots that rise and fall one after another ("the coach is working").

    It only runs its timer while it is on screen, so it costs nothing when hidden.
    """

    DOT_SIZE = 8
    GAP = 6
    STEP_MS = 60
    CYCLE_STEPS = 24

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__()
        self._clock = clock
        self._timer = QTimer(self)
        self._timer.setInterval(self.STEP_MS)
        self._timer.timeout.connect(self.update)
        self.setFixedSize(3 * self.DOT_SIZE + 2 * self.GAP + 8, self.DOT_SIZE + 12)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt's method name
        """Start moving when shown."""
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 - Qt's method name
        """Stop moving when hidden."""
        super().hideEvent(event)
        self._timer.stop()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802, ARG002 - Qt's signature
        """Draw the dots; each one is a little behind the one before it."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(current_colors().parchment_muted)  # the dots sit on parchment
        phase = self._clock() * 1000 / (self.STEP_MS * self.CYCLE_STEPS) * 2 * math.pi
        for index in range(3):
            wave = (math.sin(phase - index * 0.9) + 1) / 2  # 0..1
            color.setAlphaF(0.35 + 0.65 * wave)
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            left = 4 + index * (self.DOT_SIZE + self.GAP)
            top = 6 + (1 - wave) * 3
            painter.drawEllipse(QRectF(left, top, self.DOT_SIZE, self.DOT_SIZE))


class TypingBubble(QFrame):
    """The coach's bubble that holds the typing dots."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("typingBubble")
        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE, 4, SPACE, 4)
        row.addWidget(TypingIndicator())
        self.setToolTip("Your coach is working on an answer.")


class ClickableCard(QFrame):
    """A frame that acts like a button: click it, or focus it and press Enter or Space."""

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt's method name
        """A click inside the card counts."""
        super().mouseReleaseEvent(event)
        if self.isEnabled():
            self.clicked.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt's method name
        """Enter and Space count as a click."""
        activating = (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)
        if event.key() in activating and self.isEnabled():
            self.clicked.emit()
            return
        super().keyPressEvent(event)
