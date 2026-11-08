"""The warm welcome shown while the chat is still empty, with three big suggestions."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from wow_coach.desktop.quick_actions import QuickAction, suggestions
from wow_coach.desktop.theme import SPACE, SPACE_LARGE
from wow_coach.desktop.widgets.bubbles import ClickableCard, plain_label

GREETING = "Hi! I'm your coach. Ask me anything about your character, quests or the game."


class SuggestionCard(ClickableCard):
    """A big card with a title and one sentence about what happens when you pick it."""

    def __init__(self, action: QuickAction) -> None:
        super().__init__()
        self.setObjectName("suggestionCard")
        self.action = action
        self.setToolTip(action.tooltip)
        column = QVBoxLayout(self)
        column.setContentsMargins(SPACE + 4, SPACE + 2, SPACE + 4, SPACE + 2)
        column.addWidget(plain_label(action.label, "subtitle"))
        column.addWidget(plain_label(action.tooltip, "muted"))
        column.addStretch(1)
        self.setMinimumWidth(160)


class WelcomeView(QWidget):
    """Greeting plus suggestion cards. ``chosen`` carries the action the player picked."""

    chosen = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.cards: list[SuggestionCard] = []
        title = plain_label(GREETING, "subtitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = plain_label("Not sure where to start? Pick one:", "muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row = QHBoxLayout()
        row.setSpacing(SPACE)
        for action in suggestions():
            card = SuggestionCard(action)
            card.clicked.connect(lambda a=action: self.chosen.emit(a))
            self.cards.append(card)
            row.addWidget(card, 1)
        column = QVBoxLayout(self)
        column.setContentsMargins(SPACE_LARGE, SPACE_LARGE, SPACE_LARGE, SPACE_LARGE)
        column.setSpacing(SPACE)
        column.addStretch(1)
        column.addWidget(title)
        column.addWidget(hint)
        column.addSpacing(SPACE)
        column.addLayout(row)
        column.addStretch(2)

    def set_cards_enabled(self, enabled: bool) -> None:
        """Turn the cards on or off (off while the player is not signed in)."""
        for card in self.cards:
            card.setEnabled(enabled)
