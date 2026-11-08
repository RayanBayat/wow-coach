"""The desktop app's foundations: the typed state, the bridge, the window and the theme."""

from desktop_support import KEY, FakeCore, make_bridge, sample_state
from pytestqt.qtbot import QtBot

from wow_coach.desktop.main_window import MainWindow
from wow_coach.desktop.run import platform_arguments
from wow_coach.desktop.state import StateView, read_state
from wow_coach.desktop.theme import DARK, LIGHT, stylesheet

# ---- the typed state -----------------------------------------------------------------


def test_read_state_reads_a_full_state() -> None:
    view = read_state(sample_state())
    assert view.signed_in is True
    assert view.selected == KEY
    assert view.answers[0].title == "Train your new spells"
    assert view.answers[0].steps == ("Hearth to Brill", "Visit the mage trainer")
    assert view.usage.hour_cap == 30
    assert view.last_save == 1_000


def test_read_state_turns_junk_into_safe_defaults() -> None:
    junk: dict[str, object] = {
        "signed_in": "yes",
        "characters": "not a list",
        "answers": [42, {"title": 7, "steps": ["ok", 3]}],
        "usage": None,
        "last_save": True,
        "alerts": {"notify": False},
        "problem": "",
    }
    view = read_state(junk)
    assert view.signed_in is False
    assert view.characters == ()
    assert len(view.answers) == 1
    assert view.answers[0].title == ""
    assert view.answers[0].steps == ("ok",)
    assert view.usage.last_hour == 0
    assert view.last_save is None
    assert view.notify_available is False
    assert view.problem is None


# ---- the bridge ----------------------------------------------------------------------


def test_bridge_reads_the_state_and_emits_it(qtbot: QtBot) -> None:
    bridge, _core = make_bridge()
    with qtbot.waitSignal(bridge.state_changed) as signal:
        bridge.refresh_state()
    assert isinstance(signal.args[0], StateView)
    assert bridge.latest_state.selected == KEY


def test_bridge_turns_a_failing_read_into_a_problem_sentence(qtbot: QtBot) -> None:
    class BrokenCore(FakeCore):
        def state(self, wanted_character: str | None) -> dict[str, object]:
            raise RuntimeError(f"disk on fire while reading {wanted_character}")

    bridge, _core = make_bridge(BrokenCore())
    with qtbot.waitSignal(bridge.state_changed) as signal:
        bridge.refresh_state()
    assert signal.args[0].problem is not None


def test_bridge_forwards_core_events_and_rereads_the_state(qtbot: QtBot) -> None:
    bridge, core = make_bridge()
    bridge.start()
    try:
        reads_before = len(core.state_reads)
        with qtbot.waitSignal(bridge.event_arrived) as signal:
            core.bus.publish("info", {"text": "hello"})
        assert signal.args == ["info", {"text": "hello"}]
        qtbot.waitUntil(lambda: len(core.state_reads) > reads_before)
    finally:
        bridge.stop()


def test_bridge_asks_about_the_selected_character() -> None:
    bridge, core = make_bridge()
    bridge.select_character("Other-Realm")
    assert bridge.ask("Where next?") is True
    assert core.asked == [("Where next?", "Other-Realm")]
    assert core.state_reads[-1] == "Other-Realm"


def test_bridge_says_when_the_coach_is_busy() -> None:
    bridge, _core = make_bridge(FakeCore(busy=True))
    assert bridge.ask("Where next?") is False


def test_bridge_loads_models_and_signs_out_in_the_background(qtbot: QtBot) -> None:
    bridge, core = make_bridge()
    with qtbot.waitSignal(bridge.models_loaded) as models:
        bridge.load_models()
    assert models.args[0][0]["slug"] == "gpt-test-terra"
    with qtbot.waitSignal(bridge.signed_out) as out:
        bridge.sign_out()
    assert out.args == [True]
    assert core.sign_outs == 1


# ---- the window ----------------------------------------------------------------------


def test_window_lists_every_page_and_switches_between_them(qtbot: QtBot) -> None:
    bridge, _core = make_bridge()
    window = MainWindow(bridge)
    qtbot.addWidget(window)
    names = [page.name for page in window.pages]
    assert names == ["coach", "settings", "chatgpt", "setup", "privacy"]
    window.show_page("settings")
    page = window.current_page()
    assert page is not None
    assert page.name == "settings"
    window.show_page("no-such-page")
    page = window.current_page()
    assert page is not None
    assert page.name == "settings"


def test_window_hands_new_state_to_the_pages(qtbot: QtBot) -> None:
    seen: list[StateView] = []
    bridge, _core = make_bridge()
    window = MainWindow(bridge)
    qtbot.addWidget(window)
    window.pages[0].show_state = seen.append  # type: ignore[method-assign]  # spy on one page
    bridge.refresh_state()
    assert seen
    assert seen[-1].selected == KEY


# ---- the theme and the platform --------------------------------------------------------


def test_both_color_schemes_make_a_stylesheet() -> None:
    assert DARK.accent in stylesheet(DARK)
    assert LIGHT.accent in stylesheet(LIGHT)


def test_wayland_with_xwayland_runs_as_an_x11_app_so_keep_on_top_works() -> None:
    environ = {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}
    assert platform_arguments(environ, "linux") == ["-platform", "xcb"]


def test_the_players_own_qt_platform_choice_wins() -> None:
    environ = {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0", "QT_QPA_PLATFORM": "wayland"}
    assert platform_arguments(environ, "linux") == []


def test_other_systems_need_no_extra_arguments() -> None:
    assert platform_arguments({"DISPLAY": ":0"}, "win32") == []
    assert platform_arguments({"XDG_SESSION_TYPE": "wayland"}, "linux") == []
