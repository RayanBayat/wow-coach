"""The overlay hotkey: key-text conversion, the portal steps (with a fake), and Windows.

Nothing here talks to a real D-Bus, registers a real key or loads a Windows library.
"""

import ctypes
from collections.abc import Callable, Mapping

import pytest
from pytestqt.qtbot import QtBot

from wow_coach.desktop import hotkey
from wow_coach.desktop.hotkey import (
    HotkeyMessageFilter,
    HotkeyState,
    PortalHotkey,
    UnavailableHotkey,
    WindowsHotkey,
    create_hotkey,
    parse_sequence,
    portal_trigger,
    windows_key,
)
from wow_coach.desktop.portal_bus import PortalError

# ---- turning key text into what each system wants -----------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ctrl+Shift+Space", "CTRL+SHIFT+space"),
        ("Shift+Ctrl+Space", "CTRL+SHIFT+space"),
        ("Ctrl+Alt+F9", "CTRL+ALT+F9"),
        ("Meta+A", "LOGO+a"),
        ("Ctrl+Esc", "CTRL+Escape"),
        ("Ctrl+PgUp", "CTRL+Prior"),
        ("F12", "F12"),
    ],
)
def test_the_portal_trigger_text(text: str, expected: str) -> None:
    assert portal_trigger(text) == expected


@pytest.mark.parametrize("text", ["", "Ctrl+", "Ctrl+Shift", "A+B", "Ctrl+A+B"])
def test_a_key_without_one_main_key_is_refused(text: str) -> None:
    assert portal_trigger(text) is None
    assert windows_key(text) is None


def test_ctrl_plus_the_plus_key_is_understood() -> None:
    parsed = parse_sequence("Ctrl++")
    assert parsed is not None
    assert (parsed.modifiers, parsed.key) == (frozenset({"ctrl"}), "+")


def test_windows_key_codes() -> None:
    flags, code = windows_key("Ctrl+Shift+Space") or (0, 0)
    assert code == 0x20
    assert flags & 0x2 and flags & 0x4  # Ctrl and Shift
    assert flags & 0x4000  # no repeat while the key is held
    assert windows_key("Ctrl+Alt+F9") == (0x2 | 0x1 | 0x4000, 0x78)
    assert windows_key("Ctrl+K") == (0x2 | 0x4000, ord("K"))
    assert windows_key("Ctrl+Shift+Banana") is None


# ---- the portal, with a fake D-Bus --------------------------------------------------------


class FakePortal:
    """Stands in for the portal: records what we asked, and answers when the test says so."""

    def __init__(self, *, version: int | None = 2, fail_bind_call: bool = False) -> None:
        self.version = version
        self.fail_bind_call = fail_bind_call
        self.on_response: Callable[[str, int, Mapping[str, object]], None] | None = None
        self.on_activated: Callable[[str, str], None] | None = None
        self.calls: list[tuple[str, ...]] = []
        self.closed = False

    def portal_version(self) -> int | None:
        return self.version

    def create_session(self, handle_token: str, session_token: str) -> None:
        self.calls.append(("create", handle_token, session_token))

    def bind_shortcut(
        self, session: str, shortcut_id: str, description: str, trigger: str, handle_token: str
    ) -> None:
        if self.fail_bind_call:
            raise PortalError("App info not found")
        self.calls.append(("bind", session, shortcut_id, description, trigger, handle_token))

    def close_session(self, session: str) -> None:
        self.calls.append(("close", session))

    def close(self) -> None:
        self.closed = True

    # ---- what the test plays the desktop with ----

    def token_of(self, call: str) -> str:
        """The handle token of the first ``create`` or ``bind`` call."""
        index = 1 if call == "create" else 5
        return next(item[index] for item in self.calls if item[0] == call)

    def answer(self, call: str, code: int, results: Mapping[str, object]) -> None:
        assert self.on_response is not None
        path = f"/org/freedesktop/portal/desktop/request/1_2/{self.token_of(call)}"
        self.on_response(path, code, results)


SESSION = "/org/freedesktop/portal/desktop/session/1_2/mine"


def make_hotkey(portal: FakePortal) -> PortalHotkey:
    return PortalHotkey(lambda: portal)


def bring_up(portal: FakePortal, key: PortalHotkey) -> None:
    """Run the whole happy path: session created, shortcut bound."""
    key.register("Ctrl+Shift+Space")
    portal.answer("create", 0, {"session_handle": SESSION})
    portal.answer("bind", 0, {})


