"""The desktop shell: icons, one instance only, the tray and closing the window."""

from pathlib import Path

import pytest
from desktop_support import make_bridge
from PySide6.QtCore import QSettings
from PySide6.QtGui import QCloseEvent
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from pytestqt.qtbot import QtBot

from wow_coach.desktop import icons
from wow_coach.desktop.main_window import MainWindow
from wow_coach.desktop.single_instance import SingleInstance, default_name
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


def test_the_second_copy_wakes_the_first_and_exits(qtbot: QtBot) -> None:
    first = SingleInstance("wow-coach-test-wake")
    second = SingleInstance("wow-coach-test-wake")
    try:
        assert first.claim() is True
        with qtbot.waitSignal(first.show_requested, timeout=3000):
            assert second.claim() is False
    finally:
        first.close()


def test_the_first_instance_raises_its_window(qtbot: QtBot) -> None:
    bridge, _core = make_bridge()
    window = MainWindow(bridge)
    qtbot.addWidget(window)
    first = SingleInstance("wow-coach-test-raise")
    try:
        assert first.claim()
        first.show_requested.connect(window.bring_to_front)
        assert not window.isVisible()
        assert SingleInstance("wow-coach-test-raise").claim() is False
        qtbot.waitUntil(window.isVisible, timeout=3000)
    finally:
        first.close()


@pytest.mark.usefixtures("qtbot")
def test_a_name_left_by_a_crash_is_cleaned_up() -> None:
    # A server that was not closed properly leaves its name behind; nobody answers on it.
    crashed = QLocalServer()
    assert crashed.listen("wow-coach-test-stale")
    crashed.close()
    fresh = SingleInstance("wow-coach-test-stale")
    try:
        assert fresh.claim() is True
    finally:
        fresh.close()


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
