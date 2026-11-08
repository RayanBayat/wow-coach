"""The box where the player types a question.

* Enter sends, Shift+Enter starts a new line.
* The box grows from one line to six, then scrolls.
* The text is limited to ``MAX_QUESTION_CHARS``; a quiet counter appears near the limit.
* The Send button is gold and stays off while there is nothing to send.
"""

from typing import Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from wow_coach.advice.contract import MAX_QUESTION_CHARS
from wow_coach.desktop.icons import icon
from wow_coach.desktop.theme import SPACE, SPACE_SMALL, Colors
from wow_coach.desktop.widgets.bubbles import plain_label

PLACEHOLDER: Final = "Ask your coach anything…"
MAX_LINES: Final = 6
COUNTER_FROM: Final = int(MAX_QUESTION_CHARS * 0.8)  # the counter appears from here on
EDIT_PADDING: Final = 12  # the stylesheet's padding of the text box, top plus bottom


class _QuestionEdit(QPlainTextEdit):
    """A text box where Enter means "send" and Shift+Enter means "new line"."""

    submit = Signal()
    focus_changed = Signal(bool)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt's method name
        """Send on Enter; everything else (including Shift+Enter) works as usual."""
        is_enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if is_enter and not shift:
            self.submit.emit()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt's method name
        """Tell the composer so it can draw its gold outline."""
        super().focusInEvent(event)
        self.focus_changed.emit(True)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt's method name
        """Tell the composer so it can remove its gold outline."""
        super().focusOutEvent(event)
        self.focus_changed.emit(False)


class Composer(QFrame):
    """The question box with its Send button."""

    # The question the player wants to send (already trimmed, never empty).
    submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("composer")
        self._edit = _QuestionEdit()
        self._edit.setObjectName("composerEdit")
        self._edit.setPlaceholderText(PLACEHOLDER)
        self._edit.setToolTip("Type your question. Enter sends it, Shift+Enter starts a new line.")
        self._edit.setAccessibleName("Your question")
        self._edit.setTabChangesFocus(True)
        self._edit.submit.connect(self.submit)
        self._edit.focus_changed.connect(self._show_focus)
        self._edit.textChanged.connect(self._text_changed)
        self._edit.document().documentLayout().documentSizeChanged.connect(self._grow)

        self._send = QPushButton("Send")
        self._send.setProperty("kind", "primary")
        self._send.setToolTip("Send your question to the coach (Enter).")
        self._send.clicked.connect(self.submit)
        self._counter = plain_label("", "small")
        self._counter.setWordWrap(False)
        self._counter.setToolTip("How many letters you can still use in this question.")

        side = QVBoxLayout()
        side.setSpacing(2)
        side.addWidget(self._send)
        side.addWidget(self._counter, 0, Qt.AlignmentFlag.AlignHCenter)
        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE_SMALL, SPACE_SMALL, SPACE_SMALL, SPACE_SMALL)
        row.setSpacing(SPACE)
        row.addWidget(self._edit, 1)
        row.addLayout(side)
        self._grow()
        self._text_changed()

    # ---- using it -----------------------------------------------------------------------

    def text(self) -> str:
        """What is typed so far."""
        return self._edit.toPlainText()

    def use_icons(self, colors: Colors) -> None:
        """Draw the Send button's icon in the current theme's colors."""
        self._send.setIcon(icon("send", colors.on_button, 16))

    def set_text(self, text: str, cursor: int | None = None) -> None:
        """Put text in the box, with the cursor at ``cursor`` (default: the end), and focus it."""
        self._edit.setPlainText(text)
        position = len(self._edit.toPlainText()) if cursor is None else cursor
        block = self._edit.textCursor()
        block.setPosition(min(position, len(self._edit.toPlainText())))
        self._edit.setTextCursor(block)
        self._edit.setFocus()

    def set_input_enabled(self, enabled: bool) -> None:
        """Turn typing and sending on or off (off while the player is not signed in)."""
        self._edit.setEnabled(enabled)
        self._text_changed()

    def focus_input(self) -> None:
        """Put the cursor in the box."""
        self._edit.setFocus()

    @property
    def send_enabled(self) -> bool:
        """True when the Send button can be pressed."""
        return self._send.isEnabled()

    @property
    def counter_text(self) -> str:
        """The quiet counter's text (empty when far from the limit)."""
        return self._counter.text()

    def submit(self) -> None:
        """Send the typed question, if there is one, and empty the box."""
        question = self.text().strip()
        if not question or not self._edit.isEnabled():
            return
        self._edit.clear()
        self.submitted.emit(question)

    # ---- helpers ------------------------------------------------------------------------

    def _text_changed(self) -> None:
        """Enforce the length limit, update the counter and the Send button."""
        text = self._edit.toPlainText()
        if len(text) > MAX_QUESTION_CHARS:
            # Pasted text can be too long: cut it, and keep the cursor at the end.
            self._edit.setPlainText(text[:MAX_QUESTION_CHARS])
            cursor = self._edit.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self._edit.setTextCursor(cursor)
            return  # setPlainText fires textChanged again with the short text
        self._send.setEnabled(self._edit.isEnabled() and bool(text.strip()))
        if len(text) >= COUNTER_FROM:
            self._counter.setText(f"{len(text)} / {MAX_QUESTION_CHARS}")
        else:
            self._counter.setText("")

    def _grow(self) -> None:
        """Make the box one line tall for short text, up to ``MAX_LINES`` for long text."""
        document = self._edit.document()
        lines = max(1, min(MAX_LINES, round(document.size().height())))
        line_height = self._edit.fontMetrics().lineSpacing()
        margins = int(document.documentMargin() * 2)
        self._edit.setFixedHeight(lines * line_height + margins + EDIT_PADDING)

    def _show_focus(self, focused: bool) -> None:
        self.setProperty("focused", focused)
        self.style().unpolish(self)
        self.style().polish(self)
