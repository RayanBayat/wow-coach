"""The card at the top of the Coach page: who you play, how fresh the data is, two buttons."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from wow_coach.desktop.state import CharacterView, StateView
from wow_coach.desktop.theme import SPACE, SPACE_SMALL
from wow_coach.desktop.widgets.bubbles import plain_label
from wow_coach.desktop.widgets.formatting import Freshness, gold_text

NO_CHARACTER_TEXT = "No character yet"
NO_CHARACTER_HELP = "Log in to the game once with the CoachLink addon on, then type /coach."


class FreshnessPill(QFrame):
    """A small rounded label with a colored dot: "Game data: 12 min old"."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("freshnessPill")
        self._dot = QLabel()
        self._dot.setFixedSize(8, 8)
        self._dot.setProperty("dot", "muted")
        self._text = QLabel()
        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE, 4, SPACE, 4)
        row.setSpacing(SPACE_SMALL)
        row.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._text)
        self.setToolTip(
            "How long ago the game last saved your character. "
            "Your coach can only see what the game has saved."
        )

    def show_freshness(self, value: Freshness) -> None:
        """Show new words and a new dot color."""
        self._text.setText(value.text)
        self._dot.setProperty("dot", value.level)
        self._dot.style().unpolish(self._dot)
        self._dot.style().polish(self._dot)

    @property
    def text(self) -> str:
        """The words now shown."""
        return self._text.text()

    @property
    def level(self) -> str:
        """The color name now shown: success, warning or muted."""
        return str(self._dot.property("dot"))


def describe_character(character: CharacterView | None) -> str:
    """One muted line about the character: ``Level 12 Undead Mage · Tirisfal Glades · 1g 2s 3c``."""
    if character is None:
        return NO_CHARACTER_HELP
    pieces: list[str] = []
    who = " ".join(
        part
        for part in (
            f"Level {character.level}" if character.level is not None else None,
            character.race,
            character.class_name,
        )
        if part
    )
    if who:
        pieces.append(who)
    if character.zone:
        pieces.append(character.zone)
    if character.money is not None:
        pieces.append(gold_text(character.money))
    return " · ".join(pieces)


class HeaderCard(QFrame):
    """Character, freshness and the two header buttons."""

    character_chosen = Signal(str)
    refresh_clicked = Signal()
    keep_on_top_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("role", "card")
        self._name = QLabel(NO_CHARACTER_TEXT)
        self._name.setProperty("role", "subtitle")
        self._name.setTextFormat(Qt.TextFormat.PlainText)
        self._picker = QComboBox()
        self._picker.setToolTip("Choose which of your characters the coach looks at.")
        self._picker.setAccessibleName("Character")
        self._picker.activated.connect(self._picked)
        self._picker.hide()
        self._detail = plain_label("", "muted")
        self.pill = FreshnessPill()

        self.refresh_button = QPushButton("Refresh game data")
        self.refresh_button.setProperty("kind", "secondary")
        self.refresh_button.setToolTip(
            "Shows how to make the game save your character again, so the coach sees "
            "what you did just now."
        )
        self.refresh_button.clicked.connect(self.refresh_clicked)
        self.keep_button = QPushButton("Keep on top of the game")
        self.keep_button.setProperty("kind", "chip")
        self.keep_button.setToolTip(
            "Opens a small card that stays above the game and shows your coach's newest answer."
        )
        self.keep_button.clicked.connect(self.keep_on_top_clicked)

        top = QHBoxLayout()
        top.setSpacing(SPACE)
        top.addWidget(self._name)
        top.addWidget(self._picker)
        top.addStretch(1)
        top.addWidget(self.pill)
        buttons = QHBoxLayout()
        buttons.setSpacing(SPACE_SMALL)
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.keep_button)
        buttons.addStretch(1)
        column = QVBoxLayout(self)
        column.setContentsMargins(SPACE + 4, SPACE, SPACE + 4, SPACE)
        column.setSpacing(SPACE_SMALL)
        column.addLayout(top)
        column.addWidget(self._detail)
        column.addLayout(buttons)

    def show_state(self, state: StateView) -> None:
        """Fill in the character and the picker."""
        character = state.character
        self._name.setText(character.name if character and character.name else NO_CHARACTER_TEXT)
        self._detail.setText(describe_character(character))
        many = len(state.characters) > 1
        self._picker.setVisible(many)
        self._name.setVisible(not many)
        self._picker.blockSignals(True)  # filling the list must not count as a choice
        self._picker.clear()
        self._picker.addItems(list(state.characters))
        if state.selected in state.characters:
            self._picker.setCurrentIndex(state.characters.index(state.selected))
        self._picker.blockSignals(False)

    def show_card_open(self, is_open: bool) -> None:
        """Change the "Keep on top" button's words while the small card is shown."""
        self.keep_button.setText("Hide the small card" if is_open else "Keep on top of the game")

    @property
    def picker_visible(self) -> bool:
        """True when the character picker is shown (more than one character)."""
        return not self._picker.isHidden()

    def choose(self, index: int) -> None:
        """Pick a character by position, as if clicked (used by tests)."""
        self._picker.setCurrentIndex(index)
        self._picked(index)

    def _picked(self, index: int) -> None:
        key = self._picker.itemText(index)
        if key:
            self.character_chosen.emit(key)
