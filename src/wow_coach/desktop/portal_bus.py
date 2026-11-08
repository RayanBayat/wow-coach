"""A very small client for the "global shortcuts" portal of a Linux desktop.

A *portal* is a service every modern Linux desktop offers over D-Bus (the system that lets
programs talk to each other). The ``org.freedesktop.portal.GlobalShortcuts`` portal is the
polite way to ask the desktop: "please tell me when the player presses this key, even while
another program (the game) has the keyboard."

Why not Qt's own D-Bus classes (``QtDBus``)? The call that registers a shortcut
(``BindShortcuts``) needs a list of structures (``a(sa{sv})`` in D-Bus's type language), and
Qt for Python cannot build one. Worse, a wrong guess makes libdbus abort the whole program.
So this file talks to ``libdbus`` (the C library Qt's D-Bus support is built on) with
``ctypes``, and only does what the portal needs:

* ask for a session and bind one shortcut,
* receive the portal's two kinds of messages (``Response`` and ``Activated``).

The rest of the app only sees the small ``PortalConnection`` interface, so tests use a fake
and never touch a real D-Bus. This module is only loaded on Linux.
"""

import ctypes
import ctypes.util
import logging
from collections.abc import Callable, Mapping
from typing import Any, Final, NamedTuple, Protocol

from PySide6.QtCore import QObject, QSocketNotifier

_log = logging.getLogger(__name__)

PORTAL_SERVICE: Final = "org.freedesktop.portal.Desktop"
PORTAL_PATH: Final = "/org/freedesktop/portal/desktop"
SHORTCUTS_INTERFACE: Final = "org.freedesktop.portal.GlobalShortcuts"
REQUEST_INTERFACE: Final = "org.freedesktop.portal.Request"
SESSION_INTERFACE: Final = "org.freedesktop.portal.Session"
CALL_TIMEOUT_MS: Final = 3000  # the portal answers a call at once; the user's answer comes later

# D-Bus type letters, as numbers (libdbus wants the character code).
_STRING = ord("s")
_OBJECT_PATH = ord("o")
_SIGNATURE = ord("g")
_VARIANT = ord("v")
_ARRAY = ord("a")
_STRUCT = ord("r")
_DICT_ENTRY = ord("e")
_BASIC_NUMBERS: Final = {ord(letter): letter for letter in "ybnqiuxtd"}
_BOOLEAN = ord("b")

_SESSION_BUS = 0
_MESSAGE_ERROR = 3
_MESSAGE_SIGNAL = 4


class PortalError(Exception):
    """The portal or the D-Bus connection could not be used. The text is for the log."""


class PortalConnection(Protocol):
    """What the hotkey needs from the portal. Real: ``LibDBusPortal``. Tests: a fake.

    The two handlers are called later, when the portal sends a message:

    * ``on_response(request_path, code, results)``: the answer to a request (code 0 = yes,
      1 = the player said no, 2 = something else went wrong).
    * ``on_activated(session_path, shortcut_id)``: the player pressed the key.
    """

    on_response: Callable[[str, int, Mapping[str, object]], None] | None
    on_activated: Callable[[str, str], None] | None

    def portal_version(self) -> int | None:
        """The global-shortcuts portal's version, or None when this desktop has none."""

    def create_session(self, handle_token: str, session_token: str) -> None:
        """Ask for a session. The answer arrives through ``on_response``."""

    def bind_shortcut(
        self, session: str, shortcut_id: str, description: str, trigger: str, handle_token: str
    ) -> None:
        """Ask the desktop to bind one shortcut. The answer arrives through ``on_response``."""

    def close_session(self, session: str) -> None:
        """Tell the portal we are done (the shortcut stops working)."""

    def close(self) -> None:
        """Hang up."""


# ---- libdbus through ctypes ---------------------------------------------------------------


