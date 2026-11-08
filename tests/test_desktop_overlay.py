"""The overlay: the Coach page moves into the panel and back, geometry, opacity, Esc, hotkey.

Nothing here shows a real window on a screen (Qt draws offscreen), registers a real key or
touches the player's real settings (a temporary ``.ini`` file is used).
"""

import uuid
from pathlib import Path

import pytest
from desktop_support import make_bridge, sample_message, sample_state
from PySide6.QtCore import QPoint, QPointF, QSettings, QSize, Qt
from PySide6.QtWidgets import QLabel, QPushButton
from pytestqt.qtbot import QtBot

from wow_coach.app_settings import AppSettings, update_settings
from wow_coach.desktop.hotkey import GlobalHotkey, HotkeyState
from wow_coach.desktop.main_window import MainWindow
from wow_coach.desktop.overlay import (
    HINT_WITHOUT_KEY,
    MINIMUM_SIZE,
    OverlayController,
    OverlayPanel,
    clean_opacity,
)
from wow_coach.desktop.pages.coach import CoachPage
from wow_coach.desktop.single_instance import TOGGLE_OVERLAY_MESSAGE, SingleInstance
from wow_coach.desktop.state import read_state


class FakeHotkey(GlobalHotkey):
    """A hotkey that registers nothing; tests press it with ``press``."""

    def __init__(self) -> None:
        super().__init__()
        self.registered: list[str] = []
        self.unregistered = 0
        self.works = True

    def register(self, sequence: str) -> None:
        self.registered.append(sequence)
        self._sequence = sequence
        self._set_status(HotkeyState.ACTIVE if self.works else HotkeyState.UNAVAILABLE, "x")

    def unregister(self) -> None:
        self.unregistered += 1
        self._set_status(HotkeyState.OFF)

    def press(self) -> None:
        self.activated.emit()


def make_settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "overlay.ini"), QSettings.Format.IniFormat)


class Rig:
    """A main window, a fake hotkey and a controller, wired like the real app."""

    def __init__(self, qtbot: QtBot, tmp_path: Path) -> None:
        self.bridge, self.core = make_bridge()
        self.window = MainWindow(self.bridge)
        qtbot.addWidget(self.window)
        self.hotkey = FakeHotkey()
        self.settings = make_settings(tmp_path)
        self.panel = OverlayPanel(self.settings)
        qtbot.addWidget(self.panel)
        self.controller = OverlayController(self.window, self.hotkey, self.panel)
        self.bridge.state_changed.connect(self.controller.on_state)
        self.page = next(page for page in self.window.pages if isinstance(page, CoachPage))


@pytest.fixture
def rig(qtbot: QtBot, tmp_path: Path) -> Rig:
    return Rig(qtbot, tmp_path)


# ---- the page moves into the panel and back -----------------------------------------------


def test_showing_moves_the_one_coach_page_into_the_panel(rig: Rig) -> None:
    rig.window.show()
    assert rig.page.parent() is not rig.panel
    rig.controller.show_overlay()
    assert rig.panel.isVisible()
    assert rig.panel.page is rig.page
    assert rig.page.isVisible()
    assert rig.page.window() is rig.panel
    assert rig.controller.is_shown


def test_hiding_gives_the_page_back_to_its_place(rig: Rig) -> None:
    rig.window.show()
    stack_index = rig.window._stack.indexOf(rig.page)
    rig.controller.show_overlay()
    rig.controller.hide_overlay()
    assert not rig.panel.isVisible()
    assert rig.panel.page is None
    assert rig.page.window() is rig.window
    assert rig.window._stack.indexOf(rig.page) == stack_index
    assert rig.window._stack.currentWidget() is rig.page  # the Coach page is current again
    assert not rig.controller.is_shown


