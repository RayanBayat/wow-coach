"""The desktop shell: icons, one instance only, the tray and closing the window."""

from pathlib import Path

import pytest
from desktop_support import make_bridge
from PySide6.QtCore import QSettings
from PySide6.QtGui import QCloseEvent
from PySide6.QtNetwork import QHostInfo, QLocalServer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from pytestqt.qtbot import QtBot

from wow_coach.desktop import icons
from wow_coach.desktop.main_window import MainWindow
from wow_coach.desktop.single_instance import (
    TOGGLE_OVERLAY_MESSAGE,
    SingleInstance,
    default_name,
    socket_address,
    socket_folder,
)
from wow_coach.desktop.theme import DARK
from wow_coach.desktop.tray import TRAY_MESSAGE, AppTray

# ---- icons ----------------------------------------------------------------------------


@pytest.mark.parametrize("name", icons.ICON_NAMES)
@pytest.mark.usefixtures("qtbot")
def test_every_icon_draws_something(name: str) -> None:
    image = icons.icon(name, DARK.accent, 20).pixmap(20, 20).toImage()
    visible = [
        image.pixelColor(x, y).alpha() for x in range(image.width()) for y in range(image.height())
    ]
    assert max(visible) > 0


def test_icons_use_the_wanted_color() -> None:
    assert "#123456" in icons.icon_svg("coach", "#123456")
    assert icons.COLOR not in icons.icon_svg("coach", "#123456")


@pytest.mark.usefixtures("qtbot")
def test_the_app_icon_has_many_sizes_and_is_an_svg() -> None:
    assert icons.APP_ICON_SVG.startswith("<svg")
    assert len(icons.app_icon().availableSizes()) >= 5


@pytest.mark.usefixtures("qtbot")
def test_the_app_icon_can_be_saved_as_ico(tmp_path: Path) -> None:
    target = tmp_path / "wow-coach.ico"
    assert icons.save_app_ico(target) is True
    assert target.stat().st_size > 100


def test_saving_the_ico_never_makes_a_pixmap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pixmaps may only be used in the window's thread; the Setup page saves in a background one.
    class NoPixmaps:
        def __init__(self, *_args: object) -> None:
            raise AssertionError("a QPixmap was made")

        @staticmethod
        def fromImage(_image: object) -> None:  # noqa: N802 - Qt's name
            raise AssertionError("a QPixmap was made")

    monkeypatch.setattr(icons, "QPixmap", NoPixmaps)
    target = tmp_path / "wow-coach.ico"
    assert icons.save_app_ico(target) is True
    assert target.stat().st_size > 100


def test_the_sidebar_shows_icons_and_follows_the_selected_page(qtbot: QtBot) -> None:
    bridge, _core = make_bridge()
    window = MainWindow(bridge)
    qtbot.addWidget(window)
    assert not window._nav_buttons["coach"].icon().isNull()
    assert window._nav_buttons["coach"].isChecked()
    window.show_page("settings")
    assert window._nav_buttons["settings"].isChecked()
    assert not window.windowIcon().isNull()


# ---- one instance only -------------------------------------------------------------------


def private_environ(root: Path) -> dict[str, str]:
    """Environment variables that keep the lock file and the socket inside ``root``."""
    (root / "run").mkdir(exist_ok=True)
    return {"WOW_COACH_DATA_DIR": str(root / "data"), "XDG_RUNTIME_DIR": str(root / "run")}


def make_instance(root: Path, name: str = "t") -> SingleInstance:
    return SingleInstance(name, environ=private_environ(root))


def test_the_second_copy_wakes_the_first_and_exits(qtbot: QtBot, tmp_path: Path) -> None:
    first = make_instance(tmp_path)
    second = make_instance(tmp_path)
    try:
        assert first.claim() is True
        with qtbot.waitSignal(first.show_requested, timeout=3000):
            assert second.claim() is False
    finally:
        first.close()


