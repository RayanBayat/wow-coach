"""A small client for the "global shortcuts" portal of a Linux desktop, using ``jeepney``.

A *portal* is a service every modern Linux desktop offers over D-Bus (the system that lets
programs talk to each other). The ``org.freedesktop.portal.GlobalShortcuts`` portal is the
polite way to ask the desktop: "please tell me when the player presses this key, even while
another program (the game) has the keyboard."

``jeepney`` is a D-Bus library written in plain Python (no C code), so a mistake in a message
raises a normal Python error instead of crashing the whole program. We use its simple
"blocking" style: the whole conversation runs in one background thread, one step after the
other, so the code reads like the story:

1. connect to the session bus,
2. ``CreateSession``, then wait for the portal's ``Response``,
3. ``BindShortcuts``, then wait for its ``Response`` (the desktop may ask the player),
4. listen for ``Activated`` until the app closes,
5. ``Close`` the session and hang up.

Only that thread ever touches the connection, which keeps things simple and safe. Every
failure becomes a ``PortalFailed`` report, never an exception that escapes the thread.

This module imports ``jeepney``, which is only installed on Linux, so only import it on Linux.
"""

import logging
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any, Final

from jeepney import (
    DBusAddress,
    DBusErrorResponse,
    HeaderFields,
    MatchRule,
    Message,
    MessageType,
    message_bus,
    new_method_call,
)
from jeepney.io.blocking import open_dbus_connection

from wow_coach.desktop.portal_types import (
    PortalActivated,
    PortalBound,
    PortalEvent,
    PortalFailed,
    PortalFailure,
    ShortcutRequest,
)

_log = logging.getLogger(__name__)

PORTAL_SERVICE: Final = "org.freedesktop.portal.Desktop"
PORTAL_PATH: Final = "/org/freedesktop/portal/desktop"
SHORTCUTS_INTERFACE: Final = "org.freedesktop.portal.GlobalShortcuts"
REQUEST_INTERFACE: Final = "org.freedesktop.portal.Request"
SESSION_INTERFACE: Final = "org.freedesktop.portal.Session"
PROPERTIES_INTERFACE: Final = "org.freedesktop.DBus.Properties"

# How long to wait for each answer. The portal answers a call at once, but the *Response* to
# BindShortcuts waits for the player: KDE shows a dialog the first time, so allow a minute.
CALL_TIMEOUT: Final = 5.0
RESPONSE_TIMEOUT: Final = 10.0
BIND_RESPONSE_TIMEOUT: Final = 60.0
CLOSE_TIMEOUT: Final = 1.0
# While waiting we look up from the socket this often to see if the app wants to quit.
POLL_SECONDS: Final = 0.2
# How long ``close`` waits for the background thread to finish.
JOIN_SECONDS: Final = 3.0

# Response codes from the portal.
_RESPONSE_OK: Final = 0
_RESPONSE_CANCELLED: Final = 1  # the player said no


class _StoppedError(Exception):
    """The app asked us to stop while we were waiting (not an error)."""


class _TimedOutError(Exception):
    """The desktop did not answer in time."""


class _RefusedError(Exception):
    """The portal said no. ``reason`` is what we report to the hotkey."""

    def __init__(self, reason: PortalFailure) -> None:
        super().__init__(reason.value)
        self.reason = reason


# ---- the messages we send ------------------------------------------------------------------


def _text(value: str) -> tuple[str, str]:
    """A D-Bus *variant* holding a string: jeepney writes a variant as (signature, value)."""
    return ("s", value)


def _portal_address(interface: str) -> DBusAddress:
    return DBusAddress(PORTAL_PATH, bus_name=PORTAL_SERVICE, interface=interface)


def read_version_message() -> Message:
    """``Properties.Get(interface, "version")``: fails on desktops without this portal."""
    return new_method_call(
        _portal_address(PROPERTIES_INTERFACE), "Get", "ss", (SHORTCUTS_INTERFACE, "version")
    )


def create_session_message(handle_token: str, session_token: str) -> Message:
    """``CreateSession(a{sv} options)``."""
    options = {"handle_token": _text(handle_token), "session_handle_token": _text(session_token)}
    return new_method_call(
        _portal_address(SHORTCUTS_INTERFACE), "CreateSession", "a{sv}", (options,)
    )


def bind_shortcuts_message(session: str, request: ShortcutRequest, handle_token: str) -> Message:
    """``BindShortcuts(o session, a(sa{sv}) shortcuts, s parent_window, a{sv} options)``.

    The shortcut list is an array of structures: a name and a dictionary of details. This is
    the part Qt's own D-Bus classes cannot build.
    """
    details = {
        "description": _text(request.description),
        "preferred_trigger": _text(request.trigger),
    }
    shortcuts = [(request.shortcut_id, details)]
    # The empty parent window means "no window": the desktop asks in its own dialog.
    body = (session, shortcuts, "", {"handle_token": _text(handle_token)})
    return new_method_call(
        _portal_address(SHORTCUTS_INTERFACE), "BindShortcuts", "oa(sa{sv})sa{sv}", body
    )