def test_the_main_window_shows_a_note_in_its_place_while_it_is_lent(rig: Rig) -> None:
    rig.window.show()
    rig.controller.show_overlay()
    current = rig.window._stack.currentWidget()
    assert current is not rig.page
    labels = [label.text() for label in current.findChildren(QLabel)]
    assert any("overlay" in text for text in labels)
    # The sidebar keeps working: clicking Coach again selects the note, not a missing page.
    rig.window.show_page("coach")
    assert rig.window._stack.currentWidget() is current
    rig.window.show_page("settings")
    assert rig.window.current_page() is not None
    assert rig.window.current_page().name == "settings"  # type: ignore[union-attr]
    rig.controller.hide_overlay()
    assert rig.window.current_page().name == "settings"  # type: ignore[union-attr]


def test_the_note_has_a_button_that_brings_the_page_back(rig: Rig, qtbot: QtBot) -> None:
    rig.window.show()
    rig.controller.show_overlay()
    button = rig.window._stack.currentWidget().findChild(QPushButton)
    assert button is not None
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert not rig.controller.is_shown
    assert rig.page.window() is rig.window


def test_the_page_keeps_receiving_state_while_in_the_overlay(rig: Rig) -> None:
    rig.controller.show_overlay()
    message = sample_message("Hello from the overlay test", message_id="m1", seconds=1_000)
    rig.core.raw_state = sample_state(conversation=[message])
    rig.bridge.refresh_state()
    assert any("Hello from the overlay test" in text for text in rig.page.chat.texts())


def test_toggle_shows_then_hides(rig: Rig) -> None:
    rig.controller.toggle()
    assert rig.panel.isVisible()
    rig.controller.toggle()
    assert not rig.panel.isVisible()


def test_showing_twice_is_harmless(rig: Rig) -> None:
    rig.controller.show_overlay()
    rig.controller.show_overlay()
    assert rig.panel.page is rig.page
    rig.controller.hide_overlay()
    rig.controller.hide_overlay()
    assert rig.page.window() is rig.window


def test_the_overlay_button_is_hidden_inside_the_panel(rig: Rig) -> None:
    rig.window.show()
    assert not rig.page.header.overlay_button.isHidden()
    rig.controller.show_overlay()
    assert rig.page.header.overlay_button.isHidden()
    rig.controller.hide_overlay()
    assert not rig.page.header.overlay_button.isHidden()


# ---- keyboard -----------------------------------------------------------------------------


def test_the_question_box_gets_the_keyboard_when_shown(rig: Rig, qtbot: QtBot) -> None:
    rig.controller.show_overlay()
    qtbot.waitUntil(
        lambda: rig.page.composer._edit.hasFocus() or rig.panel.isActiveWindow(), timeout=2000
    )
    # Offscreen windows may not become "active"; the box must at least be the panel's focus.
    assert rig.panel.focusWidget() is rig.page.composer._edit


def test_escape_hides_the_overlay(rig: Rig, qtbot: QtBot) -> None:
    rig.controller.show_overlay()
    qtbot.keyClick(rig.page.composer._edit, Qt.Key.Key_Escape)
    assert not rig.panel.isVisible()
    assert rig.page.window() is rig.window


def test_the_hide_button_hides(rig: Rig, qtbot: QtBot) -> None:
    rig.controller.show_overlay()
    qtbot.mouseClick(rig.panel.bar.hide_button, Qt.MouseButton.LeftButton)
    assert not rig.panel.isVisible()


def test_open_the_full_app_hides_and_raises_the_window(rig: Rig, qtbot: QtBot) -> None:
    rig.controller.show_overlay()
    qtbot.mouseClick(rig.panel.bar.open_app, Qt.MouseButton.LeftButton)
    assert not rig.panel.isVisible()
    assert rig.window.isVisible()


def test_a_page_button_that_needs_the_app_opens_it(rig: Rig) -> None:
    rig.controller.show_overlay()
    rig.page.navigate.emit("chatgpt")  # for example the "Sign in" card
    assert not rig.panel.isVisible()
    assert rig.window.isVisible()
    assert rig.window.current_page().name == "chatgpt"  # type: ignore[union-attr]