def test_the_toggle_message_reaches_the_running_copy(qtbot: QtBot, tmp_path: Path) -> None:
    first = make_instance(tmp_path)
    try:
        assert first.claim() is True
        shown: list[bool] = []
        first.show_requested.connect(lambda: shown.append(True))
        with qtbot.waitSignal(first.toggle_overlay_requested, timeout=3000):
            assert make_instance(tmp_path).claim(TOGGLE_OVERLAY_MESSAGE) is False
        assert shown == []  # a toggle is not also a "show the window"
    finally:
        first.close()


def test_an_unknown_message_does_nothing(qtbot: QtBot, tmp_path: Path) -> None:
    first = make_instance(tmp_path)
    try:
        assert first.claim() is True
        seen: list[str] = []
        first.show_requested.connect(lambda: seen.append("show"))
        first.toggle_overlay_requested.connect(lambda: seen.append("toggle"))
        with qtbot.waitSignal(first.show_requested, timeout=3000):
            assert make_instance(tmp_path).claim(b"format-the-disk") is False
            assert make_instance(tmp_path).claim() is False  # a real "show" follows
        assert seen == ["show"]
    finally:
        first.close()


def test_the_first_instance_raises_its_window(qtbot: QtBot, tmp_path: Path) -> None:
    bridge, _core = make_bridge()
    window = MainWindow(bridge)
    qtbot.addWidget(window)
    first = make_instance(tmp_path)
    try:
        assert first.claim()
        first.show_requested.connect(window.bring_to_front)
        assert not window.isVisible()
        assert make_instance(tmp_path).claim() is False
        qtbot.waitUntil(window.isVisible, timeout=3000)
    finally:
        first.close()


def test_only_one_of_two_copies_gets_the_lock_and_the_winner_keeps_its_socket(
    qtbot: QtBot, tmp_path: Path
) -> None:
    # The old check looked first and claimed later, so two copies could both win and the
    # second would delete the first one's socket. The lock decides in one step.
    copies = [make_instance(tmp_path) for _ in range(3)]
    try:
        results = [copy.claim() for copy in copies]
        assert results.count(True) == 1
        winner = copies[results.index(True)]
        assert Path(winner.address).exists()  # the losers did not remove it
        with qtbot.waitSignal(winner.show_requested, timeout=3000):
            assert make_instance(tmp_path).claim() is False
    finally:
        for copy in copies:
            copy.close()


def test_the_lock_is_free_again_after_close(tmp_path: Path) -> None:
    first = make_instance(tmp_path)
    assert first.claim()
    first.close()
    second = make_instance(tmp_path)
    try:
        assert second.claim() is True
    finally:
        second.close()


def test_a_lock_left_by_a_crashed_copy_is_taken_over(tmp_path: Path) -> None:
    # A lock file whose program is gone (here: a process id that does not exist) is stale.
    environ = private_environ(tmp_path)
    lock_file = Path(environ["WOW_COACH_DATA_DIR"]) / "instance.lock"
    lock_file.parent.mkdir(parents=True)
    lock_file.write_text(f"2147483646\nwow-coach\n{QHostInfo.localHostName()}\n")
    instance = SingleInstance("t", environ=environ)
    try:
        assert instance.claim() is True
    finally:
        instance.close()


def test_a_socket_left_by_a_crash_is_cleaned_up(tmp_path: Path) -> None:
    # A server that was not closed properly leaves its name behind; nobody answers on it.
    fresh = make_instance(tmp_path)
    folder = Path(fresh.address).parent
    folder.mkdir(mode=0o700)
    crashed = QLocalServer()
    assert crashed.listen(fresh.address)
    crashed.close()
    try:
        assert fresh.claim() is True
    finally:
        fresh.close()


def test_somebody_squatting_on_the_name_does_not_stop_us(tmp_path: Path) -> None:
    # Another program listens on our name but holds no lock: we are still the first copy, and
    # we must not tell it "show" as if it were a running coach.
    instance = make_instance(tmp_path)
    folder = Path(instance.address).parent
    folder.mkdir(mode=0o700)
    squatter = QLocalServer()
    assert squatter.listen(instance.address)
    try:
        assert instance.claim() is True
        assert not squatter.hasPendingConnections()
    finally:
        instance.close()
        squatter.close()


