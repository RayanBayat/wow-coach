"""The overlay hotkey: one key, pressed anywhere, that shows or hides the overlay.

The game owns the keyboard while the player plays, so an ordinary window never hears a key
press. A *global* hotkey asks the operating system to tell us about one key, whichever
program has the keyboard. Every system does it differently, so this file hides that behind
one small class, ``GlobalHotkey``:

* **Linux**: ``PortalHotkey`` asks the desktop's global-shortcuts *portal* (see
  ``portal_bus.py``). KDE shows its own question the first time. This is the polite, official
  way, and it works on Wayland, where programs may not grab keys by themselves.
* **Windows**: ``WindowsHotkey`` uses the ``RegisterHotKey`` system call.
* **macOS** and anything else: ``UnavailableHotkey``. There is no global hotkey there yet; the
  tray menu and the ``wow-coach-app --toggle-overlay`` command still work.

None of this touches the game: we only ask the system to tell *us* about a key press. We never
send keys to the game, read its memory or look at its window.

Each hotkey has a ``status`` (``HotkeyStatus``) that the Setup page shows in plain words.
"""

import ctypes
import logging
import secrets
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Protocol

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray, QCoreApplication, QObject, Signal

from wow_coach.desktop.portal_bus import LibDBusPortal, PortalConnection, PortalError

_log = logging.getLogger(__name__)

SHORTCUT_ID: Final = "toggle-overlay"
SHORTCUT_DESCRIPTION: Final = "Show or hide the WoW Coach overlay"


class HotkeyState(Enum):
    """Where the hotkey is in its life."""

    OFF = "off"  # not asked for yet, or switched off again
    STARTING = "starting"  # waiting for the desktop (it may be asking the player)
    ACTIVE = "active"  # pressing the key toggles the overlay
    UNAVAILABLE = "unavailable"  # this computer cannot do it; ``message`` says why


@dataclass(frozen=True, slots=True)
class HotkeyStatus:
    """The hotkey's state and one sentence for the player."""

    state: HotkeyState
    message: str = ""

    @property
    def active(self) -> bool:
        """True when pressing the key works."""
        return self.state is HotkeyState.ACTIVE


class GlobalHotkey(QObject):
    """A key that works everywhere. Subclasses talk to one operating system."""

    # The player pressed the key.
    activated = Signal()
    # ``status`` changed (the Setup page redraws).
    status_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._status = HotkeyStatus(HotkeyState.OFF)
        self._sequence = ""

    @property
    def status(self) -> HotkeyStatus:
        """What the hotkey is doing now."""
        return self._status

    @property
    def sequence(self) -> str:
        """The key asked for last, in Qt's text ("Ctrl+Shift+Space"), or ""."""
        return self._sequence

    def register(self, sequence: str) -> None:
        """Start listening for ``sequence``. A running registration is replaced."""
        raise NotImplementedError

    def unregister(self) -> None:
        """Stop listening."""
        raise NotImplementedError

    def _set_status(self, state: HotkeyState, message: str = "") -> None:
        status = HotkeyStatus(state, message)
        if status != self._status:
            self._status = status
            self.status_changed.emit()


class UnavailableHotkey(GlobalHotkey):
    """For computers with no way to do it (macOS, or Linux without the portal)."""

    def __init__(self, reason: str) -> None:
        super().__init__()
        self._reason = reason

    def register(self, sequence: str) -> None:
        self._sequence = sequence
        self._set_status(HotkeyState.UNAVAILABLE, self._reason)

    def unregister(self) -> None:
        self._set_status(HotkeyState.OFF)


# ---- turning "Ctrl+Shift+Space" into what each system wants -------------------------------

_MODIFIER_NAMES: Final = {"ctrl": "ctrl", "control": "ctrl", "shift": "shift", "alt": "alt"}
_META_NAMES: Final = {"meta", "win", "windows", "super", "cmd"}

# Qt's key names that differ from the names the freedesktop portal uses (X11 key names).
_PORTAL_KEYS: Final = {
    "esc": "Escape",
    "return": "Return",
    "enter": "Return",
    "backspace": "BackSpace",
    "del": "Delete",
    "ins": "Insert",
    "pgup": "Prior",
    "pgdown": "Next",
    "space": "space",
    "tab": "Tab",
    "home": "Home",
    "end": "End",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
}

