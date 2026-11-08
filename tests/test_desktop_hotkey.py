"""The overlay hotkey: key-text conversion, the portal steps (with a fake), and Windows.

Nothing here talks to a real D-Bus, registers a real key or loads a Windows library.
"""

import ctypes
import threading
from collections.abc import Callable

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
from wow_coach.desktop.portal_types import (
    PortalActivated,
    PortalBound,
    PortalError,
    PortalEvent,
    PortalFailed,
    PortalFailure,
    ShortcutRequest,
)

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


# ---- the portal, with a fake portal client ------------------------------------------------


class FakePortal:
    """Stands in for the portal client: records the request, and reports when the test says so."""

    def __init__(self) -> None:
        self.request: ShortcutRequest | None = None
        self.report: Callable[[PortalEvent], None] | None = None
        self.closed = False

    def start(self, request: ShortcutRequest, report: Callable[[PortalEvent], None]) -> None:
        self.request = request
        self.report = report

    def close(self) -> None:
        self.closed = True

    def say(self, event: PortalEvent) -> None:
        """Play the portal: report ``event`` to the hotkey."""
        assert self.report is not None
        self.report(event)


def make_hotkey(portal: FakePortal) -> PortalHotkey:
    return PortalHotkey(lambda: portal)


def bring_up(portal: FakePortal, key: PortalHotkey) -> None:
    """Run the happy path: the desktop accepted the shortcut."""
    key.register("Ctrl+Shift+Space")
    portal.say(PortalBound())


@pytest.mark.usefixtures("qtbot")
def test_registering_asks_the_portal_for_the_shortcut_and_waits() -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    key.register("Ctrl+Shift+Space")
    assert portal.request == ShortcutRequest(
        "toggle-overlay", "Show or hide the WoW Coach overlay", "CTRL+SHIFT+space"
    )
    assert key.status.state is HotkeyState.STARTING  # not active until the desktop says yes

    portal.say(PortalBound())
    assert key.status.active
    assert "Ctrl+Shift+Space" in key.status.message


@pytest.mark.usefixtures("qtbot")
def test_the_desktops_own_wording_of_the_key_is_shown() -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    key.register("Ctrl+Shift+Space")
    portal.say(PortalBound("Ctrl+Alt+O"))
    assert "Ctrl+Alt+O" in key.status.message


def test_activated_toggles(qtbot: QtBot) -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    bring_up(portal, key)
    with qtbot.waitSignal(key.activated, timeout=1000):
        portal.say(PortalActivated())


def test_a_report_from_the_portals_thread_reaches_the_qt_thread(qtbot: QtBot) -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    bring_up(portal, key)
    threads: list[threading.Thread] = []
    key.activated.connect(lambda: threads.append(threading.current_thread()))
    worker = threading.Thread(target=lambda: portal.say(PortalActivated()))
    with qtbot.waitSignal(key.activated, timeout=2000):
        worker.start()
    worker.join()
    assert threads == [threading.main_thread()]


def test_a_press_before_the_desktop_said_yes_is_ignored(qtbot: QtBot) -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    key.register("Ctrl+Shift+Space")
    heard: list[bool] = []
    key.activated.connect(lambda: heard.append(True))
    portal.say(PortalActivated())
    qtbot.wait(20)
    assert heard == []


@pytest.mark.parametrize(
    ("reason", "words"),
    [
        (PortalFailure.UNAVAILABLE, "portal"),
        (PortalFailure.DECLINED, "not set up"),
        (PortalFailure.REFUSED, "app menu"),
        (PortalFailure.TIMED_OUT, "did not answer"),
    ],
)
@pytest.mark.usefixtures("qtbot")
def test_every_failure_becomes_a_plain_status(reason: PortalFailure, words: str) -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    key.register("Ctrl+Shift+Space")
    portal.say(PortalFailed(reason))
    assert key.status.state is HotkeyState.UNAVAILABLE
    assert words in key.status.message


@pytest.mark.usefixtures("qtbot")
def test_no_portal_client_falls_back() -> None:
    def refuse() -> FakePortal:
        raise PortalError("jeepney is missing")

    key = PortalHotkey(refuse)
    key.register("Ctrl+Shift+Space")
    assert key.status.state is HotkeyState.UNAVAILABLE


@pytest.mark.usefixtures("qtbot")
def test_a_bad_key_is_refused_before_asking_the_desktop() -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    key.register("Ctrl+")
    assert key.status.state is HotkeyState.UNAVAILABLE
    assert portal.request is None


@pytest.mark.usefixtures("qtbot")
def test_changing_the_key_closes_the_old_connection_and_starts_a_new_one() -> None:
    portals = [FakePortal(), FakePortal()]
    first, second = portals[1], portals[0]  # `pop` hands out the last one first
    key = PortalHotkey(portals.pop)
    key.register("Ctrl+Shift+Space")
    key.register("Ctrl+Alt+F9")
    assert first.closed
    assert second.request is not None
    assert second.request.trigger == "CTRL+ALT+F9"


@pytest.mark.usefixtures("qtbot")
def test_a_late_report_from_an_old_connection_is_ignored() -> None:
    portals = [FakePortal(), FakePortal()]
    key = PortalHotkey(portals.pop)
    old, new = portals[1], portals[0]
    key.register("Ctrl+Shift+Space")  # takes `old`
    key.register("Ctrl+Alt+F9")  # takes `new`
    old.say(PortalBound())
    assert key.status.state is HotkeyState.STARTING
    new.say(PortalBound())
    assert key.status.active


@pytest.mark.usefixtures("qtbot")
def test_unregister_and_close_hang_up() -> None:
    portal = FakePortal()
    key = make_hotkey(portal)
    bring_up(portal, key)
    key.close()
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