def test_nothing_shows_the_overlay_by_itself(rig: Rig) -> None:
    rig.core.raw_state = sample_state()
    rig.bridge.refresh_state()
    rig.page.on_event("answer", {"title": "A new answer", "steps": ["x"], "text": "t"})
    assert not rig.panel.isVisible()


# ---- the hotkey and other ways in ---------------------------------------------------------


def test_the_hotkey_toggles(rig: Rig) -> None:
    rig.hotkey.press()
    assert rig.panel.isVisible()
    rig.hotkey.press()
    assert not rig.panel.isVisible()


def test_the_overlay_button_on_the_page_toggles(rig: Rig, qtbot: QtBot) -> None:
    rig.window.show()
    qtbot.mouseClick(rig.page.header.overlay_button, Qt.MouseButton.LeftButton)
    assert rig.panel.isVisible()


def test_the_single_instance_message_toggles(rig: Rig, qtbot: QtBot, tmp_path: Path) -> None:
    environ = {
        "WOW_COACH_DATA_DIR": str(tmp_path / "data"),
        "XDG_RUNTIME_DIR": str(tmp_path / "run"),
    }
    # A name of its own: on Windows two programs may listen on one pipe name, so an earlier
    # test's listener could otherwise receive the message.
    name = f"overlay-test-{uuid.uuid4().hex[:8]}"
    first = SingleInstance(name, environ=environ)
    try:
        assert first.claim()
        first.toggle_overlay_requested.connect(rig.controller.toggle)
        with qtbot.waitSignal(first.toggle_overlay_requested, timeout=3000):
            assert SingleInstance(name, environ=environ).claim(TOGGLE_OVERLAY_MESSAGE) is False
        assert rig.panel.isVisible()
    finally:
        first.close()


def test_the_hint_names_the_key_only_when_it_works(rig: Rig) -> None:
    hints: list[str] = []
    rig.controller.hint_changed.connect(hints.append)
    rig.controller.start(AppSettings())
    assert "Ctrl+Shift+Space" in hints[-1]
    assert "Ctrl+Shift+Space" in rig.page.header.overlay_button.toolTip()
    rig.hotkey.works = False
    rig.controller.apply(update_settings(AppSettings(), {"overlay_hotkey": "Ctrl+Alt+F9"}))
    assert hints[-1] == HINT_WITHOUT_KEY


# ---- settings -----------------------------------------------------------------------------


def test_start_registers_the_saved_key_and_applies_the_opacity(rig: Rig) -> None:
    rig.controller.start(
        update_settings(AppSettings(), {"overlay_hotkey": "Ctrl+Alt+F9", "overlay_opacity": 70})
    )
    assert rig.hotkey.registered == ["Ctrl+Alt+F9"]
    assert rig.panel.opacity_percent == 70
    assert rig.panel.windowOpacity() == pytest.approx(0.70, abs=0.005)


def test_the_key_is_only_registered_again_when_it_changed(rig: Rig) -> None:
    rig.controller.start(AppSettings())
    rig.controller.apply(AppSettings())
    assert rig.hotkey.registered == ["Ctrl+Shift+Space"]
    rig.controller.apply(update_settings(AppSettings(), {"overlay_hotkey": "Ctrl+Alt+F9"}))
    assert rig.hotkey.registered == ["Ctrl+Shift+Space", "Ctrl+Alt+F9"]


def test_a_new_state_with_new_settings_changes_the_overlay(rig: Rig) -> None:
    rig.core.raw_state = sample_state(
        settings={"overlay_hotkey": "Ctrl+Alt+F8", "overlay_opacity": 65}
    )
    rig.bridge.refresh_state()
    assert rig.hotkey.registered == ["Ctrl+Alt+F8"]
    assert rig.panel.opacity_percent == 65


def test_a_state_without_settings_changes_nothing(rig: Rig) -> None:
    rig.controller.on_state(read_state(sample_state(settings={})))
    rig.controller.on_state("not a state")
    assert rig.hotkey.registered == []