class _Error(ctypes.Structure):
    """libdbus's ``DBusError``."""

    _fields_ = (
        ("name", ctypes.c_char_p),
        ("message", ctypes.c_char_p),
        ("dummy", ctypes.c_uint),
        ("padding", ctypes.c_void_p),
    )


class _Iter(ctypes.Structure):
    """libdbus's ``DBusMessageIter``: a bookmark inside a message. Only libdbus looks inside."""

    _fields_ = (("opaque", ctypes.c_uint64 * 16),)


def load_libdbus() -> Any:
    """Load libdbus and declare the C types of the functions used. Raises ``PortalError``."""
    name = ctypes.util.find_library("dbus-1") or "libdbus-1.so.3"
    try:
        lib = ctypes.CDLL(name)
    except OSError as error:
        raise PortalError(f"libdbus is not installed ({error})") from error
    pointer, string, integer = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
    signatures: dict[str, tuple[Any, list[Any]]] = {
        "dbus_error_init": (None, [ctypes.POINTER(_Error)]),
        "dbus_error_free": (None, [ctypes.POINTER(_Error)]),
        "dbus_bus_get_private": (pointer, [integer, ctypes.POINTER(_Error)]),
        "dbus_bus_get_unique_name": (string, [pointer]),
        "dbus_bus_add_match": (None, [pointer, string, ctypes.POINTER(_Error)]),
        "dbus_connection_set_exit_on_disconnect": (None, [pointer, integer]),
        "dbus_connection_get_unix_fd": (integer, [pointer, ctypes.POINTER(integer)]),
        "dbus_connection_read_write": (integer, [pointer, integer]),
        "dbus_connection_pop_message": (pointer, [pointer]),
        "dbus_connection_send_with_reply_and_block": (
            pointer,
            [pointer, pointer, integer, ctypes.POINTER(_Error)],
        ),
        "dbus_connection_close": (None, [pointer]),
        "dbus_connection_unref": (None, [pointer]),
        "dbus_message_new_method_call": (pointer, [string, string, string, string]),
        "dbus_message_unref": (None, [pointer]),
        "dbus_message_get_type": (integer, [pointer]),
        "dbus_message_get_path": (string, [pointer]),
        "dbus_message_get_interface": (string, [pointer]),
        "dbus_message_get_member": (string, [pointer]),
        "dbus_message_iter_init": (integer, [pointer, ctypes.POINTER(_Iter)]),
        "dbus_message_iter_init_append": (None, [pointer, ctypes.POINTER(_Iter)]),
        "dbus_message_iter_append_basic": (integer, [ctypes.POINTER(_Iter), integer, pointer]),
        "dbus_message_iter_open_container": (
            integer,
            [ctypes.POINTER(_Iter), integer, string, ctypes.POINTER(_Iter)],
        ),
        "dbus_message_iter_close_container": (
            integer,
            [ctypes.POINTER(_Iter), ctypes.POINTER(_Iter)],
        ),
        "dbus_message_iter_get_arg_type": (integer, [ctypes.POINTER(_Iter)]),
        "dbus_message_iter_get_basic": (None, [ctypes.POINTER(_Iter), pointer]),
        "dbus_message_iter_recurse": (None, [ctypes.POINTER(_Iter), ctypes.POINTER(_Iter)]),
        "dbus_message_iter_next": (integer, [ctypes.POINTER(_Iter)]),
    }
    for function_name, (result, arguments) in signatures.items():
        function = getattr(lib, function_name)
        function.restype = result
        function.argtypes = arguments
    return lib


