"""The portal client (``portal_bus``) against a fake D-Bus connection.

jeepney is installed on Linux only, so ``conftest.py`` skips this file elsewhere.

Nothing here touches a real bus, a real portal or a real window. The fake stands in for
jeepney's connection: it records the messages we send, answers them like the portal would,
and delivers the signals the test scripts. Messages are real jeepney messages, so a wrong
signature or body type fails here too (we serialise and read each message back).
"""

import queue
import time
from collections import deque
from types import TracebackType
from typing import Any

import pytest
from jeepney import (
    DBusAddress,
    HeaderFields,
    Message,
    new_error,
    new_method_return,
    new_signal,
)

from wow_coach.desktop import portal_bus
from wow_coach.desktop.portal_bus import JeepneyPortal
from wow_coach.desktop.portal_types import (
    PortalActivated,
    PortalBound,
    PortalEvent,
    PortalFailed,
    PortalFailure,
    ShortcutRequest,
)

SESSION = "/org/freedesktop/portal/desktop/session/1_42/mine"
REQUEST = ShortcutRequest("toggle-overlay", "Show or hide WoW Coach", "CTRL+SHIFT+space")


@pytest.fixture(autouse=True)
def never_open_a_real_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    """Safety net: if a test forgets the fake, fail instead of reaching the real session bus."""

    def refuse() -> None:
        raise AssertionError("a test tried to open the real D-Bus session bus")

    monkeypatch.setattr(portal_bus, "open_dbus_connection", refuse)