# Windows "virtual key codes" for the named keys (letters and digits are their own code).
_WINDOWS_KEYS: Final = {
    "space": 0x20,
    "tab": 0x09,
    "return": 0x0D,
    "enter": 0x0D,
    "esc": 0x1B,
    "backspace": 0x08,
    "pgup": 0x21,
    "pgdown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "ins": 0x2D,
    "del": 0x2E,
}
_MOD_ALT: Final = 0x0001
_MOD_CONTROL: Final = 0x0002
_MOD_SHIFT: Final = 0x0004
_MOD_WIN: Final = 0x0008
_MOD_NOREPEAT: Final = 0x4000  # holding the key down must not toggle again and again
_FUNCTION_KEY_BASE: Final = 0x70  # F1


@dataclass(frozen=True, slots=True)
class ParsedKey:
    """A key chord split into its parts: modifiers (lowercase) and the main key as typed."""

    modifiers: frozenset[str]
    key: str


def parse_sequence(sequence: str) -> ParsedKey | None:
    """Split "Ctrl+Shift+Space" into modifiers and key. None when it has no main key."""
    parts = [part.strip() for part in sequence.split("+")]
    if len(parts) >= 2 and parts[-1] == "" and parts[-2] == "":
        parts = [*parts[:-2], "+"]  # "Ctrl++" means Ctrl and the plus key
    modifiers: set[str] = set()
    key = ""
    for part in parts:
        lowered = part.lower()
        if lowered in _MODIFIER_NAMES:
            modifiers.add(_MODIFIER_NAMES[lowered])
        elif lowered in _META_NAMES:
            modifiers.add("meta")
        elif part and not key:
            key = part
        else:
            return None  # two main keys, or an empty piece
    return ParsedKey(frozenset(modifiers), key) if key else None


def portal_trigger(sequence: str) -> str | None:
    """The trigger text the portal wants ("CTRL+SHIFT+space"), or None if it cannot be made."""
    parsed = parse_sequence(sequence)
    if parsed is None:
        return None
    order = ("ctrl", "alt", "shift", "meta")
    names = {"ctrl": "CTRL", "alt": "ALT", "shift": "SHIFT", "meta": "LOGO"}
    pieces = [names[name] for name in order if name in parsed.modifiers]
    key = _PORTAL_KEYS.get(parsed.key.lower())
    if key is None:
        key = parsed.key.lower() if len(parsed.key) == 1 else parsed.key.upper()
    return "+".join([*pieces, key])


def windows_key(sequence: str) -> tuple[int, int] | None:
    """(modifier flags, virtual key code) for ``RegisterHotKey``, or None if unknown."""
    parsed = parse_sequence(sequence)
    if parsed is None:
        return None
    flags = _MOD_NOREPEAT
    for name, flag in (
        ("ctrl", _MOD_CONTROL),
        ("alt", _MOD_ALT),
        ("shift", _MOD_SHIFT),
        ("meta", _MOD_WIN),
    ):
        if name in parsed.modifiers:
            flags |= flag
    lowered = parsed.key.lower()
    if lowered in _WINDOWS_KEYS:
        return flags, _WINDOWS_KEYS[lowered]
    if len(parsed.key) == 1 and parsed.key.isascii() and parsed.key.isalnum():
        return flags, ord(parsed.key.upper())
    if lowered.startswith("f") and lowered[1:].isdigit() and 1 <= int(lowered[1:]) <= 24:
        return flags, _FUNCTION_KEY_BASE + int(lowered[1:]) - 1
    return None


# ---- Linux: the global-shortcuts portal ---------------------------------------------------

PORTAL_MISSING: Final = (
    "This desktop does not offer the global-shortcuts portal, so WoW Coach cannot listen for "
    "a key by itself."
)
PORTAL_NO_DESKTOP_FILE: Final = (
    "The desktop did not accept the key. This usually means it does not know WoW Coach yet: "
    "add it to your app menu first (button above), then try again."
)
PORTAL_DECLINED: Final = "The key was not set up (you or the desktop said no)."
PORTAL_WAITING: Final = "Waiting for your desktop to confirm the key. A question may be showing."
PORTAL_BAD_KEY: Final = "That key cannot be used as a global hotkey."


def new_token(prefix: str) -> str:
    """A name only this run knows, safe to use as part of a D-Bus object path."""
    return f"{prefix}_{secrets.token_hex(6)}"