class _Writer:
    """Fills in the arguments of one outgoing D-Bus message."""

    def __init__(self, lib: Any, message: Any) -> None:
        self._lib = lib
        self._root = _Iter()
        lib.dbus_message_iter_init_append(message, ctypes.byref(self._root))

    def text(self, kind: int, value: str, into: _Iter | None = None) -> None:
        """Add a string (``kind`` is the type letter: ``s`` or ``o``)."""
        raw = ctypes.c_char_p(value.encode("utf-8"))
        target = self._root if into is None else into
        self._lib.dbus_message_iter_append_basic(
            ctypes.byref(target), kind, ctypes.cast(ctypes.byref(raw), ctypes.c_void_p)
        )

    def open(self, kind: int, signature: bytes | None, into: _Iter | None = None) -> _Iter:
        """Start an array, structure, dictionary entry or variant. Close it with ``close``."""
        parent = self._root if into is None else into
        child = _Iter()
        self._lib.dbus_message_iter_open_container(
            ctypes.byref(parent), kind, signature, ctypes.byref(child)
        )
        return child

    def close(self, child: _Iter, into: _Iter | None = None) -> None:
        parent = self._root if into is None else into
        self._lib.dbus_message_iter_close_container(ctypes.byref(parent), ctypes.byref(child))

    def text_options(self, options: Mapping[str, str], into: _Iter | None = None) -> None:
        """Add an ``a{sv}`` dictionary whose values are all strings."""
        array = self.open(_ARRAY, b"{sv}", into)
        for key, value in options.items():
            entry = self.open(_DICT_ENTRY, None, array)
            self.text(_STRING, key, entry)
            variant = self.open(_VARIANT, b"s", entry)
            self.text(_STRING, value, variant)
            self.close(variant, entry)
            self.close(entry, array)
        self.close(array, into)


class _Entry(NamedTuple):
    """One ``key: value`` pair of a D-Bus dictionary (kept apart from a two-field structure)."""

    key: object
    value: object


def _read_value(lib: Any, bookmark: _Iter) -> object:
    """The value the bookmark points at, as Python data.

    Dictionaries become ``dict``, other arrays ``list``, structures ``tuple`` and variants are
    opened. Kinds we never need (file handles and so on) give None.
    """
    kind = lib.dbus_message_iter_get_arg_type(ctypes.byref(bookmark))
    if kind in (_STRING, _OBJECT_PATH, _SIGNATURE):
        raw = ctypes.c_char_p()
        lib.dbus_message_iter_get_basic(
            ctypes.byref(bookmark), ctypes.cast(ctypes.byref(raw), ctypes.c_void_p)
        )
        return (raw.value or b"").decode("utf-8", errors="replace")
    if kind in _BASIC_NUMBERS:
        number = ctypes.c_uint64()
        lib.dbus_message_iter_get_basic(
            ctypes.byref(bookmark), ctypes.cast(ctypes.byref(number), ctypes.c_void_p)
        )
        return _fit(kind, number.value)
    if kind == _BOOLEAN:
        flag = ctypes.c_uint32()
        lib.dbus_message_iter_get_basic(
            ctypes.byref(bookmark), ctypes.cast(ctypes.byref(flag), ctypes.c_void_p)
        )
        return bool(flag.value)
    if kind not in (_VARIANT, _STRUCT, _ARRAY, _DICT_ENTRY):
        return None
    inner = _Iter()
    lib.dbus_message_iter_recurse(ctypes.byref(bookmark), ctypes.byref(inner))
    items = _read_all(lib, inner)
    if kind == _VARIANT:
        return items[0] if items else None
    if kind == _DICT_ENTRY:
        return _Entry(items[0], items[1]) if len(items) == 2 else None
    if kind == _STRUCT:
        return tuple(items)
    entries = [item for item in items if isinstance(item, _Entry)]
    if entries and len(entries) == len(items):
        return {str(entry.key): entry.value for entry in entries}
    return items


def _fit(kind: int, raw: int) -> int:
    """A number read into 64 bits, as the signed or unsigned value its D-Bus type means."""
    sizes = {"y": 8, "b": 32, "n": 16, "q": 16, "i": 32, "u": 32, "x": 64, "t": 64}
    letter = _BASIC_NUMBERS[kind]
    bits = sizes.get(letter, 64)
    value = raw & ((1 << bits) - 1)
    if letter in "nix" and value >= 1 << (bits - 1):
        value -= 1 << bits
    return value