class FakeBus:
    """A stand-in for jeepney's blocking connection, playing the portal."""

    unique_name = ":1.42"

    def __init__(
        self,
        *,
        create_code: int | None = 0,
        bind_code: int | None = 0,
        bind_error: bool = False,
        no_portal: bool = False,
        break_on: str | None = None,
        trigger: str = "Ctrl+Alt+O",
        presses: tuple[tuple[str, str], ...] = (),
        stray_response: bool = False,
    ) -> None:
        """Script the portal.

        Args:
            create_code: Response code for CreateSession (None = never answer).
            bind_code: Response code for BindShortcuts (None = never answer).
            bind_error: Answer the BindShortcuts call itself with a D-Bus error.
            no_portal: Answer the version question with a D-Bus error.
            break_on: Name of a method whose call raises ``ConnectionResetError``.
            trigger: The key the desktop says it bound.
            presses: (session, shortcut) pairs sent as ``Activated`` after the bind answer.
            stray_response: Send an answer for somebody else's request first.
        """
        self.create_code = create_code
        self.bind_code = bind_code
        self.bind_error = bind_error
        self.no_portal = no_portal
        self.break_on = break_on
        self.trigger = trigger
        self.presses = presses
        self.stray_response = stray_response
        self.sent: list[Message] = []
        self.closed = False
        self._incoming: deque[Message] = deque()
        self._filters: list[tuple[Any, deque[Message]]] = []

    # ---- what the portal client calls ----

    def send_and_get_reply(self, message: Message, *, timeout: float | None = None) -> Message:  # noqa: ARG002 - same call as jeepney
        self.sent.append(message)
        member = message.header.fields[HeaderFields.member]
        if member == self.break_on:
            raise ConnectionResetError("the bus went away")
        if member == "Get" and self.no_portal:
            return new_error(message, "org.freedesktop.DBus.Error.UnknownProperty", "s", ("no",))
        if member == "BindShortcuts":
            return self._answer_bind(message)
        if member == "CreateSession":
            self._answer_create(message)
        if member == "Get":
            return new_method_return(message, "v", (("u", 1),))  # the portal's version
        return new_method_return(message)

    def filter(self, rule: Any, *, queue: deque[Message]) -> FakeBus._Filter:
        self._filters.append((rule, queue))
        return FakeBus._Filter()

    def recv_until_filtered(self, queue: deque[Message], *, timeout: float) -> Message:
        while not queue:
            if not self._incoming:
                time.sleep(min(timeout, 0.005))  # like waiting on a quiet socket
                raise TimeoutError
            self._deliver(self._incoming.popleft())
        return queue.popleft()

    def close(self) -> None:
        self.closed = True

    class _Filter:
        """What ``connection.filter`` returns: usable in a ``with`` block."""

        def __enter__(self) -> None:
            return None

        def __exit__(
            self,
            kind: type[BaseException] | None,
            error: BaseException | None,
            trace: TracebackType | None,
        ) -> None:
            return None

    # ---- the scripted portal ----

    def _answer_create(self, message: Message) -> None:
        token = message.body[0]["handle_token"][1]
        if self.stray_response:
            self._respond("/org/freedesktop/portal/desktop/request/1_99/other", 0, {})
        if self.create_code is not None:
            results = {"session_handle": ("s", SESSION)} if self.create_code == 0 else {}
            self._respond(
                portal_bus.request_path(self.unique_name, token), self.create_code, results
            )

    def _answer_bind(self, message: Message) -> Message:
        if self.bind_error:
            return new_error(message, "org.freedesktop.DBus.Error.Failed", "s", ("App info",))
        token = message.body[3]["handle_token"][1]
        if self.bind_code is not None:
            shortcuts = [("toggle-overlay", {"trigger_description": ("s", self.trigger)})]
            results = {"shortcuts": ("a(sa{sv})", shortcuts)}
            self._respond(portal_bus.request_path(self.unique_name, token), self.bind_code, results)
            for session, shortcut in self.presses:
                address = DBusAddress(
                    portal_bus.PORTAL_PATH, interface=portal_bus.SHORTCUTS_INTERFACE
                )
                self._incoming.append(
                    new_signal(address, "Activated", "osta{sv}", (session, shortcut, 1, {}))
                )
        return new_method_return(message, "o", ("/request",))

    def _respond(self, path: str, code: int, results: dict[str, Any]) -> None:
        address = DBusAddress(path, interface=portal_bus.REQUEST_INTERFACE)
        self._incoming.append(new_signal(address, "Response", "ua{sv}", (code, results)))

    def _deliver(self, message: Message) -> None:
        """Put a signal into the queue whose rule matches it (like jeepney's filters)."""
        for rule, waiting in self._filters:
            wanted = rule.header_fields
            fields = message.header.fields
            if fields.get(HeaderFields.interface) == wanted.get("interface") and fields.get(
                HeaderFields.member
            ) == wanted.get("member"):
                waiting.append(message)

    # ---- what the tests look at ----

    def calls(self, member: str) -> list[Message]:
        return [m for m in self.sent if m.header.fields[HeaderFields.member] == member]


class Run:
    """Starts a portal client on a fake bus and collects what it reports."""

    def __init__(
        self, bus: FakeBus, *, response_timeout: float = 1.0, bind_timeout: float = 1.0
    ) -> None:
        self.bus = bus
        self.events: queue.Queue[PortalEvent] = queue.Queue()
        self.portal = JeepneyPortal(
            lambda: bus, response_timeout=response_timeout, bind_timeout=bind_timeout
        )
        self.portal.start(REQUEST, self.events.put)

    def next_event(self) -> PortalEvent:
        return self.events.get(timeout=3)

    def finish(self) -> list[PortalEvent]:
        """Close the portal and return every event that was still waiting."""
        self.portal.close()
        left: list[PortalEvent] = []
        while not self.events.empty():
            left.append(self.events.get_nowait())
        return left


@pytest.fixture
def started() -> Any:
    """Make runs, and close them all at the end, whatever the test did."""
    runs: list[Run] = []

    def start(bus: FakeBus, **timeouts: float) -> Run:
        run = Run(bus, **timeouts)
        runs.append(run)
        return run

    yield start
    for run in runs:
        run.portal.close()