@pytest.mark.usefixtures("qtbot")
def test_the_portal_steps_create_a_session_then_bind_the_shortcut() -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    key.register("Ctrl+Shift+Space")
    assert key.status.state is HotkeyState.STARTING
    assert [call[0] for call in portal.calls] == ["create"]

    portal.answer("create", 0, {"session_handle": SESSION})
    bind = next(call for call in portal.calls if call[0] == "bind")
    assert bind[1:5] == (
        SESSION,
        "toggle-overlay",
        "Show or hide the WoW Coach overlay",
        "CTRL+SHIFT+space",
    )
    assert key.status.state is HotkeyState.STARTING  # not active until the desktop says yes

    portal.answer("bind", 0, {})
    assert key.status.active
    assert "Ctrl+Shift+Space" in key.status.message


@pytest.mark.usefixtures("qtbot")
def test_the_desktops_own_wording_of_the_key_is_shown() -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    key.register("Ctrl+Shift+Space")
    portal.answer("create", 0, {"session_handle": SESSION})
    shortcuts = [("toggle-overlay", {"trigger_description": "Ctrl+Alt+O"})]
    portal.answer("bind", 0, {"shortcuts": shortcuts})
    assert "Ctrl+Alt+O" in key.status.message


def test_activated_toggles(qtbot: QtBot) -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    bring_up(portal, key)
    assert portal.on_activated is not None
    with qtbot.waitSignal(key.activated, timeout=1000):
        portal.on_activated(SESSION, "toggle-overlay")


def test_another_session_or_shortcut_is_ignored(qtbot: QtBot) -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    bring_up(portal, key)
    heard: list[bool] = []
    key.activated.connect(lambda: heard.append(True))
    assert portal.on_activated is not None
    portal.on_activated("/some/other/session", "toggle-overlay")
    portal.on_activated(SESSION, "something-else")
    qtbot.wait(20)
    assert heard == []


@pytest.mark.usefixtures("qtbot")
def test_no_portal_falls_back_with_a_reason() -> None:
    key = make_hotkey(FakePortal(version=None))
    key.register("Ctrl+Shift+Space")
    assert key.status.state is HotkeyState.UNAVAILABLE
    assert "portal" in key.status.message


@pytest.mark.usefixtures("qtbot")
def test_no_session_bus_falls_back() -> None:
    def refuse() -> FakePortal:
        raise PortalError("no session bus")

    key = PortalHotkey(refuse)
    key.register("Ctrl+Shift+Space")
    assert key.status.state is HotkeyState.UNAVAILABLE


@pytest.mark.usefixtures("qtbot")
def test_the_player_saying_no_falls_back() -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    key.register("Ctrl+Shift+Space")
    portal.answer("create", 0, {"session_handle": SESSION})
    portal.answer("bind", 1, {})  # 1 = the player cancelled
    assert key.status.state is HotkeyState.UNAVAILABLE
    assert "not set up" in key.status.message


@pytest.mark.usefixtures("qtbot")
def test_a_desktop_that_does_not_know_the_app_falls_back_and_says_what_to_do() -> None:
    portal = FakePortal(fail_bind_call=True)
    key = make_hotkey(portal)
    key.register("Ctrl+Shift+Space")
    portal.answer("create", 0, {"session_handle": SESSION})
    assert key.status.state is HotkeyState.UNAVAILABLE
    assert "app menu" in key.status.message


@pytest.mark.usefixtures("qtbot")
def test_a_refused_bind_answer_falls_back() -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    key.register("Ctrl+Shift+Space")
    portal.answer("create", 0, {"session_handle": SESSION})
    portal.answer("bind", 2, {})  # 2 = something else went wrong
    assert key.status.state is HotkeyState.UNAVAILABLE
    assert "app menu" in key.status.message


@pytest.mark.usefixtures("qtbot")
def test_a_bad_key_is_refused_before_asking_the_desktop() -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    key.register("Ctrl+")
    assert key.status.state is HotkeyState.UNAVAILABLE
    assert portal.calls == []


@pytest.mark.usefixtures("qtbot")
def test_changing_the_key_closes_the_old_session_and_opens_a_new_one() -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    bring_up(portal, key)
    portal.calls.clear()
    key.register("Ctrl+Alt+F9")
    assert portal.calls[0] == ("close", SESSION)
    assert portal.calls[1][0] == "create"