def _read_all(lib: Any, bookmark: _Iter) -> list[object]:
    """Every value from the bookmark to the end of its container."""
    values: list[object] = []
    while lib.dbus_message_iter_get_arg_type(ctypes.byref(bookmark)) != 0:
        values.append(_read_value(lib, bookmark))
        if not lib.dbus_message_iter_next(ctypes.byref(bookmark)):
            break
    return values


def message_arguments(lib: Any, message: Any) -> list[object]:
    """All the arguments of a received message, as Python data."""
    bookmark = _Iter()
    if not lib.dbus_message_iter_init(message, ctypes.byref(bookmark)):
        return []
    return _read_all(lib, bookmark)


class LibDBusPortal(QObject):
    """The real portal connection: its own private connection to the user's session bus.

    It fits the ``PortalConnection`` interface.
    """

    def __init__(self, lib: Any | None = None) -> None:
        """Connect to the session bus. Raises ``PortalError`` when that is not possible."""
        super().__init__()
        self.on_response: Callable[[str, int, Mapping[str, object]], None] | None = None
        self.on_activated: Callable[[str, str], None] | None = None
        self._lib = lib if lib is not None else load_libdbus()
        error = _Error()
        self._lib.dbus_error_init(ctypes.byref(error))
        connection = self._lib.dbus_bus_get_private(_SESSION_BUS, ctypes.byref(error))
        if not connection:
            text = (error.message or b"no session bus").decode("utf-8", errors="replace")
            self._lib.dbus_error_free(ctypes.byref(error))
            raise PortalError(text)
        self._connection: Any = connection
        # libdbus would otherwise end the whole program if the bus went away.
        self._lib.dbus_connection_set_exit_on_disconnect(connection, 0)
        self._notifier: QSocketNotifier | None = None
        self._watch_for_messages()

    # ---- receiving -------------------------------------------------------------------------

    def _watch_for_messages(self) -> None:
        """Wake up when the bus sends something, so nothing polls and nothing freezes."""
        descriptor = ctypes.c_int()
        if self._lib.dbus_connection_get_unix_fd(self._connection, ctypes.byref(descriptor)):
            self._notifier = QSocketNotifier(descriptor.value, QSocketNotifier.Type.Read, self)
            self._notifier.activated.connect(self._on_readable)
        for member, interface in (
            ("Response", REQUEST_INTERFACE),
            ("Activated", SHORTCUTS_INTERFACE),
        ):
            self._add_match(f"type='signal',interface='{interface}',member='{member}'")

    def _add_match(self, rule: str) -> None:
        error = _Error()
        self._lib.dbus_error_init(ctypes.byref(error))
        self._lib.dbus_bus_add_match(self._connection, rule.encode(), ctypes.byref(error))
        self._lib.dbus_error_free(ctypes.byref(error))

    def _on_readable(self) -> None:
        self._lib.dbus_connection_read_write(self._connection, 0)
        self.drain()

    def drain(self) -> None:
        """Handle every message that is waiting."""
        while True:
            message = self._lib.dbus_connection_pop_message(self._connection)
            if not message:
                return
            try:
                self._handle(message)
            except Exception:  # a handler must never break the app's event loop
                _log.exception("Could not handle a portal message")
            finally:
                self._lib.dbus_message_unref(message)

    def _handle(self, message: Any) -> None:
        if self._lib.dbus_message_get_type(message) != _MESSAGE_SIGNAL:
            return
        interface = (self._lib.dbus_message_get_interface(message) or b"").decode()
        member = (self._lib.dbus_message_get_member(message) or b"").decode()
        arguments = message_arguments(self._lib, message)
        if interface == REQUEST_INTERFACE and member == "Response" and len(arguments) >= 2:
            path = (self._lib.dbus_message_get_path(message) or b"").decode()
            results = arguments[1] if isinstance(arguments[1], dict) else {}
            code = arguments[0] if isinstance(arguments[0], int) else 2
            if self.on_response is not None:
                self.on_response(path, code, results)
        elif (
            interface == SHORTCUTS_INTERFACE
            and member == "Activated"
            and len(arguments) >= 2
            and self.on_activated is not None
        ):
            self.on_activated(str(arguments[0]), str(arguments[1]))

    # ---- calling ---------------------------------------------------------------------------

    def _call(
        self,
        interface: str,
        method: str,
        path: str,
        fill: Callable[[_Writer], None] | None = None,
    ) -> list[object]:
        """Call a portal method and wait for its (quick) reply. Raises ``PortalError``."""
        message = self._lib.dbus_message_new_method_call(
            PORTAL_SERVICE.encode(), path.encode(), interface.encode(), method.encode()
        )
        if not message:
            raise PortalError("could not build the D-Bus message")
        try:
            if fill is not None:
                fill(_Writer(self._lib, message))
            error = _Error()
            self._lib.dbus_error_init(ctypes.byref(error))
            reply = self._lib.dbus_connection_send_with_reply_and_block(
                self._connection, message, CALL_TIMEOUT_MS, ctypes.byref(error)
            )
        finally:
            self._lib.dbus_message_unref(message)
        if not reply:
            text = (error.message or b"no answer").decode("utf-8", errors="replace")
            self._lib.dbus_error_free(ctypes.byref(error))
            raise PortalError(text)
        try:
            if self._lib.dbus_message_get_type(reply) == _MESSAGE_ERROR:
                raise PortalError("the portal answered with an error")
            return message_arguments(self._lib, reply)
        finally:
            self._lib.dbus_message_unref(reply)

    def portal_version(self) -> int | None:
        """Read the portal's ``version`` property (it is missing on desktops without it)."""

        def fill(writer: _Writer) -> None:
            writer.text(_STRING, SHORTCUTS_INTERFACE)
            writer.text(_STRING, "version")

        try:
            reply = self._call("org.freedesktop.DBus.Properties", "Get", PORTAL_PATH, fill)
        except PortalError:
            return None
        return reply[0] if reply and isinstance(reply[0], int) else None

    def create_session(self, handle_token: str, session_token: str) -> None:
        def fill(writer: _Writer) -> None:
            writer.text_options(
                {"handle_token": handle_token, "session_handle_token": session_token}
            )

        self._call(SHORTCUTS_INTERFACE, "CreateSession", PORTAL_PATH, fill)
        self.drain()  # a quick Response may already be waiting

    def bind_shortcut(
        self, session: str, shortcut_id: str, description: str, trigger: str, handle_token: str
    ) -> None:
        def fill(writer: _Writer) -> None:
            writer.text(_OBJECT_PATH, session)
            shortcuts = writer.open(_ARRAY, b"(sa{sv})")
            entry = writer.open(_STRUCT, None, shortcuts)
            writer.text(_STRING, shortcut_id, entry)
            writer.text_options({"description": description, "preferred_trigger": trigger}, entry)
            writer.close(entry, shortcuts)
            writer.close(shortcuts)
            writer.text(_STRING, "")  # no parent window: the desktop asks in its own dialog
            writer.text_options({"handle_token": handle_token})

        self._call(SHORTCUTS_INTERFACE, "BindShortcuts", PORTAL_PATH, fill)
        self.drain()

    def close_session(self, session: str) -> None:
        try:
            self._call(SESSION_INTERFACE, "Close", session)
        except PortalError:
            _log.debug("The portal session was already gone")

    def close(self) -> None:
        if self._notifier is not None:
            self._notifier.setEnabled(False)
            self._notifier = None
        connection, self._connection = self._connection, None
        if connection:
            self._lib.dbus_connection_close(connection)
            self._lib.dbus_connection_unref(connection)