def read_back(message: Message) -> Message:
    """Serialise a message and parse it again, as the bus would."""
    return Message.from_buffer(message.serialise(serial=1))


# ---- the messages we send -------------------------------------------------------------------


def test_create_session_sends_two_tokens_as_string_variants() -> None:
    message = portal_bus.create_session_message("create_1", "session_1")
    assert message.header.fields[HeaderFields.signature] == "a{sv}"
    assert message.header.fields[HeaderFields.member] == "CreateSession"
    assert message.header.fields[HeaderFields.interface] == portal_bus.SHORTCUTS_INTERFACE
    assert message.body == (
        {"handle_token": ("s", "create_1"), "session_handle_token": ("s", "session_1")},
    )
    assert read_back(message).body == message.body


def test_bind_shortcuts_sends_one_shortcut_in_the_a_sa_sv_shape() -> None:
    message = portal_bus.bind_shortcuts_message(SESSION, REQUEST, "bind_1")
    assert message.header.fields[HeaderFields.signature] == "oa(sa{sv})sa{sv}"
    assert message.header.fields[HeaderFields.member] == "BindShortcuts"
    assert message.body == (
        SESSION,
        [
            (
                "toggle-overlay",
                {
                    "description": ("s", "Show or hide WoW Coach"),
                    "preferred_trigger": ("s", "CTRL+SHIFT+space"),
                },
            )
        ],
        "",
        {"handle_token": ("s", "bind_1")},
    )
    assert read_back(message).body == message.body


def test_close_goes_to_the_session_object() -> None:
    message = portal_bus.close_session_message(SESSION)
    assert message.header.fields[HeaderFields.path] == SESSION
    assert message.header.fields[HeaderFields.interface] == portal_bus.SESSION_INTERFACE
    assert message.header.fields[HeaderFields.member] == "Close"


def test_the_request_path_is_built_from_our_connection_name_and_token() -> None:
    assert (
        portal_bus.request_path(":1.42", "bind_1")
        == "/org/freedesktop/portal/desktop/request/1_42/bind_1"
    )


def test_the_bound_key_is_read_from_the_response() -> None:
    results = {"shortcuts": ("a(sa{sv})", [("x", {"trigger_description": ("s", "Ctrl+Alt+O")})])}
    assert portal_bus.trigger_description(results) == "Ctrl+Alt+O"
    assert portal_bus.trigger_description({}) == ""
    assert portal_bus.trigger_description({"shortcuts": ("a(sa{sv})", [])}) == ""


# ---- the conversation -----------------------------------------------------------------------


def test_the_happy_path_asks_in_order_and_reports_the_bound_key(started: Any) -> None:
    bus = FakeBus()
    run = started(bus)
    assert run.next_event() == PortalBound("Ctrl+Alt+O")

    members = [m.header.fields[HeaderFields.member] for m in bus.sent]
    assert members == ["AddMatch", "AddMatch", "Get", "CreateSession", "BindShortcuts"]
    bind = bus.calls("BindShortcuts")[0]
    assert bind.body[0] == SESSION  # bound on the session the portal gave us
    assert bind.body[1][0][0] == "toggle-overlay"


def test_an_answer_to_somebody_elses_request_is_ignored(started: Any) -> None:
    run = started(FakeBus(stray_response=True))
    assert run.next_event() == PortalBound("Ctrl+Alt+O")


def test_a_key_press_for_our_session_is_reported_and_others_are_not(started: Any) -> None:
    bus = FakeBus(
        presses=(
            ("/org/freedesktop/portal/desktop/session/1_77/other", "toggle-overlay"),
            (SESSION, "some-other-shortcut"),
            (SESSION, "toggle-overlay"),
        )
    )
    run = started(bus)
    assert run.next_event() == PortalBound("Ctrl+Alt+O")
    assert run.next_event() == PortalActivated()
    assert run.finish() == []  # no second press was reported


