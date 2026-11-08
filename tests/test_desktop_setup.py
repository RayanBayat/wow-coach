"""The Setup page: every check state, install/update, folder choice and the page itself."""

import io
import subprocess
import sys
import zipfile
from pathlib import Path, PureWindowsPath

import pytest
from desktop_support import make_bridge, run_now
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from wow_coach.config import load_saved_wow_dir
from wow_coach.desktop.hotkey import GlobalHotkey, HotkeyState, HotkeyStatus
from wow_coach.desktop.pages.setup import MENU_NAME, SetupPage, SetupServices
from wow_coach.desktop.setup_checks import (
    RESTART_WOW_HINT,
    Status,
    change_game_folder,
    check_addon,
    check_answers_folder,
    check_game_folder,
    create_answers_folder,
    install_or_update_addon,
    make_report,
)
from wow_coach.desktop.shortcuts import ShortcutFolders, ShortcutMaker, overlay_command
from wow_coach.errors import LookupFailed
from wow_coach.setup import RELEASE_URL

VERSION = "9.9.9"


def addon_zip(version: str = VERSION) -> bytes:
    """A tiny fake CoachLink release zip."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("CoachLink/CoachLink.toc", f"## Interface: 16001\n## Version: {version}\n")
        archive.writestr("CoachLink/CoachLink.lua", "-- code\n")
    return buffer.getvalue()


def make_game(root: Path) -> Path:
    game = root / "game"
    (game / "WTF").mkdir(parents=True)
    (game / "Interface" / "AddOns").mkdir(parents=True)
    return game


def install_fake_addon(game: Path, version: str) -> None:
    folder = game / "Interface" / "AddOns" / "CoachLink"
    folder.mkdir()
    (folder / "CoachLink.toc").write_text(f"## Interface: 16001\n## Version: {version}\n")


# ---- the checks ---------------------------------------------------------------------------


def test_game_folder_missing_is_a_problem() -> None:
    assert check_game_folder(None).status is Status.PROBLEM


def test_game_folder_without_wtf_needs_attention(tmp_path: Path) -> None:
    assert check_game_folder(tmp_path).status is Status.ATTENTION


def test_game_folder_found_is_ok_and_shows_the_path(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    check = check_game_folder(game)
    assert check.status is Status.OK
    assert check.sentence == str(game)


def test_addon_missing_old_and_current(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    assert check_addon(game, VERSION)[0].status is Status.PROBLEM
    install_fake_addon(game, "1.0.0")
    check, installed, is_link = check_addon(game, VERSION)
    assert (check.status, installed, is_link) == (Status.ATTENTION, "1.0.0", False)
    assert "1.0.0" in check.sentence
    assert VERSION in check.sentence
    toc = game / "Interface" / "AddOns" / "CoachLink" / "CoachLink.toc"
    toc.write_text(f"## Version: {VERSION}\n")
    assert check_addon(game, VERSION)[0].status is Status.OK


def test_a_linked_addon_is_ok_and_never_replaced(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    source = tmp_path / "dev-copy"
    source.mkdir()
    (game / "Interface" / "AddOns" / "CoachLink").symlink_to(source, target_is_directory=True)
    assert check_addon(game, VERSION)[2] is True

    def no_download(_url: str) -> bytes:
        raise AssertionError("a linked addon must not be downloaded over")

    assert install_or_update_addon(game, VERSION, no_download).ok
    assert not (source / "CoachLink.toc").exists()


def test_a_windows_junction_copy_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A junction is Windows' folder link; Python's is_symlink() says False for it.
    game = make_game(tmp_path)
    install_fake_addon(game, "0.0.1")
    addon = game / "Interface" / "AddOns" / "CoachLink"
    real_is_junction = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda self: self == addon or real_is_junction(self))
    assert check_addon(game, VERSION)[2] is True

    def no_download(_url: str) -> bytes:
        raise AssertionError("a junction must not be downloaded over")

    assert install_or_update_addon(game, VERSION, no_download).ok


def test_answers_folder_check_and_create(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    assert check_answers_folder(game).status is Status.PROBLEM
    assert create_answers_folder(game).ok
    assert check_answers_folder(game).status is Status.OK


def test_the_report_without_a_game_folder_asks_for_it_first() -> None:
    report = make_report(None, VERSION)
    assert report.game_folder.status is Status.PROBLEM
    assert report.addon.status is Status.PROBLEM
    assert report.addon_installed is None


def test_the_report_of_a_ready_game(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    install_fake_addon(game, VERSION)
    create_answers_folder(game)
    report = make_report(game, VERSION)
    statuses = [report.game_folder.status, report.addon.status, report.answers_folder.status]
    assert statuses == [Status.OK, Status.OK, Status.OK]


# ---- the actions --------------------------------------------------------------------------


def test_install_downloads_swaps_and_creates_the_answers_folder(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    install_fake_addon(game, "1.0.0")
    urls: list[str] = []

    def download(url: str) -> bytes:
        urls.append(url)
        return addon_zip()

    result = install_or_update_addon(game, VERSION, download)
    assert result.ok
    assert result.sentence == RESTART_WOW_HINT
    assert urls == [RELEASE_URL.format(v=VERSION)]
    assert check_addon(game, VERSION)[0].status is Status.OK
    assert check_answers_folder(game).status is Status.OK


def test_a_failed_download_keeps_the_old_addon_and_says_what_to_do(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    install_fake_addon(game, "1.0.0")

    def broken(_url: str) -> bytes:
        raise LookupFailed("timeout")

    result = install_or_update_addon(game, VERSION, broken)
    assert not result.ok
    assert "try again" in result.sentence.lower()
    assert check_addon(game, VERSION)[1] == "1.0.0"


def test_a_bad_zip_is_reported(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    assert not install_or_update_addon(game, VERSION, lambda _url: b"not a zip").ok


def test_change_folder_checks_for_wtf_and_saves_it(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    config = tmp_path / "config.json"
    bad = change_game_folder(tmp_path / "nothing", config)
    assert not bad.ok
    assert "WTF" in bad.sentence
    assert load_saved_wow_dir(config) is None
    good = change_game_folder(game, config)
    assert good.ok
    assert "Restart WoW Coach" in good.sentence
    assert load_saved_wow_dir(config) == game


# ---- the page -----------------------------------------------------------------------------


def make_services(
    tmp_path: Path, *, picked: str = "", maker: ShortcutMaker | None = None
) -> SetupServices:
    return SetupServices(
        app_version=VERSION,
        config_file=tmp_path / "config.json",
        download=lambda _url: addon_zip(),
        shortcut_maker=maker,
        runner=run_now,
        pick_folder=lambda _parent: picked,
    )


def make_page(qtbot: QtBot, services: SetupServices, game: Path | None) -> SetupPage:
    bridge, _core = make_bridge()
    page = SetupPage(bridge, services=services)
    qtbot.addWidget(page)
    page.set_game_dir(game)
    return page


def linux_maker(tmp_path: Path, *, program: Path | None) -> tuple[ShortcutMaker, ShortcutFolders]:
    folders = ShortcutFolders(tmp_path / "apps", tmp_path / "autostart", tmp_path / "i.svg")
    return ShortcutMaker(folders, program=program, platform="linux"), folders


def test_the_page_shows_a_problem_without_a_game_folder(qtbot: QtBot, tmp_path: Path) -> None:
    page = make_page(qtbot, make_services(tmp_path), None)
    assert "could not find" in page.game_card.sentence.text()
    assert page.addon_card.button.isHidden()


def test_the_page_installs_the_addon_in_the_background(qtbot: QtBot, tmp_path: Path) -> None:
    game = make_game(tmp_path)
    page = make_page(qtbot, make_services(tmp_path), game)
    assert page.addon_card.button.text() == "Install CoachLink"
    page.addon_card.button.click()
    assert page.message.text() == RESTART_WOW_HINT
    assert page.addon_card.button.isHidden()  # up to date now
    assert "up to date" in page.addon_card.sentence.text()


@pytest.mark.parametrize(
    "error",
    [zipfile.BadZipFile("bad CRC"), subprocess.TimeoutExpired("powershell", 20), RuntimeError("x")],
)
def test_any_failure_in_an_action_ends_the_working_state(
    qtbot: QtBot, tmp_path: Path, error: Exception
) -> None:
    game = make_game(tmp_path)

    def broken_download(_url: str) -> bytes:
        raise error

    services = make_services(tmp_path)
    services.download = broken_download
    page = make_page(qtbot, services, game)
    page.addon_card.button.click()
    assert page.message.text().startswith("That didn't work")
    assert "Troubleshooting" in page.message.text()
    assert page.addon_card.button.isEnabled()  # not stuck on "Working on it..."


def test_the_page_offers_an_update_for_an_old_addon(qtbot: QtBot, tmp_path: Path) -> None:
    game = make_game(tmp_path)
    install_fake_addon(game, "1.0.0")
    page = make_page(qtbot, make_services(tmp_path), game)
    assert page.addon_card.button.text() == "Update CoachLink"


def test_the_page_creates_the_answers_folder(qtbot: QtBot, tmp_path: Path) -> None:
    game = make_game(tmp_path)
    install_fake_addon(game, VERSION)
    page = make_page(qtbot, make_services(tmp_path), game)
    assert page.answers_card.button.text() == "Create it"
    page.answers_card.button.click()
    assert check_answers_folder(game).status is Status.OK
    assert page.answers_card.button.isHidden()


def test_choosing_a_wrong_folder_says_why(qtbot: QtBot, tmp_path: Path) -> None:
    game = make_game(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    page = make_page(qtbot, make_services(tmp_path, picked=str(empty)), game)
    page.game_card.button.click()
    assert "WTF" in page.message.text()
    assert load_saved_wow_dir(tmp_path / "config.json") is None
    assert page.game_card.sentence.text() == str(game)  # unchanged


def test_choosing_the_right_folder_saves_it_and_says_to_restart(
    qtbot: QtBot, tmp_path: Path
) -> None:
    old = make_game(tmp_path)
    new = tmp_path / "other" / "_forever_"
    (new / "WTF").mkdir(parents=True)
    page = make_page(qtbot, make_services(tmp_path, picked=str(new)), old)
    page.game_card.button.click()
    assert "Restart WoW Coach" in page.message.text()
    assert page.game_card.sentence.text() == str(new)
    assert load_saved_wow_dir(tmp_path / "config.json") == new
    # A button does the restart, so the player need not know that closing only hides the window.
    assert not page.restart_button.isHidden()
    with qtbot.waitSignal(page.restart_requested, timeout=1000):
        page.restart_button.click()


def test_the_restart_button_only_shows_after_a_folder_change(qtbot: QtBot, tmp_path: Path) -> None:
    page = make_page(qtbot, make_services(tmp_path), make_game(tmp_path))
    assert page.restart_button.isHidden()
    page.addon_card.button.click()  # some other action
    assert page.restart_button.isHidden()


def test_cancelling_the_folder_dialog_changes_nothing(qtbot: QtBot, tmp_path: Path) -> None:
    page = make_page(qtbot, make_services(tmp_path, picked=""), make_game(tmp_path))
    page.game_card.button.click()
    assert page.message.isHidden()


def test_the_page_hides_shortcut_cards_where_unsupported(qtbot: QtBot, tmp_path: Path) -> None:
    page = make_page(qtbot, make_services(tmp_path, maker=None), make_game(tmp_path))
    assert page.menu_card.isHidden()
    assert page.login_card.isHidden()
    assert "macOS" in page.no_shortcuts.text()


def test_paths_and_error_texts_are_shown_as_plain_text(qtbot: QtBot, tmp_path: Path) -> None:
    # A folder called "<b>x</b>" must not turn into bold text (Qt's AutoText would).
    page = make_page(qtbot, make_services(tmp_path), None)
    assert page.message.textFormat() == Qt.TextFormat.PlainText
    for card in (page.game_card, page.addon_card, page.answers_card, page.menu_card):
        assert card.sentence.textFormat() == Qt.TextFormat.PlainText


def test_the_key_card_explains_the_keybinding(qtbot: QtBot, tmp_path: Path) -> None:
    page = make_page(qtbot, make_services(tmp_path), make_game(tmp_path))
    assert "Save for the coach (reloads the interface)" in page.key_card.sentence.text()
    assert page.key_card.button.isHidden()


def test_the_page_toggles_shortcuts(qtbot: QtBot, tmp_path: Path) -> None:
    maker, folders = linux_maker(tmp_path, program=tmp_path / "bin" / "wow-coach")
    page = make_page(qtbot, make_services(tmp_path, maker=maker), make_game(tmp_path))
    assert page.menu_card.button.text() == f"Add to my {MENU_NAME}"
    page.menu_card.button.click()
    assert (folders.menu_dir / "wow-coach.desktop").is_file()
    assert page.menu_card.button.text() == "Remove"
    page.login_card.button.click()
    assert (folders.autostart_dir / "wow-coach.desktop").is_file()
    page.login_card.button.click()
    assert not (folders.autostart_dir / "wow-coach.desktop").exists()


def test_without_a_stable_program_the_page_shows_the_install_command(
    qtbot: QtBot, tmp_path: Path
) -> None:
    maker, folders = linux_maker(tmp_path, program=None)
    page = make_page(qtbot, make_services(tmp_path, maker=maker), make_game(tmp_path))
    assert not page.menu_card.isHidden()
    assert not page.menu_card.command.isHidden()
    assert "uv tool install" in page.menu_card.command.text()
    assert page.menu_card.button.isHidden()
    assert not folders.menu_dir.exists()


# ---- the overlay hotkey card ---------------------------------------------------------------


class FakeHotkey(GlobalHotkey):
    """A hotkey whose status the test sets by hand."""

    def __init__(
        self, state: HotkeyState, message: str = "", sequence: str = "Ctrl+Shift+Space"
    ) -> None:
        super().__init__()
        self._sequence = sequence
        self._status = HotkeyStatus(state, message)
        self.registered: list[str] = []

    def register(self, sequence: str) -> None:
        self.registered.append(sequence)

    def unregister(self) -> None:
        pass

    def change(self, state: HotkeyState, message: str) -> None:
        self._set_status(state, message)


def overlay_page(
    qtbot: QtBot,
    tmp_path: Path,
    hotkey: GlobalHotkey,
    *,
    platform: str = "linux",
    desktop: str = "KDE",
    program: Path | None = Path("/home/me/.local/bin/wow-coach-app"),
    maker: ShortcutMaker | None = None,
) -> SetupPage:
    services = make_services(tmp_path, maker=maker)
    services.platform = platform
    services.desktop = desktop
    services.program = program
    page = make_page(qtbot, services, make_game(tmp_path))
    page.set_hotkey(hotkey)
    return page


def test_the_overlay_card_is_hidden_until_the_app_gives_it_a_hotkey(
    qtbot: QtBot, tmp_path: Path
) -> None:
    page = make_page(qtbot, make_services(tmp_path), make_game(tmp_path))
    assert page.overlay_card.isHidden()


def test_an_active_hotkey_shows_a_calm_ok_card(qtbot: QtBot, tmp_path: Path) -> None:
    hotkey = FakeHotkey(HotkeyState.ACTIVE, "Active. Press Ctrl+Shift+Space to show or hide it.")
    page = overlay_page(qtbot, tmp_path, hotkey)
    card = page.overlay_card
    assert not card.isHidden()
    assert "Active" in card.sentence.text()
    assert card.steps.isHidden()
    assert card.command.isHidden()
    assert card.retry_button.isHidden()
    assert card.button.text() == "Copy command"


# The command texts below use Linux paths and Linux quoting; Windows has its own test.
LINUX_COMMANDS = pytest.mark.skipif(sys.platform == "win32", reason="Linux paths and quoting")


@LINUX_COMMANDS
def test_a_missing_portal_shows_the_kde_steps_and_the_real_command(
    qtbot: QtBot, tmp_path: Path
) -> None:
    hotkey = FakeHotkey(HotkeyState.UNAVAILABLE, "No portal here.")
    page = overlay_page(qtbot, tmp_path, hotkey)
    card = page.overlay_card
    assert card.sentence.text() == "No portal here."
    assert "System Settings → Keyboard → Shortcuts" in card.steps.text()
    assert "Add New → Command or Script" in card.steps.text()
    assert not card.steps.isHidden()
    assert card.command.text() == "/home/me/.local/bin/wow-coach-app --toggle-overlay"
    assert not card.retry_button.isHidden()


def test_other_linux_desktops_get_generic_steps(qtbot: QtBot, tmp_path: Path) -> None:
    hotkey = FakeHotkey(HotkeyState.UNAVAILABLE, "No portal here.")
    page = overlay_page(qtbot, tmp_path, hotkey, desktop="GNOME")
    assert "custom shortcut" in page.overlay_card.steps.text()
    assert "KDE" not in page.overlay_card.steps.text()


def test_macos_says_there_is_no_global_hotkey_and_has_no_retry(
    qtbot: QtBot, tmp_path: Path
) -> None:
    hotkey = FakeHotkey(HotkeyState.UNAVAILABLE, "macOS has no global hotkey in WoW Coach yet.")
    page = overlay_page(qtbot, tmp_path, hotkey, platform="darwin", desktop="")
    card = page.overlay_card
    assert "macOS" in card.sentence.text()
    assert "Shortcuts app" in card.steps.text()
    assert card.retry_button.isHidden()


@LINUX_COMMANDS
def test_a_path_with_spaces_is_quoted_in_the_command(qtbot: QtBot, tmp_path: Path) -> None:
    hotkey = FakeHotkey(HotkeyState.UNAVAILABLE, "x")
    page = overlay_page(qtbot, tmp_path, hotkey, program=Path("/home/my name/bin/wow-coach-app"))
    assert page.overlay_card.command.text() == "'/home/my name/bin/wow-coach-app' --toggle-overlay"


@LINUX_COMMANDS
def test_copy_command_puts_the_command_on_the_clipboard(qtbot: QtBot, tmp_path: Path) -> None:
    hotkey = FakeHotkey(HotkeyState.UNAVAILABLE, "x")
    page = overlay_page(qtbot, tmp_path, hotkey)
    page.overlay_card.button.click()
    clipboard = QApplication.clipboard()
    assert clipboard is not None
    assert clipboard.text() == "/home/me/.local/bin/wow-coach-app --toggle-overlay"


def test_try_again_asks_the_hotkey_again(qtbot: QtBot, tmp_path: Path) -> None:
    hotkey = FakeHotkey(HotkeyState.UNAVAILABLE, "x", sequence="Ctrl+Alt+F9")
    page = overlay_page(qtbot, tmp_path, hotkey)
    page.overlay_card.retry_button.click()
    assert hotkey.registered == ["Ctrl+Alt+F9"]


def test_the_card_follows_the_hotkeys_status(qtbot: QtBot, tmp_path: Path) -> None:
    hotkey = FakeHotkey(HotkeyState.STARTING, "Waiting for your desktop.")
    page = overlay_page(qtbot, tmp_path, hotkey)
    assert page.overlay_card.steps.isHidden()  # still waiting: no by-hand steps yet
    hotkey.change(HotkeyState.UNAVAILABLE, "The key was not set up.")
    assert not page.overlay_card.steps.isHidden()
    hotkey.change(HotkeyState.ACTIVE, "Active.")
    assert page.overlay_card.steps.isHidden()


def test_without_the_menu_entry_the_card_suggests_adding_it_first(
    qtbot: QtBot, tmp_path: Path
) -> None:
    maker, folders = linux_maker(tmp_path, program=tmp_path / "bin" / "wow-coach")
    hotkey = FakeHotkey(HotkeyState.UNAVAILABLE, "The desktop did not accept the key.")
    page = overlay_page(qtbot, tmp_path, hotkey, maker=maker)
    assert MENU_NAME in page.overlay_card.tip.text()
    page.menu_card.button.click()  # adds the menu entry
    assert (folders.menu_dir / "wow-coach.desktop").is_file()
    assert page.overlay_card.tip.isHidden()


def test_without_a_stable_program_the_card_says_to_install_first(
    qtbot: QtBot, tmp_path: Path
) -> None:
    hotkey = FakeHotkey(HotkeyState.UNAVAILABLE, "x")
    page = overlay_page(qtbot, tmp_path, hotkey, program=None)
    assert page.overlay_card.command.text() == "wow-coach-app --toggle-overlay"
    assert "Install" in page.overlay_card.tip.text()


def test_the_overlay_card_text_is_plain_text(qtbot: QtBot, tmp_path: Path) -> None:
    page = overlay_page(qtbot, tmp_path, FakeHotkey(HotkeyState.UNAVAILABLE, "x"))
    card = page.overlay_card
    for label in (card.sentence, card.steps, card.tip):
        assert label.textFormat() == Qt.TextFormat.PlainText


def test_on_windows_the_overlay_command_uses_windows_quoting() -> None:
    # A Windows path on purpose (backslashes), whatever system the test runs on.
    program = PureWindowsPath("C:/Program Files/WoW Coach/wow-coach-app.exe")
    command = overlay_command(program, platform="win32")
    assert command == '"C:\\Program Files\\WoW Coach\\wow-coach-app.exe" --toggle-overlay'