@pytest.mark.parametrize(
    ("given", "expected"),
    [(60, 60), (100, 100), (92, 92), (59, 92), (101, 92), ("80", 92), (None, 92), (True, 92)],
)
def test_opacity_is_validated(given: object, expected: int) -> None:
    assert clean_opacity(given) == expected


def test_the_panel_ignores_a_bad_opacity(qtbot: QtBot, tmp_path: Path) -> None:
    panel = OverlayPanel(make_settings(tmp_path))
    qtbot.addWidget(panel)
    panel.set_opacity_percent(10)
    assert panel.opacity_percent == 92
    panel.set_opacity_percent(75)
    assert panel.opacity_percent == 75


def test_closing_hides_the_overlay_and_lets_go_of_the_key(rig: Rig) -> None:
    rig.controller.show_overlay()
    rig.controller.close()
    assert not rig.panel.isVisible()
    assert rig.hotkey.unregistered == 1


# ---- the panel's own behavior -------------------------------------------------------------


def test_the_panel_is_a_frameless_always_on_top_tool_window(qtbot: QtBot, tmp_path: Path) -> None:
    panel = OverlayPanel(make_settings(tmp_path))
    qtbot.addWidget(panel)
    flags = panel.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.Tool
    assert panel.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert panel.windowOpacity() == pytest.approx(0.92, abs=0.005)  # the default


def test_the_first_time_the_panel_sits_inside_the_screen(qtbot: QtBot, tmp_path: Path) -> None:
    panel = OverlayPanel(make_settings(tmp_path))
    qtbot.addWidget(panel)
    panel.show_for_typing()
    screen = panel.screen().availableGeometry()
    assert screen.contains(panel.geometry())
    assert panel.width() <= 520
    assert panel.width() >= MINIMUM_SIZE[0]
    # On the right part of the screen.
    assert panel.geometry().center().x() > screen.center().x()


def test_the_panel_remembers_its_size_and_place(qtbot: QtBot, tmp_path: Path) -> None:
    first = OverlayPanel(make_settings(tmp_path))
    qtbot.addWidget(first)
    first.show_for_typing()
    first.resize(410, 480)
    first.move(QPoint(30, 40))
    first.hide()
    saved = make_settings(tmp_path)
    assert saved.value("overlay/size") == QSize(410, 480)
    assert saved.value("overlay/position") == QPoint(30, 40)

    second = OverlayPanel(make_settings(tmp_path))
    qtbot.addWidget(second)
    second.show_for_typing()
    assert second.size() == QSize(410, 480)
    assert second.pos() == QPoint(30, 40)


def test_a_saved_place_off_every_screen_is_not_used(qtbot: QtBot, tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.setValue("overlay/position", QPoint(-30_000, -30_000))
    settings.setValue("overlay/size", QSize(100_000, 100_000))
    panel = OverlayPanel(settings)
    qtbot.addWidget(panel)
    panel.show_for_typing()
    screen = panel.screen().availableGeometry()
    assert screen.contains(panel.geometry())


def test_edges_and_corners_are_resize_handles(qtbot: QtBot, tmp_path: Path) -> None:
    panel = OverlayPanel(make_settings(tmp_path))
    qtbot.addWidget(panel)
    panel.resize(500, 600)
    assert panel._edges_at(QPointF(250, 300)) == Qt.Edge(0)
    assert panel._edges_at(QPointF(2, 300)) == Qt.Edge.LeftEdge
    assert panel._edges_at(QPointF(498, 300)) == Qt.Edge.RightEdge
    assert panel._edges_at(QPointF(250, 2)) == Qt.Edge.TopEdge
    assert panel._edges_at(QPointF(498, 598)) == Qt.Edge.RightEdge | Qt.Edge.BottomEdge


def test_the_page_is_see_through_inside_the_panel(rig: Rig) -> None:
    rig.controller.show_overlay()
    assert "transparent" in rig.panel.styleSheet()