# ---- every way it can fail ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bus_options", "expected"),
    [
        ({"create_code": 1}, PortalFailure.DECLINED),
        ({"create_code": 2}, PortalFailure.UNAVAILABLE),
        ({"bind_code": 1}, PortalFailure.DECLINED),
        ({"bind_code": 2}, PortalFailure.REFUSED),
        ({"bind_error": True}, PortalFailure.REFUSED),
        ({"no_portal": True}, PortalFailure.UNAVAILABLE),
        ({"break_on": "CreateSession"}, PortalFailure.UNAVAILABLE),
        ({"break_on": "BindShortcuts"}, PortalFailure.UNAVAILABLE),
    ],
)
def test_every_failure_is_reported_and_the_connection_is_closed(
    started: Any, bus_options: dict[str, Any], expected: PortalFailure
) -> None:
    bus = FakeBus(**bus_options)
    run = started(bus)
    assert run.next_event() == PortalFailed(expected)
    run.portal.close()
    assert bus.closed


def test_no_answer_to_create_session_times_out(started: Any) -> None:
    run = started(FakeBus(create_code=None), response_timeout=0.05)
    assert run.next_event() == PortalFailed(PortalFailure.TIMED_OUT)


def test_no_answer_to_bind_shortcuts_times_out(started: Any) -> None:
    run = started(FakeBus(bind_code=None), bind_timeout=0.05)
    assert run.next_event() == PortalFailed(PortalFailure.TIMED_OUT)


def test_the_bind_wait_is_much_longer_than_the_others() -> None:
    # The player may have to confirm KDE's dialog the first time.
    assert portal_bus.BIND_RESPONSE_TIMEOUT >= 60
    assert portal_bus.RESPONSE_TIMEOUT <= portal_bus.BIND_RESPONSE_TIMEOUT


def test_no_session_bus_is_reported_not_raised() -> None:
    def no_bus() -> FakeBus:
        raise FileNotFoundError("no session bus socket")

    events: queue.Queue[PortalEvent] = queue.Queue()
    portal = JeepneyPortal(no_bus)
    portal.start(REQUEST, events.put)
    assert events.get(timeout=3) == PortalFailed(PortalFailure.UNAVAILABLE)
    portal.close()


def test_a_missing_session_bus_address_is_reported_not_raised() -> None:
    def no_address() -> FakeBus:
        raise KeyError("DBUS_SESSION_BUS_ADDRESS")

    events: queue.Queue[PortalEvent] = queue.Queue()
    portal = JeepneyPortal(no_address)
    portal.start(REQUEST, events.put)
    assert events.get(timeout=3) == PortalFailed(PortalFailure.UNAVAILABLE)
    portal.close()


# ---- shutting down --------------------------------------------------------------------------


def test_closing_gives_the_session_back_and_hangs_up(started: Any) -> None:
    bus = FakeBus()
    run = started(bus)
    assert run.next_event() == PortalBound("Ctrl+Alt+O")

    run.portal.close()

    closes = bus.calls("Close")
    assert [m.header.fields[HeaderFields.path] for m in closes] == [SESSION]
    assert closes[0].header.fields[HeaderFields.interface] == portal_bus.SESSION_INTERFACE
    assert bus.closed


def test_closing_while_waiting_reports_nothing_and_still_hangs_up(started: Any) -> None:
    bus = FakeBus(bind_code=None)
    run = started(bus, bind_timeout=60)
    time.sleep(0.05)  # let it reach the wait for the player's answer
    run.portal.close()
    assert run.events.empty()
    assert bus.closed
    assert [m.header.fields[HeaderFields.path] for m in bus.calls("Close")] == [SESSION]


def test_one_client_serves_one_registration(started: Any) -> None:
    run = started(FakeBus())
    with pytest.raises(RuntimeError):
        run.portal.start(REQUEST, lambda _event: None)
