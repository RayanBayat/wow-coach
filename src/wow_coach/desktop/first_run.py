"""The "I can't find your game yet" window, shown when the app starts without a game folder.

Without it, a player who opens WoW Coach from a menu or at login would see nothing at all:
the game folder is looked up before any window exists. This can happen on the very first start,
or when the game's disk is not connected yet right after login.

``find_game_folder_or_ask`` is the one function ``run.py`` calls. Everything the player can
do here is on a small dialog:

* "Choose the game folder…" opens a folder picker, checks the folder has a ``WTF`` folder (the
  same check as the Setup page) and remembers it, like ``wow-coach setup`` does.
* "Try again" looks once more (for a disk that mounts late).
* "Quit" stops the app.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Final, Protocol

from PySide6.QtCore import QEventLoop, Qt, SignalInstance
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wow_coach.desktop.setup_checks import change_game_folder
from wow_coach.desktop.theme import SPACE, SPACE_LARGE
from wow_coach.errors import GameFolderNotFound

EXPLANATION: Final = (
    "WoW Coach can't find World of Warcraft yet. Choose the folder called _forever_ (it is "
    "inside your World of Warcraft folder). If your game is on a disk that is not connected "
    "yet, connect it and press Try again."
)
STILL_MISSING: Final = "I still can't find the game. Choose its folder, or connect the disk."
LOGIN_MESSAGE: Final = "WoW Coach can't find your game yet. Click to choose it."
DIALOG_TITLE: Final = "WoW Coach"

# Looks for the game folder; raises ``GameFolderNotFound`` when it is not there.
FindFolder = Callable[[], Path]


class StartupTray(Protocol):
    """The parts of the tray icon this module uses (so tests can pass a fake)."""

    available: bool
    open_requested: SignalInstance
    quit_requested: SignalInstance

    def show(self) -> None:
        """Put the icon in the tray."""

    def hide(self) -> None:
        """Take the icon out of the tray."""

    def show_message(self, text: str) -> None:
        """Pop up a short message next to the icon."""


def _pick_with_dialog(parent: QWidget) -> str:
    """The real folder picker. Returns "" when the player cancels."""
    return QFileDialog.getExistingDirectory(
        parent, "Choose the _forever_ folder of World of Warcraft"
    )


class GameFolderDialog(QDialog):
    """Explains the problem and lets the player fix it. ``folder`` is set when it worked."""

    def __init__(
        self,
        find: FindFolder,
        config_file: Path,
        *,
        pick_folder: Callable[[QWidget], str] = _pick_with_dialog,
    ) -> None:
        """Build the dialog.

        Args:
            find: Looks for the game folder again (raises ``GameFolderNotFound``).
            config_file: Where a chosen folder is remembered (the same file as ``setup``).
            pick_folder: Opens the folder picker and returns the path ("" when cancelled).
        """
        super().__init__()
        self._find = find
        self._config_file = config_file
        self._pick_folder = pick_folder
        self.folder: Path | None = None
        self.setWindowTitle(DIALOG_TITLE)
        self.setMinimumWidth(460)

        title = QLabel("I can't find your game yet")
        title.setProperty("role", "title")
        self.explanation = QLabel(EXPLANATION)
        self.explanation.setWordWrap(True)
        self.explanation.setProperty("role", "muted")
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setProperty("role", "error")
        self.message.setTextFormat(Qt.TextFormat.PlainText)  # shows paths: never markup
        self.message.hide()

        self.choose_button = QPushButton("Choose the game folder…")
        self.choose_button.setProperty("kind", "primary")
        self.retry_button = QPushButton("Try again")
        self.retry_button.setProperty("kind", "secondary")
        self.quit_button = QPushButton("Quit")
        self.quit_button.setProperty("kind", "ghost")
        self.choose_button.clicked.connect(self._choose)
        self.retry_button.clicked.connect(self._retry)
        self.quit_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(self.quit_button)
        buttons.addStretch(1)
        buttons.addWidget(self.retry_button)
        buttons.addWidget(self.choose_button)
        column = QVBoxLayout(self)
        column.setContentsMargins(SPACE_LARGE, SPACE_LARGE, SPACE_LARGE, SPACE_LARGE)
        column.setSpacing(SPACE)
        column.addWidget(title)
        column.addWidget(self.explanation)
        column.addWidget(self.message)
        column.addLayout(buttons)

    def _choose(self) -> None:
        chosen = self._pick_folder(self)
        if not chosen:
            return  # the player cancelled the picker
        result = change_game_folder(Path(chosen), self._config_file)
        if not result.ok:
            self._show_message(result.sentence)
            return
        self.folder = Path(chosen)
        self.accept()

    def _retry(self) -> None:
        try:
            self.folder = self._find()
        except GameFolderNotFound:
            self._show_message(STILL_MISSING)
            return
        self.accept()

    def _show_message(self, text: str) -> None:
        self.message.setText(text)
        self.message.show()


def ask_with_dialog(find: FindFolder, config_file: Path) -> Path | None:
    """Show the dialog and wait. Returns the folder, or None when the player quit."""
    dialog = GameFolderDialog(find, config_file)
    dialog.exec()
    return dialog.folder


def _wait_for_a_click_in_the_tray(tray: StartupTray) -> bool:
    """Show the tray icon with a message and wait. True: it was clicked. False: Quit."""
    loop = QEventLoop()
    answers: list[bool] = []

    def finish(clicked: bool) -> None:
        answers.append(clicked)
        loop.quit()

    tray.open_requested.connect(lambda: finish(True))
    tray.quit_requested.connect(lambda: finish(False))
    tray.show()
    tray.show_message(LOGIN_MESSAGE)
    loop.exec()
    tray.hide()
    return bool(answers) and answers[0]


def find_game_folder_or_ask(
    find: FindFolder,
    *,
    start_hidden: bool,
    make_tray: Callable[[], StartupTray],
    ask: Callable[[FindFolder], Path | None],
) -> Path | None:
    """The game folder, asking the player when it cannot be found. None means "quit".

    Args:
        find: Looks for the game folder (raises ``GameFolderNotFound``).
        start_hidden: True at login. Then no window pops up by itself: the tray icon says
            what is wrong and the dialog opens when the player clicks it.
        make_tray: Builds the tray icon (only used when ``start_hidden``).
        ask: Shows the dialog and returns the chosen folder (None when the player quits).
    """
    try:
        return find()
    except GameFolderNotFound:
        pass
    if start_hidden:
        tray = make_tray()
        if tray.available and not _wait_for_a_click_in_the_tray(tray):
            return None
    return ask(find)
