"""Small building blocks shared by the Settings, ChatGPT and Privacy pages.

Nothing here knows about the coach. They are plain Qt widgets with the app's look:

* ``Card``: a rounded panel with a title and a body to fill.
* ``ToggleRow``: a check box with a short explanation under it.
* ``WaitingSpinner``: a small turning arc for "waiting for you".
* ``link_button`` / ``open_link``: a button that opens a fixed web address.
* ``scrollable``: puts a page's content in a scroll area, centred and not too wide.
"""

from typing import Final

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QHideEvent, QPainter, QPaintEvent, QPen, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from wow_coach.desktop.theme import SPACE, SPACE_LARGE, SPACE_SMALL, current_colors

# The only web addresses these pages open by themselves (the sign-in address comes from
# the core and is opened by the ChatGPT page).
USAGE_URL: Final = "https://chatgpt.com/settings/usage"
PRIVACY_URL: Final = "https://github.com/RayanBayat/wow-coach/blob/main/docs/privacy.md"
CONTENT_MAX_WIDTH: Final = 760  # a page's text column; wider is hard to read


def open_link(url: str) -> None:
    """Open a web address in the player's browser."""
    QDesktopServices.openUrl(QUrl(url))


def make_label(text: str, role: str | None = None) -> QLabel:
    """A word-wrapped label that shows ``text`` as plain text (never as HTML).

    Plain text matters because some texts come from outside (server errors, web addresses).
    """
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if role is not None:
        label.setProperty("role", role)
    return label


def make_button(text: str, kind: str, tooltip: str) -> QPushButton:
    """A button with the app's look (``kind``: primary, secondary, ghost, chip or danger)."""
    button = QPushButton(text)
    button.setProperty("kind", kind)
    button.setToolTip(tooltip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def link_button(text: str, url: str, tooltip: str, kind: str = "ghost") -> QPushButton:
    """A button that opens ``url`` in the browser when clicked."""
    button = make_button(text, kind, tooltip)
    button.clicked.connect(lambda _checked=False: open_link(url))
    return button


class Card(QFrame):
    """A rounded panel with an optional title and a line of explanation."""

    def __init__(self, title: str = "", intro: str = "") -> None:
        super().__init__()
        self.setProperty("role", "card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(SPACE_LARGE, SPACE_LARGE, SPACE_LARGE, SPACE_LARGE)
        self.body.setSpacing(SPACE)
        if title:
            self.body.addWidget(make_label(title, "subtitle"))
        if intro:
            self.body.addWidget(make_label(intro, "muted"))


class ToggleRow(QWidget):
    """A check box with a short plain-words explanation under it."""

    def __init__(self, text: str, description: str, tooltip: str) -> None:
        super().__init__()
        self.check = QCheckBox(text)
        self.check.setToolTip(tooltip)
        self.description = make_label(description, "small")
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addWidget(self.check)
        indent = QHBoxLayout()
        indent.setContentsMargins(26, 0, 0, 0)  # lines the text up under the check box label
        indent.addWidget(self.description)
        column.addLayout(indent)

    def set_available(self, available: bool, reason: str) -> None:
        """Grey the row out and say why, when the computer cannot do this."""
        self.check.setEnabled(available)
        if not available:
            self.description.setText(reason)
            self.check.setToolTip(reason)


class WaitingSpinner(QWidget):
    """A small turning arc. It only turns while it is visible, so it costs nothing hidden."""

    SIZE: Final = 22
    STEP_MS: Final = 40
    DEGREES_PER_STEP: Final = 14

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(self.SIZE, self.SIZE)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self.STEP_MS)
        self._timer.timeout.connect(self._turn)

    @property
    def is_turning(self) -> bool:
        """True while the animation runs."""
        return self._timer.isActive()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802  (Qt's name)
        """Start turning when shown."""
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802  (Qt's name)
        """Stop turning when hidden."""
        self._timer.stop()
        super().hideEvent(event)

    def _turn(self) -> None:
        self._angle = (self._angle + self.DEGREES_PER_STEP) % 360
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802  (Qt's name)
        """Draw a gold quarter-circle arc on a faint ring."""
        del event
        colors = current_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(3, 3, self.SIZE - 6, self.SIZE - 6)
        ring = QPen(colors.border)
        ring.setWidth(3)
        painter.setPen(ring)
        painter.drawEllipse(rect)
        arc = QPen(colors.accent)
        arc.setWidth(3)
        arc.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc)
        painter.drawArc(rect, -self._angle * 16, -90 * 16)
        painter.end()


def scrollable(content: QWidget, max_width: int = CONTENT_MAX_WIDTH) -> QScrollArea:
    """Put ``content`` in a scroll area, centred, with a readable maximum width."""
    content.setMaximumWidth(max_width)
    content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    wrapper = QWidget()
    row = QHBoxLayout(wrapper)
    row.setContentsMargins(SPACE_LARGE, SPACE_LARGE, SPACE_LARGE, SPACE_LARGE)
    row.addStretch(1)
    row.addWidget(content, 100, Qt.AlignmentFlag.AlignTop)
    row.addStretch(1)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(wrapper)
    return area


def page_header(title: str, subtitle: str) -> QVBoxLayout:
    """The top of a page: a big title and one calm line under it."""
    column = QVBoxLayout()
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(SPACE_SMALL)
    column.addWidget(make_label(title, "title"))
    column.addWidget(make_label(subtitle, "muted"))
    return column