def close_session_message(session: str) -> Message:
    """``Session.Close()`` on the session object."""
    address = DBusAddress(session, bus_name=PORTAL_SERVICE, interface=SESSION_INTERFACE)
    return new_method_call(address, "Close")


# ---- reading what comes back ---------------------------------------------------------------


def request_path(unique_name: str, handle_token: str) -> str:
    """Where the portal will announce the answer to our request.

    The portal builds it from our connection's name (":1.42" becomes "1_42") and the
    ``handle_token`` we chose, so we know it before we ask and never miss a fast answer.
    """
    sender = unique_name.lstrip(":").replace(".", "_")
    return f"/org/freedesktop/portal/desktop/request/{sender}/{handle_token}"


def trigger_description(results: Mapping[str, Any]) -> str:
    """The key the desktop says it bound, from the ``shortcuts`` entry of a Response.

    Variants arrive as (signature, value), so the entry looks like
    ``("a(sa{sv})", [("toggle-overlay", {"trigger_description": ("s", "Ctrl+Alt+O")})])``.
    Returns "" when the desktop did not say.
    """
    try:
        description = results["shortcuts"][1][0][1]["trigger_description"][1]
    except KeyError, IndexError, TypeError:
        return ""
    return description if isinstance(description, str) else ""


def _is_our_press(message: Message, session: str, shortcut_id: str) -> bool:
    """True when an ``Activated`` signal is for our session and our shortcut."""
    body = message.body
    return len(body) >= 2 and body[0] == session and body[1] == shortcut_id


def _new_token(prefix: str) -> str:
    """A name only this run knows, safe to use as part of a D-Bus object path."""
    return f"{prefix}_{secrets.token_hex(6)}"


# ---- the client ----------------------------------------------------------------------------


