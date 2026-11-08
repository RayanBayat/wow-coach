"""The "Keep on top of the game" card: a small window that floats above the game.

It shows the coach's newest answer (title and steps) so the player can read it while playing.

* It never takes the keyboard from the game (``WA_ShowWithoutActivating``).
* The player can drag it anywhere; it remembers where it was left.
* On Linux with Wayland, programs may not stay on top of other windows; ``run.py`` starts
  the app through XWayland (as an X11 app) to make this work.

Answers are untrusted text, so every label is plain text.
"""

from typing import Final

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QGuiApplication, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from wow_coach.desktop.state import AnswerView
from wow_coach.desktop.theme import RADIUS, SPACE, SPACE_SMALL, current_colors
from wow_coach.desktop.widgets.animation import fade
from wow_coach.desktop.widgets.bubbles import plain_label

CARD_WIDTH: Final = 380
EDGE_MARGIN: Final = 24  # distance from the screen edge for the first position
POSITION_KEY: Final = "compact/position"
EMPTY_TEXT: Final = "No answers yet. Ask your coach a question in the WoW Coach window."


def default_settings() -> QSettings:
    """Where the card remembers its position (the player's own settings, not a game folder)."""
    return QSettings("wow-coach", "desktop")


class CompactCard(QWidget):
    """The small always-on-top answer card."""

    # The player pressed "Open WoW Coach": the page raises the main window.
    open_requested = Signal()
    # The card was closed (button or Alt+F4), so the header button can say "Keep on top" again.
    closed = Signal()

    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._settings = settings if settings is not None else default_settings()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Showing the card must not steal the keyboard from the game.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(CARD_WIDTH)
        self.setWindowTitle("WoW Coach")
        self._drag_offset: QPointF | None = None
        self._shown: tuple[object, ...] | None = None

        self._answer_area = QWidget()
        self._answer_column = QVBoxLayout(self._answer_area)
        self._answer_column.setContentsMargins(0, 0, 0, 0)
        self._answer_column.setSpacing(SPACE_SMALL)

        brand = plain_label("WoW Coach", "small")
        close = QPushButton("✕")
        close.setProperty("kind", "ghost")
        close.setFixedWidth(32)
        close.setToolTip("Close this small card. Your coach window stays open.")
        close.clicked.connect(self.close)
        top = QHBoxLayout()
        top.addWidget(brand, 1)
        top.addWidget(close)
        open_app = QPushButton("Open WoW Coach")
        open_app.setProperty("kind", "secondary")
        open_app.setToolTip("Bring the full WoW Coach window to the front.")
        open_app.clicked.connect(self.open_requested)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE + 4, SPACE, SPACE + 4, SPACE + 2)
        outer.setSpacing(SPACE_SMALL)
        outer.addLayout(top)
        outer.addWidget(self._answer_area)
        outer.addWidget(open_app)
        self.show_answer(None)

    # ---- content ------------------------------------------------------------------------

    def show_answer(self, answer: AnswerView | None) -> None:
        """Show the newest answer (or an invitation to ask), fading when it changes."""
        key: tuple[object, ...] = (
            (None,) if answer is None else (answer.answered_at, answer.title, answer.question_id)
        )
        changed = self._shown is not None and key != self._shown
        self._shown = key
        while (item := self._answer_column.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if answer is None:
            self._answer_column.addWidget(plain_label(EMPTY_TEXT, "muted"))
        else:
            if answer.title:
                self._answer_column.addWidget(plain_label(answer.title, "subtitle"))
            for number, step in enumerate(answer.steps, start=1):
                self._answer_column.addWidget(plain_label(f"{number}. {step}"))
            if not answer.steps and answer.text:
                self._answer_column.addWidget(plain_label(answer.text))
        self.adjustSize()
        if changed and self.isVisible():
            fade(self._answer_area, start=0.0, end=1.0)

    @property
    def texts(self) -> list[str]:
        """The words of the answer area, one entry per line (used by tests)."""
        found: list[str] = []
        for index in range(self._answer_column.count()):
            item = self._answer_column.itemAt(index)
            widget = None if item is None else item.widget()
            if isinstance(widget, QLabel):
                found.append(widget.text())
        return found

    # ---- position -----------------------------------------------------------------------

    def show_at_saved_position(self) -> None:
        """Show the card where the player last left it (or at the top right the first time)."""
        self.move(self._start_position())
        self.show()

    def _start_position(self) -> QPoint:
        saved = self._settings.value(POSITION_KEY)
        if isinstance(saved, QPoint) and QGuiApplication.screenAt(saved) is not None:
            return saved
        area = QGuiApplication.primaryScreen().availableGeometry()
        return QPoint(area.right() - CARD_WIDTH - EDGE_MARGIN, area.top() + EDGE_MARGIN)

    def remember_position(self) -> None:
        """Save where the card is now."""
        self._settings.setValue(POSITION_KEY, self.pos())
        self._settings.sync()

    # ---- drawing and dragging -----------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802, ARG002 - Qt's signature
        """Draw the rounded card (the window itself is see-through)."""
        colors = current_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(colors.surface))
        painter.setPen(QColor(colors.trim))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), RADIUS, RADIUS)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt's method name
        """Start dragging when the left button goes down on the card."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition() - QPointF(self.pos())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt's method name
        """Follow the mouse while dragging."""
        if self._drag_offset is not None:
            self.move((event.globalPosition() - self._drag_offset).toPoint())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt's method name
        """Stop dragging and remember the new place."""
        if self._drag_offset is not None:
            self._drag_offset = None
            self.remember_position()
        super().mouseReleaseEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt's method name
        """Remember the position and tell the page."""
        self.remember_position()
        self.closed.emit()
        super().closeEvent(event)