class PortalHotkey(GlobalHotkey):
    """A hotkey through the freedesktop global-shortcuts portal.

    How the portal talks, step by step (each ``Response`` arrives later, as a message):

    1. ``CreateSession``: "I'd like to register shortcuts." The answer holds the session.
    2. ``BindShortcuts``: "Please bind this key to this action." The desktop may ask the
       player; the answer says yes or no.
    3. Whenever the player presses the key the desktop sends ``Activated``.
    """

    def __init__(self, connect: Callable[[], PortalConnection]) -> None:
        """Create it.

        Args:
            connect: Opens the connection to the portal (raises ``PortalError``). Tests pass a
                function that returns a fake.
        """
        super().__init__()
        self._connect = connect
        self._connection: PortalConnection | None = None
        self._session: str | None = None
        self._create_token = ""
        self._bind_token = ""

    def register(self, sequence: str) -> None:
        self.unregister()
        self._sequence = sequence
        trigger = portal_trigger(sequence)
        if trigger is None:
            self._set_status(HotkeyState.UNAVAILABLE, PORTAL_BAD_KEY)
            return
        try:
            connection = self._connection or self._connect()
            self._connection = connection
            if connection.portal_version() is None:
                self._fail(PORTAL_MISSING)
                return
            connection.on_response = self._on_response
            connection.on_activated = self._on_activated
            self._create_token = new_token("create")
            self._bind_token = new_token("bind")
            self._set_status(HotkeyState.STARTING, PORTAL_WAITING)
            connection.create_session(self._create_token, new_token("session"))
        except PortalError as error:
            _log.info("The portal hotkey could not start: %s", error)
            self._fail(PORTAL_MISSING)

    def unregister(self) -> None:
        connection = self._connection
        session, self._session = self._session, None
        self._create_token = self._bind_token = ""
        if connection is not None:
            if session is not None:
                connection.close_session(session)
            connection.on_response = None
            connection.on_activated = None
        self._set_status(HotkeyState.OFF)

    def close(self) -> None:
        """Stop and hang up (the app is closing)."""
        self.unregister()
        connection, self._connection = self._connection, None
        if connection is not None:
            connection.close()

    def _fail(self, message: str) -> None:
        self._set_status(HotkeyState.UNAVAILABLE, message)

    def _on_response(self, request_path: str, code: int, results: Mapping[str, object]) -> None:
        token = request_path.rsplit("/", 1)[-1]
        if token == self._create_token:
            self._create_token = ""
            session = results.get("session_handle")
            if code != 0 or not isinstance(session, str):
                self._fail(PORTAL_DECLINED if code == 1 else PORTAL_MISSING)
                return
            self._session = session
            self._bind(session)
        elif token == self._bind_token:
            self._bind_token = ""
            if code == 0:
                self._set_status(HotkeyState.ACTIVE, _bound_message(results, self._sequence))
            else:
                self._fail(PORTAL_DECLINED if code == 1 else PORTAL_NO_DESKTOP_FILE)

    def _bind(self, session: str) -> None:
        connection = self._connection
        trigger = portal_trigger(self._sequence)
        if connection is None or trigger is None:
            return
        try:
            connection.bind_shortcut(
                session, SHORTCUT_ID, SHORTCUT_DESCRIPTION, trigger, self._bind_token
            )
        except PortalError as error:
            _log.info("The portal refused the shortcut: %s", error)
            self._fail(PORTAL_NO_DESKTOP_FILE)

    def _on_activated(self, session: str, shortcut_id: str) -> None:
        if session == self._session and shortcut_id == SHORTCUT_ID:
            self.activated.emit()


def _bound_message(results: Mapping[str, object], sequence: str) -> str:
    """ "Press X to ..." using the key the desktop says it bound (the player can change it)."""
    shown = sequence
    shortcuts = results.get("shortcuts")
    if isinstance(shortcuts, list) and shortcuts:
        first = shortcuts[0]
        if isinstance(first, tuple) and len(first) == 2 and isinstance(first[1], dict):
            description = first[1].get("trigger_description")
            if isinstance(description, str) and description:
                shown = description
    return f"Active. Press {shown} to show or hide the overlay."


# ---- Windows: RegisterHotKey --------------------------------------------------------------

WM_HOTKEY: Final = 0x0312
_WINDOWS_MESSAGE_TYPE: Final = b"windows_generic_MSG"
_HOTKEY_ID: Final = 0x57C0  # any number the program picks; it names this hotkey to Windows
WINDOWS_TAKEN: Final = (
    "Windows would not give us that key. Another program may already use it. "
    "Pick a different key in Settings."
)
WINDOWS_BAD_KEY: Final = "That key cannot be used as a global hotkey on Windows."


class Win32Hotkeys(Protocol):
    """The two Windows calls we need (a fake in tests)."""

    def register(self, hotkey_id: int, modifiers: int, key_code: int) -> bool:
        """``RegisterHotKey`` for this thread. True when Windows accepted the key."""

    def unregister(self, hotkey_id: int) -> None:
        """``UnregisterHotKey``."""


