"""The card at the top of the Coach page: who you play, how fresh the data is, one button."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from wow_coach.desktop.icons import icon
from wow_coach.desktop.state import CharacterView, StateView
from wow_coach.desktop.theme import SPACE, SPACE_SMALL, Colors
from wow_coach.desktop.tray import OVERLAY_TOOLTIP
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
            "Updates by itself whenever the game saves: press your Save for the coach key "
            "in WoW, type /coach, or /reload."
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
    """Character, freshness and the "keep on top" button."""

    character_chosen = Signal(str)
    keep_on_top_clicked = Signal()
    overlay_clicked = Signal()

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

        self.keep_button = QPushButton("Keep on top of the game")
        self.keep_button.setProperty("kind", "chip")
        self.keep_button.setToolTip(
            "Opens a small card that stays above the game and shows your coach's newest answer."
        )
        self.keep_button.clicked.connect(self.keep_on_top_clicked)

        self.overlay_button = QPushButton("Overlay")
        self.overlay_button.setProperty("kind", "chip")
        self.overlay_button.setToolTip(OVERLAY_TOOLTIP)
        self.overlay_button.clicked.connect(self.overlay_clicked)

        top = QHBoxLayout()
        top.setSpacing(SPACE)
        top.addWidget(self._name)
        top.addWidget(self._picker)
        top.addStretch(1)
        top.addWidget(self.pill)
        buttons = QHBoxLayout()
        buttons.setSpacing(SPACE_SMALL)
        buttons.addWidget(self.keep_button)
        buttons.addWidget(self.overlay_button)
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
        for key in state.characters:
            self._picker.addItem(character_label(key), key)  # show a nice name, keep the key
        if state.selected in state.characters:
            self._picker.setCurrentIndex(state.characters.index(state.selected))
        self._picker.blockSignals(False)

    def set_overlay_hint(self, hint: str) -> None:
        """Say in the Overlay button's tooltip how to open the overlay (for example the key)."""
        self.overlay_button.setToolTip(f"{OVERLAY_TOOLTIP} {hint}")

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

    def use_icons(self, colors: Colors) -> None:
        """Draw the buttons' icons in the current theme's colors."""
        self.keep_button.setIcon(icon("pin", colors.text, 16))

    def _picked(self, index: int) -> None:
        key = self._picker.itemData(index)
        if isinstance(key, str) and key:
            self.character_chosen.emit(key)


def character_label(key: str) -> str:
    """How a saved character's key ("Name-Realm") reads in the picker: "Name (Realm)"."""
    name, _dash, realm = key.partition("-")
    return f"{name} ({realm})" if name and realm else key
