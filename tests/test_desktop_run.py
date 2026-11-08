"""Starting the app: the "I can't find the game" window, the quiet login path, the GUI entry."""

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from wow_coach.config import load_saved_wow_dir
from wow_coach.desktop import launcher, run
from wow_coach.desktop.first_run import GameFolderDialog, find_game_folder_or_ask
from wow_coach.errors import GameFolderNotFound


def make_game(root: Path) -> Path:
    game = root / "game"
    (game / "WTF").mkdir(parents=True)
    return game


class Finder:
    """A fake "look for the game folder": fails until ``folder`` is set."""

    def __init__(self) -> None:
        self.folder: Path | None = None
        self.calls = 0

    def __call__(self) -> Path:
        self.calls += 1
        if self.folder is None:
            raise GameFolderNotFound("nothing here")
        return self.folder


def make_dialog(qtbot: QtBot, finder: Finder, config: Path, picked: str = "") -> GameFolderDialog:
    dialog = GameFolderDialog(finder, config, pick_folder=lambda _parent: picked)
    qtbot.addWidget(dialog)
    return dialog


# ---- the dialog ---------------------------------------------------------------------------


def test_the_dialog_explains_the_problem_in_plain_words(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = make_dialog(qtbot, Finder(), tmp_path / "config.json")
    assert "can't find World of Warcraft yet" in dialog.explanation.text()
    assert dialog.choose_button.text() == "Choose the game folder…"
    assert dialog.retry_button.text() == "Try again"
    assert dialog.quit_button.text() == "Quit"


def test_choosing_a_good_folder_saves_it_and_finishes(qtbot: QtBot, tmp_path: Path) -> None:
    game = make_game(tmp_path)
    config = tmp_path / "config.json"
    dialog = make_dialog(qtbot, Finder(), config, picked=str(game))
    dialog.choose_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.folder == game
    assert load_saved_wow_dir(config) == game


def test_choosing_a_folder_without_wtf_is_refused(qtbot: QtBot, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    config = tmp_path / "config.json"
    dialog = make_dialog(qtbot, Finder(), config, picked=str(empty))
    dialog.choose_button.click()
    assert dialog.folder is None
    assert "WTF" in dialog.message.text()
    assert load_saved_wow_dir(config) is None


def test_cancelling_the_picker_changes_nothing(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = make_dialog(qtbot, Finder(), tmp_path / "config.json", picked="")
    dialog.choose_button.click()
    assert dialog.folder is None
    assert dialog.message.isHidden()


def test_try_again_finishes_when_the_disk_has_appeared(qtbot: QtBot, tmp_path: Path) -> None:
    finder = Finder()
    dialog = make_dialog(qtbot, finder, tmp_path / "config.json")
    dialog.retry_button.click()
    assert dialog.folder is None
    assert "still can't find" in dialog.message.text().lower()
    finder.folder = make_game(tmp_path)  # the disk is mounted now
    dialog.retry_button.click()
    assert dialog.folder == finder.folder
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_quit_gives_no_folder(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = make_dialog(qtbot, Finder(), tmp_path / "config.json")
    dialog.quit_button.click()
    assert dialog.folder is None
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_the_dialog_shows_paths_as_plain_text(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = make_dialog(qtbot, Finder(), tmp_path / "config.json")
    assert dialog.message.textFormat().name == "PlainText"


# ---- finding the folder, asking only when needed ---------------------------------------


class FakeTray(QObject):
    """Looks like ``AppTray`` for the quiet login path."""

    open_requested = Signal()
    quit_requested = Signal()

    def __init__(self, *, available: bool = True) -> None:
        super().__init__()
        self.available = available
        self.messages: list[str] = []
        self.shown = False

    def show(self) -> None:
        self.shown = True

    def hide(self) -> None:
        self.shown = False

    def show_message(self, text: str) -> None:
        self.messages.append(text)


def test_a_known_folder_needs_no_dialog(tmp_path: Path) -> None:
    game = make_game(tmp_path)

    def ask(_finder: Finder) -> Path | None:
        raise AssertionError("the dialog must not open")

    found = find_game_folder_or_ask(
        lambda: game, start_hidden=False, make_tray=lambda: FakeTray(), ask=ask
    )
    assert found == game


def test_a_missing_folder_opens_the_dialog_at_once(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    finder = Finder()
    found = find_game_folder_or_ask(
        finder, start_hidden=False, make_tray=lambda: FakeTray(), ask=lambda _f: game
    )
    assert found == game


def test_quitting_the_dialog_gives_none() -> None:
    found = find_game_folder_or_ask(
        Finder(), start_hidden=False, make_tray=lambda: FakeTray(), ask=lambda _f: None
    )
    assert found is None


@pytest.mark.usefixtures("qtbot")
def test_at_login_the_tray_says_it_and_the_dialog_waits_for_a_click(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    tray = FakeTray()
    asked: list[bool] = []

    def ask(_finder: Finder) -> Path | None:
        asked.append(True)
        return game

    def click_soon() -> None:
        assert tray.messages == ["WoW Coach can't find your game yet. Click to choose it."]
        assert tray.shown
        assert asked == []  # nothing popped up by itself
        tray.open_requested.emit()

    QTimer.singleShot(0, click_soon)
    found = find_game_folder_or_ask(Finder(), start_hidden=True, make_tray=lambda: tray, ask=ask)
    assert found == game
    assert asked == [True]
    assert not tray.shown


@pytest.mark.usefixtures("qtbot")
def test_quit_from_the_tray_at_login_gives_none() -> None:
    tray = FakeTray()
    QTimer.singleShot(0, tray.quit_requested.emit)
    found = find_game_folder_or_ask(
        Finder(), start_hidden=True, make_tray=lambda: tray, ask=lambda _f: Path("/never")
    )
    assert found is None


def test_at_login_without_a_tray_the_dialog_opens_at_once(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    found = find_game_folder_or_ask(
        Finder(),
        start_hidden=True,
        make_tray=lambda: FakeTray(available=False),
        ask=lambda _f: game,
    )
    assert found == game


# ---- the GUI entry point (wow-coach-app) -----------------------------------------------------


def test_the_gui_entry_hands_its_arguments_to_the_app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, object] = {}

    def fake_run_desktop(*, wow_dir_flag: Path | None, start_hidden: bool) -> int:
        seen.update(flag=wow_dir_flag, hidden=start_hidden)
        return 0

    monkeypatch.setattr(run, "run_desktop", fake_run_desktop)
    assert launcher.main(["--hidden", "--wow-dir", str(tmp_path)]) == 0
    assert seen == {"flag": tmp_path, "hidden": True}


def test_the_gui_entry_survives_missing_output_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Windows GUI programs have no console, so sys.stdout and sys.stderr are None there.
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(launcher, "desktop_installed", lambda: False)
    assert launcher.main([]) == 1  # a clear failure, and no crash on the missing streams
    assert launcher.main(["--bogus"]) == 2  # argparse wants to print to stderr, too


def test_the_gui_entry_says_what_is_missing_without_qt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(launcher, "desktop_installed", lambda: False)
    assert launcher.main([]) == 1
    assert "desktop extra" in capsys.readouterr().err


# ---- relaunching ------------------------------------------------------------------------------


def test_the_relaunch_command_does_not_depend_on_the_script_launcher(tmp_path: Path) -> None:
    command = run.relaunch_command(None, executable="/env/bin/python", platform="linux")
    assert command == ("/env/bin/python", ["-m", "wow_coach.desktop.launcher"])
    kept = run.relaunch_command(tmp_path, executable="/env/bin/python", platform="linux")
    assert kept[1] == ["-m", "wow_coach.desktop.launcher", "--wow-dir", str(tmp_path)]


def test_the_windows_relaunch_uses_pythonw_when_it_exists(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    program, _arguments = run.relaunch_command(None, executable=str(python), platform="win32")
    assert program == str(tmp_path / "pythonw.exe")