@pytest.mark.usefixtures("qtbot")
def test_a_late_answer_for_an_old_registration_is_ignored() -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    key.register("Ctrl+Shift+Space")
    old_token = portal.token_of("create")
    key.register("Ctrl+Alt+F9")
    assert portal.on_response is not None
    portal.on_response(f"/x/request/1_2/{old_token}", 0, {"session_handle": SESSION})
    assert [call[0] for call in portal.calls].count("bind") == 0


@pytest.mark.usefixtures("qtbot")
def test_unregister_and_close_hang_up() -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    bring_up(portal, key)
    key.close()
    assert ("close", SESSION) in portal.calls
    assert portal.closed
    assert key.status.state is HotkeyState.OFF


# ---- Windows ------------------------------------------------------------------------------


class FakeWin32:
    def __init__(self, *, accept: bool = True) -> None:
        self.accept = accept
        self.registered: list[tuple[int, int, int]] = []
        self.unregistered: list[int] = []

    def register(self, hotkey_id: int, modifiers: int, key_code: int) -> bool:
        self.registered.append((hotkey_id, modifiers, key_code))
        return self.accept

    def unregister(self, hotkey_id: int) -> None:
        self.unregistered.append(hotkey_id)


def windows_message(message: int, wparam: int) -> tuple[bytes, int, ctypes.Structure]:
    """A native event like Qt hands to a filter: (event type, address of a MSG)."""
    msg = hotkey._Msg(None, message, wparam, 0)
    return b"windows_generic_MSG", ctypes.addressof(msg), msg


@pytest.mark.usefixtures("qtbot")
def test_windows_registers_the_key_and_unregisters_it() -> None:
    api = FakeWin32()
    key = WindowsHotkey(api)
    key.register("Ctrl+Shift+Space")
    assert key.status.active
    assert api.registered == [(0x57C0, 0x2 | 0x4 | 0x4000, 0x20)]
    key.register("Ctrl+Alt+F9")  # replacing releases the old key first
    assert api.unregistered == [0x57C0]
    key.unregister()
    assert api.unregistered == [0x57C0, 0x57C0]
    assert key.status.state is HotkeyState.OFF


@pytest.mark.usefixtures("qtbot")
def test_windows_key_taken_by_another_program_falls_back() -> None:
    key = WindowsHotkey(FakeWin32(accept=False))
    key.register("Ctrl+Shift+Space")
    assert key.status.state is HotkeyState.UNAVAILABLE
    assert "program may already" in key.status.message


def test_wm_hotkey_messages_toggle(qtbot: QtBot) -> None:
    key = WindowsHotkey(FakeWin32())
    key.register("Ctrl+Shift+Space")
    seen: list[int] = []
    message_filter = HotkeyMessageFilter(seen.append)
    kind, address, msg = windows_message(hotkey.WM_HOTKEY, 0x57C0)
    assert message_filter.nativeEventFilter(kind, address) == (False, 0)
    assert seen == [0x57C0]
    # Other messages, other event kinds and a missing message are left alone.
    other_kind, other_address, other = windows_message(0x0100, 0x57C0)
    message_filter.nativeEventFilter(other_kind, other_address)
    message_filter.nativeEventFilter(b"xcb_generic_event_t", address)
    message_filter.nativeEventFilter(kind, 0)
    assert seen == [0x57C0]
    del msg, other

    with qtbot.waitSignal(key.activated, timeout=1000):
        key._on_message(0x57C0)
    heard: list[bool] = []
    key.activated.connect(lambda: heard.append(True))
    key._on_message(1)  # not our key
    assert heard == []


def test_real_windows_calls_are_never_made_elsewhere() -> None:
    with pytest.raises(RuntimeError):
        hotkey.RealWin32Hotkeys("linux")


# ---- choosing -----------------------------------------------------------------------------


@pytest.mark.usefixtures("qtbot")
def test_each_system_gets_its_own_hotkey() -> None:
    portal = FakePortal()
    assert isinstance(create_hotkey("linux", connect_portal=lambda: portal), PortalHotkey)
    assert isinstance(create_hotkey("win32", windows_api=FakeWin32()), WindowsHotkey)
    mac = create_hotkey("darwin")
    assert isinstance(mac, UnavailableHotkey)
    mac.register("Ctrl+Shift+Space")
    assert mac.status.state is HotkeyState.UNAVAILABLE
    assert "macOS" in mac.status.message
    assert isinstance(create_hotkey("freebsd"), UnavailableHotkey)
