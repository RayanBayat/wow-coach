"""The things that appear in the chat: bubbles, notices, the typing dots.

SAFETY: answers come from an AI and questions come from the game, so they are untrusted
text. Every label here is plain text (``Qt.TextFormat.PlainText``): characters are shown as
characters and are never read as page code or turned into links.
"""

import math
import time
from collections.abc import Callable
from urllib.parse import urlsplit

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

from wow_coach.desktop.state import AnswerView, LookupView, SourceView
from wow_coach.desktop.theme import SPACE, SPACE_SMALL, current_colors
from wow_coach.desktop.widgets.flow import FlowLayout
from wow_coach.desktop.widgets.formatting import relative_time
from wow_coach.engine.sources import is_web_url

USAGE_URL = "https://chatgpt.com/settings/usage"  # where the player manages their plan's usage
BUBBLE_WIDTH_SHARE = 0.7  # a bubble is at most 70% as wide as the chat
MIN_BUBBLE_WIDTH = 120
BUBBLE_TEXT_SLACK = 80  # room for the bubble's padding and the step numbers
COLLAPSE_AFTER_CHARS = 700  # a longer reply starts folded, with a "Show more" button
MAX_SOURCE_LABEL_CHARS = 60  # a long page title is cut, the tooltip has the whole link
SOURCES_HEADING = "Sources"
LOOKUPS_OPEN_MARK = "\u25be"  # a small triangle pointing down
LOOKUPS_CLOSED_MARK = "\u25b8"  # a small triangle pointing right


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


def domain_of(url: str) -> str:
    """The site of a link without "www.", for a source that has no title."""
    host = urlsplit(url).hostname or url
    return host.removeprefix("www.")


def open_source(url: str) -> None:
    """Open a source link in the browser. Only plain web links are ever opened."""
    if is_web_url(url):
        QDesktopServices.openUrl(QUrl(url))


class SourcesList(QWidget):
    """ "Sources" and one small link button per source (title, or the site when it has none).

    The full link is the button's tooltip. Nothing is opened until a button is clicked. These
    links come from our own code (see ``engine/sources.py``), never from the AI's words.
    """

    def __init__(self, sources: tuple[SourceView, ...]) -> None:
        super().__init__()
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addWidget(plain_label(SOURCES_HEADING, "small"))
        holder = QWidget()
        flow = FlowLayout(holder, spacing=SPACE_SMALL)
        self.buttons: list[QPushButton] = []
        for source in sources:
            label = source.title or domain_of(source.url)
            if len(label) > MAX_SOURCE_LABEL_CHARS:
                label = label[: MAX_SOURCE_LABEL_CHARS - 1] + "\u2026"
            button = QPushButton(label)
            button.setProperty("kind", "source")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(source.url)
            button.setAccessibleName(f"Source: {label}")
            button.clicked.connect(lambda _checked=False, url=source.url: open_source(url))
            flow.addWidget(button)
            self.buttons.append(button)
        column.addWidget(holder)


class LookupsToggle(QWidget):
    """A folded "What the coach looked up (N)" that opens to show one sentence per lookup."""

    def __init__(self, lookups: tuple[LookupView, ...]) -> None:
        super().__init__()
        self._title = f"What the coach looked up ({len(lookups)})"
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        self.button = QPushButton()
        self.button.setProperty("kind", "ghost")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self._flip)
        column.addWidget(self.button, 0, Qt.AlignmentFlag.AlignLeft)
        self.details = plain_label("\n".join(f"\u2022 {item.text}" for item in lookups), "small")
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(self.details)
        self._show(opened=False)

    def _flip(self) -> None:
        self._show(opened=self.details.isHidden())

    def _show(self, *, opened: bool) -> None:
        self.details.setVisible(opened)
        mark = LOOKUPS_OPEN_MARK if opened else LOOKUPS_CLOSED_MARK
        self.button.setText(f"{mark} {self._title}")

    @property
    def opened(self) -> bool:
        """True while the sentences are shown."""
        return not self.details.isHidden()