class RealWin32Hotkeys:
    """The real calls. Only ever created on Windows, so Linux and macOS never load them."""

    def __init__(self, platform: str = sys.platform) -> None:
        if platform != "win32":
            raise RuntimeError("Windows hotkeys exist only on Windows")
        windll: Any = ctypes.windll  # type: ignore[attr-defined,unused-ignore]
        self._user32: Any = windll.user32

    def register(self, hotkey_id: int, modifiers: int, key_code: int) -> bool:
        return bool(self._user32.RegisterHotKey(None, hotkey_id, modifiers, key_code))

    def unregister(self, hotkey_id: int) -> None:
        self._user32.UnregisterHotKey(None, hotkey_id)


class _Msg(ctypes.Structure):
    """The start of Windows' ``MSG`` structure (all we read is the message and wParam)."""

    _fields_ = (
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint32),
        ("wparam", ctypes.c_size_t),
        ("lparam", ctypes.c_ssize_t),
    )


class HotkeyMessageFilter(QAbstractNativeEventFilter):
    """Looks at Windows messages before Qt does and reports ``WM_HOTKEY`` ones."""

    def __init__(self, on_hotkey: Callable[[int], None]) -> None:
        super().__init__()
        self._on_hotkey = on_hotkey

    def nativeEventFilter(  # noqa: N802 - Qt's name
        self,
        eventType: QByteArray | bytes | bytearray | memoryview[int],  # noqa: N803 - Qt's name
        message: int,
    ) -> tuple[bool, int]:
        """Qt calls this for every native message. We never swallow one (``False``)."""
        kind = eventType.data() if isinstance(eventType, QByteArray) else bytes(eventType)
        if kind == _WINDOWS_MESSAGE_TYPE and message:
            msg = _Msg.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self._on_hotkey(int(msg.wparam))
        return False, 0


class WindowsHotkey(GlobalHotkey):
    """A hotkey through ``RegisterHotKey``."""

    def __init__(self, api: Win32Hotkeys | None = None) -> None:
        """Create it. ``api`` defaults to the real Windows calls."""
        super().__init__()
        self._api = api if api is not None else RealWin32Hotkeys()
        self._filter = HotkeyMessageFilter(self._on_message)
        self._installed = False
        self._registered = False

    def register(self, sequence: str) -> None:
        self.unregister()
        self._sequence = sequence
        chosen = windows_key(sequence)
        if chosen is None:
            self._set_status(HotkeyState.UNAVAILABLE, WINDOWS_BAD_KEY)
            return
        modifiers, key_code = chosen
        if not self._api.register(_HOTKEY_ID, modifiers, key_code):
            self._set_status(HotkeyState.UNAVAILABLE, WINDOWS_TAKEN)
            return
        self._registered = True
        self._install_filter()
        self._set_status(
            HotkeyState.ACTIVE, f"Active. Press {sequence} to show or hide the overlay."
        )

    def unregister(self) -> None:
        if self._registered:
            self._api.unregister(_HOTKEY_ID)
            self._registered = False
        self._set_status(HotkeyState.OFF)

    def _install_filter(self) -> None:
        app = QCoreApplication.instance()
        if app is not None and not self._installed:
            app.installNativeEventFilter(self._filter)
            self._installed = True

    def _on_message(self, hotkey_id: int) -> None:
        if hotkey_id == _HOTKEY_ID:
            self.activated.emit()


# ---- choosing the right one ---------------------------------------------------------------

MACOS_MESSAGE: Final = (
    "macOS has no global hotkey in WoW Coach yet. Use the tray menu, or the command below."
)
OTHER_MESSAGE: Final = "This system has no global hotkey in WoW Coach. Use the command below."


def create_hotkey(
    platform: str = sys.platform,
    *,
    connect_portal: Callable[[], PortalConnection] | None = None,
    windows_api: Win32Hotkeys | None = None,
) -> GlobalHotkey:
    """The right hotkey for this system.

    ``connect_portal`` and ``windows_api`` are for tests; the real ones are used otherwise.
    """
    if platform.startswith("linux"):
        if connect_portal is None:
            connect_portal = LibDBusPortal
        return PortalHotkey(connect_portal)
    if platform == "win32":
        return WindowsHotkey(windows_api)
    if platform == "darwin":
        return UnavailableHotkey(MACOS_MESSAGE)
    return UnavailableHotkey(OTHER_MESSAGE)
