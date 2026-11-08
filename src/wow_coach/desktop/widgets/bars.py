"""Small cards of the Coach page: the calm problem banner, the "questions are waiting" bar and
the "please sign in" card."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QVBoxLayout

from wow_coach.desktop.theme import SPACE
from wow_coach.desktop.widgets.bubbles import plain_label


class ProblemBanner(QFrame):
    """Shows the one-sentence problem from the state (for example "No saved game data yet")."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("problemBanner")
        self._label = plain_label("")
        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE, SPACE - 4, SPACE, SPACE - 4)
        row.addWidget(self._label)
        self.hide()

    def show_problem(self, sentence: str | None) -> None:
        """Show the sentence, or hide the banner when there is no problem."""
        self._label.setText(sentence or "")
        self.setVisible(bool(sentence))

    @property
    def text(self) -> str:
        """The sentence now shown."""
        return self._label.text()


class OpenQuestionsBar(QFrame):
    """ "2 questions from the game are waiting" with an "Answer now" button."""

    answer_now = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("questionsBar")
        self._label = plain_label("")
        self.button = QPushButton("Answer now")
        self.button.setProperty("kind", "secondary")
        self.button.setToolTip("Your coach answers the questions you typed in the game.")
        self.button.clicked.connect(self.answer_now)
        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE, SPACE - 4, SPACE, SPACE - 4)
        row.addWidget(self._label, 1)
        row.addWidget(self.button)
        self.hide()

    def show_count(self, count: int) -> None:
        """Show how many questions wait, or hide the bar when none do."""
        noun = "question from the game is" if count == 1 else "questions from the game are"
        self._label.setText(f"{count} {noun} waiting")
        self.setVisible(count > 0)

    @property
    def text(self) -> str:
        """The sentence now shown."""
        return self._label.text()


class SignInCard(QFrame):
    """Tells the player the coach needs a ChatGPT sign-in, with a button to do it."""

    sign_in = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("role", "card")
        title = plain_label("Sign in to start chatting", "subtitle")
        body = plain_label(
            "Your coach thinks with your own ChatGPT account, so it needs you to sign in once. "
            "It only takes a minute and you can sign out any time."
        )
        self.button = QPushButton("Sign in with ChatGPT")
        self.button.setProperty("kind", "primary")
        self.button.setToolTip("Opens the ChatGPT page, where you sign in.")
        self.button.clicked.connect(self.sign_in)
        column = QVBoxLayout(self)
        column.setContentsMargins(SPACE + 4, SPACE, SPACE + 4, SPACE)
        column.addWidget(title)
        column.addWidget(body)
        row = QHBoxLayout()
        row.addWidget(self.button)
        row.addStretch(1)
        column.addLayout(row)
        self.hide()