def _time_tooltip(seconds: float | None, now: float) -> str:
    """ "Answered 5 min ago", for pointing at an answer; empty when the time is unknown."""
    if seconds is None or seconds <= 0:
        return ""
    return f"Answered {relative_time(now - seconds)}"


class CoachBubble(QFrame):
    """One answer from the coach: title, numbered steps, text, warnings, sources and lookups.

    There is no small line with the AI's name or the time under the answer: the time shows
    when the player points at the bubble.
    """

    def __init__(self, answer: AnswerView, *, now: float, show_lookups: bool = True) -> None:
        super().__init__()
        self.setObjectName("coachBubble")
        self._answered_at = answer.answered_at
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
        self.sources_list: SourcesList | None = None
        if answer.sources:
            self.sources_list = SourcesList(answer.sources)
            column.addWidget(self.sources_list)
        self.lookups_toggle: LookupsToggle | None = None
        if answer.lookups and show_lookups:
            self.lookups_toggle = LookupsToggle(answer.lookups)
            column.addWidget(self.lookups_toggle)
        self.update_time(now)

    def update_time(self, now: float) -> None:
        """Refresh the tooltip, so "just now" slowly becomes "5 min ago"."""
        self.setToolTip(_time_tooltip(self._answered_at, now))


class ReplyBubble(QFrame):
    """A coach reply that is just text (for example a chat with the Claude coach).

    It looks like an answer on parchment. Long replies start folded; "Show more" opens them.
    The text is shown as plain text, never as markup.
    """

    def __init__(self, text: str, *, tag: str | None, seconds: float | None, now: float) -> None:
        super().__init__()
        self.setObjectName("coachBubble")
        self._seconds = seconds
        self._full_text = text
        self._folded = len(text) > COLLAPSE_AFTER_CHARS
        column = QVBoxLayout(self)
        column.setContentsMargins(SPACE, SPACE - 2, SPACE, SPACE - 2)
        column.setSpacing(SPACE_SMALL)
        if tag:
            column.addWidget(plain_label(tag, "small"))
        self._body = plain_label("", selectable=True)
        column.addWidget(self._body)
        self._toggle = QPushButton()
        self._toggle.setProperty("kind", "ghost")
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.clicked.connect(self._flip)
        self._toggle.setVisible(self._folded)
        column.addWidget(self._toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self._show_text()
        self.update_time(now)

    def _flip(self) -> None:
        self._folded = not self._folded
        self._show_text()

    def _show_text(self) -> None:
        shown = self._full_text
        if self._folded:
            shown = self._full_text[:COLLAPSE_AFTER_CHARS].rstrip() + "\u2026"
        self._body.setText(shown)
        self._toggle.setText("Show more" if self._folded else "Show less")

    def update_time(self, now: float) -> None:
        """Refresh the tooltip, so "just now" slowly becomes "5 min ago"."""
        self.setToolTip(_time_tooltip(self._seconds, now))

    @property
    def folded(self) -> bool:
        """True while the long text is folded."""
        return self._folded

    @property
    def toggle_button(self) -> QPushButton:
        """The "Show more" button (for tests)."""
        return self._toggle


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
    """The coach's bubble that holds the typing dots and, when it looks something up, what."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("typingBubble")
        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE, 4, SPACE, 4)
        row.addWidget(TypingIndicator())
        self._activity = plain_label("", "small")
        self._activity.hide()
        row.addWidget(self._activity, 1)
        self.setToolTip("Your coach is working on an answer.")

    def set_activity(self, text: str) -> None:
        """Show the newest thing the coach is doing next to the dots ("" hides it)."""
        self._activity.setText(text)
        self._activity.setVisible(bool(text))

    @property
    def activity_text(self) -> str:
        """The line shown next to the dots (for tests)."""
        return self._activity.text()


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