def test_the_socket_lives_in_a_private_folder(tmp_path: Path) -> None:
    instance = make_instance(tmp_path)
    try:
        assert instance.claim()
        folder = Path(instance.address).parent
        assert folder == tmp_path / "run" / "wow-coach"
        assert folder.stat().st_mode & 0o777 == 0o700
    finally:
        instance.close()


def test_a_folder_that_is_really_a_link_is_not_trusted(tmp_path: Path) -> None:
    # Somebody swapped our folder for a link to a place they control: do not listen there.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "wow-coach").symlink_to(elsewhere, target_is_directory=True)
    instance = make_instance(tmp_path)
    try:
        assert instance.claim() is True  # the app still runs
        assert list(elsewhere.iterdir()) == []  # but no socket was made there
    finally:
        instance.close()


def test_the_socket_folder_follows_the_system() -> None:
    runtime = {"XDG_RUNTIME_DIR": "/run/user/1000"}
    assert socket_folder(runtime, "linux") == Path("/run/user/1000/wow-coach")
    assert socket_folder({}, "linux", user_id=1000, fallback_root=Path("/t")) == Path(
        "/t/wow-coach-1000"
    )
    assert socket_folder(runtime, "win32") is None  # Windows uses a named pipe


def test_a_long_runtime_folder_falls_back_to_a_short_one() -> None:
    long_runtime = {"XDG_RUNTIME_DIR": "/very/" + "long/" * 30}
    address = socket_address("wow-coach-me", long_runtime, "linux", fallback_root=Path("/t"))
    assert len(address) < 100
    assert address.startswith("/t/wow-coach-")


def test_the_default_name_is_per_user() -> None:
    assert default_name().startswith("wow-coach-")


# ---- tray and closing ---------------------------------------------------------------------


def _settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "desktop.ini"), QSettings.Format.IniFormat)


def _window_with_tray(
    qtbot: QtBot, tmp_path: Path, *, available: bool
) -> tuple[MainWindow, AppTray]:
    bridge, _core = make_bridge()
    tray = AppTray(_settings(tmp_path), available=available)
    window = MainWindow(bridge, tray=tray)
    qtbot.addWidget(window)
    return window, tray


def test_closing_hides_to_the_tray_and_tells_the_player_once(qtbot: QtBot, tmp_path: Path) -> None:
    window, tray = _window_with_tray(qtbot, tmp_path, available=True)
    window.show()
    window.close()
    assert not window.isVisible()
    assert tray.last_message == TRAY_MESSAGE
    tray.last_message = ""
    window.show()
    window.close()
    assert tray.last_message == ""  # the second time there is no message
    again = AppTray(_settings(tmp_path), available=True)
    again.hint_once()
    assert again.last_message == ""  # remembered for the next start too


def test_the_tray_menu_opens_the_window(qtbot: QtBot, tmp_path: Path) -> None:
    window, tray = _window_with_tray(qtbot, tmp_path, available=True)
    names = [action.text() for action in tray.menu.actions() if not action.isSeparator()]
    assert names == ["Open WoW Coach", "Quit"]
    window.hide()
    tray.menu.actions()[0].trigger()
    assert window.isVisible()


def test_quit_really_closes_instead_of_hiding(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window, tray = _window_with_tray(qtbot, tmp_path, available=True)
    quits: list[bool] = []
    monkeypatch.setattr(QApplication, "quit", lambda: quits.append(True))
    window.show()
    tray.quit_requested.emit()
    assert quits == [True]
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


def test_without_a_tray_closing_quits(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window, tray = _window_with_tray(qtbot, tmp_path, available=False)
    quits: list[bool] = []
    monkeypatch.setattr(QApplication, "quit", lambda: quits.append(True))
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()
    assert quits == [True]
    assert tray.last_message == ""


def test_clicking_the_tray_icon_opens_the_window(qtbot: QtBot, tmp_path: Path) -> None:
    _window, tray = _window_with_tray(qtbot, tmp_path, available=True)
    with qtbot.waitSignal(tray.open_requested, timeout=1000):
        tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
    with qtbot.assertNotEmitted(tray.open_requested):
        tray._on_activated(QSystemTrayIcon.ActivationReason.Context)