class JeepneyPortal:
    """The real portal client. It fits the ``PortalConnection`` interface.

    Creating it does nothing yet; ``start`` begins the conversation in a background thread.
    """

    def __init__(
        self,
        open_connection: Callable[[], Any] | None = None,
        *,
        response_timeout: float = RESPONSE_TIMEOUT,
        bind_timeout: float = BIND_RESPONSE_TIMEOUT,
    ) -> None:
        """Create it.

        Args:
            open_connection: Opens a jeepney connection to the session bus. Tests pass a
                function that returns a fake one, so no real bus is ever used.
            response_timeout: Seconds to wait for the answer to ``CreateSession``.
            bind_timeout: Seconds to wait for the answer to ``BindShortcuts`` (the player may
                have to confirm a dialog).
        """
        self._open_connection = open_connection or open_dbus_connection
        self._response_timeout = response_timeout
        self._bind_timeout = bind_timeout
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # jeepney fills these with the signals we asked for (see ``_converse``).
        self._responses: deque[Message] = deque()
        self._presses: deque[Message] = deque()

    def start(self, request: ShortcutRequest, report: Callable[[PortalEvent], None]) -> None:
        """Begin the conversation in a background thread and return at once."""
        if self._thread is not None:
            raise RuntimeError("a JeepneyPortal serves one registration only")
        # A daemon thread cannot keep the app alive if something goes wrong while quitting.
        self._thread = threading.Thread(
            target=self._run, args=(request, report), name="wow-coach-portal", daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        """Ask the thread to give the shortcut back and hang up, and wait for it."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(JOIN_SECONDS)

    # ---- the background thread -------------------------------------------------------------

    def _run(self, request: ShortcutRequest, report: Callable[[PortalEvent], None]) -> None:
        """The whole conversation. It never raises: every problem becomes a report."""
        connection: Any = None
        session: list[str] = []  # filled in as soon as we have one, so ``finally`` can close it
        try:
            connection = self._open_connection()
            self._converse(connection, request, report, session)
        except _StoppedError:
            pass  # the app is quitting; nobody wants a report
        except _TimedOutError:
            self._report_failure(report, PortalFailure.TIMED_OUT)
        except _RefusedError as refusal:
            self._report_failure(report, refusal.reason)
        except Exception as error:  # a broken bus must never crash the app, whatever jeepney raises
            _log.info("The portal hotkey could not start: %s", error)
            self._report_failure(report, PortalFailure.UNAVAILABLE)
        finally:
            self._hang_up(connection, session)

    def _report_failure(self, report: Callable[[PortalEvent], None], reason: PortalFailure) -> None:
        """Report a failure, unless the app already asked us to stop."""
        if not self._stop.is_set():
            report(PortalFailed(reason))

    def _converse(
        self,
        connection: Any,
        request: ShortcutRequest,
        report: Callable[[PortalEvent], None],
        session: list[str],
    ) -> None:
        """Subscribe, create the session, bind the shortcut, then report key presses."""
        # Subscribe *before* the first call, so an answer that comes quickly is not missed.
        responses = MatchRule(type="signal", interface=REQUEST_INTERFACE, member="Response")
        presses = MatchRule(type="signal", interface=SHORTCUTS_INTERFACE, member="Activated")
        self._call(connection, message_bus.AddMatch(responses))
        self._call(connection, message_bus.AddMatch(presses))
        with (
            connection.filter(responses, queue=self._responses),
            connection.filter(presses, queue=self._presses),
        ):
            self._call(connection, read_version_message())  # fails on desktops without the portal
            session.append(self._create_session(connection))
            self._bind(connection, session[0], request, report)
            self._listen(connection, session[0], request, report)

    def _create_session(self, connection: Any) -> str:
        """``CreateSession`` and its Response. Returns the session's object path."""
        token = _new_token("create")
        self._call(connection, create_session_message(token, _new_token("session")))
        path = request_path(connection.unique_name, token)
        results = self._wait_for_response(connection, path, self._response_timeout)
        session = results.get("session_handle", (None, None))[1]
        if not isinstance(session, str):
            raise _RefusedError(PortalFailure.UNAVAILABLE)
        return session

    def _bind(
        self,
        connection: Any,
        session: str,
        request: ShortcutRequest,
        report: Callable[[PortalEvent], None],
    ) -> None:
        """``BindShortcuts`` and its Response (the player may be asked first)."""
        token = _new_token("bind")
        try:
            self._call(connection, bind_shortcuts_message(session, request, token))
        except DBusErrorResponse as error:
            # Most often "App info not found": the desktop does not know our .desktop file.
            _log.info("The portal refused BindShortcuts: %s", error)
            raise _RefusedError(PortalFailure.REFUSED) from error
        path = request_path(connection.unique_name, token)
        results = self._wait_for_response(connection, path, self._bind_timeout, binding=True)
        report(PortalBound(trigger_description(results)))

    def _listen(
        self,
        connection: Any,
        session: str,
        request: ShortcutRequest,
        report: Callable[[PortalEvent], None],
    ) -> None:
        """Report every press of our key until the app asks us to stop."""
        while not self._stop.is_set():
            try:
                message = connection.recv_until_filtered(self._presses, timeout=POLL_SECONDS)
            except TimeoutError:
                continue  # nothing yet: look at the stop flag, then wait again
            if _is_our_press(message, session, request.shortcut_id):
                report(PortalActivated())

    def _hang_up(self, connection: Any, session: list[str]) -> None:
        """Give the session back and close the connection. Best effort: we are leaving."""
        if connection is None:
            return
        try:
            if session:
                connection.send_and_get_reply(
                    close_session_message(session[0]), timeout=CLOSE_TIMEOUT
                )
        except Exception as error:  # the session may be gone already; nothing more to do
            _log.debug("Could not close the portal session: %s", error)
        try:
            connection.close()
        except Exception as error:  # the socket may be gone already
            _log.debug("Could not close the D-Bus connection: %s", error)

    # ---- small helpers ---------------------------------------------------------------------

    def _call(self, connection: Any, message: Message) -> tuple[Any, ...]:
        """Send a call and wait for its quick reply. Raises ``DBusErrorResponse`` on an error."""
        reply = connection.send_and_get_reply(message, timeout=CALL_TIMEOUT)
        if reply.header.message_type is MessageType.error:
            raise DBusErrorResponse(reply)
        return tuple(reply.body)

    def _wait_for_response(
        self, connection: Any, path: str, timeout: float, *, binding: bool = False
    ) -> dict[str, Any]:
        """Wait for the ``Response`` signal sent from ``path`` and return its results.

        Raises ``_RefusedError`` when the code is not "yes", ``_TimedOutError`` when time runs
        out and ``_StoppedError`` when the app wants to quit.
        """
        deadline = time.monotonic() + timeout
        while True:
            if self._stop.is_set():
                raise _StoppedError
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _TimedOutError
            try:
                message = connection.recv_until_filtered(
                    self._responses, timeout=min(POLL_SECONDS, remaining)
                )
            except TimeoutError:
                continue
            if message.header.fields.get(HeaderFields.path) != path:
                continue  # an answer to somebody else's request
            code, results = message.body
            if code == _RESPONSE_OK:
                return dict(results)
            if code == _RESPONSE_CANCELLED:
                raise _RefusedError(PortalFailure.DECLINED)
            # Any other code while binding usually means the desktop does not know our app.
            raise _RefusedError(PortalFailure.REFUSED if binding else PortalFailure.UNAVAILABLE)
