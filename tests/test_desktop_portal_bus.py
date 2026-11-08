"""The libdbus layer of the portal client, without any bus.

A D-Bus message can be built and read back in memory, so these tests check that the
arguments are marshalled in the shape the portal wants without connecting to anything.
"""

import ctypes
import sys
from typing import Any

import pytest

from wow_coach.desktop import portal_bus
from wow_coach.desktop.portal_bus import PortalError

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="libdbus is the Linux desktop's library"
)


@pytest.fixture(scope="module")
def lib() -> Any:
    try:
        return portal_bus.load_libdbus()
    except PortalError:
        pytest.skip("libdbus is not installed")


def new_message(lib: Any) -> Any:
    return lib.dbus_message_new_method_call(
        b"org.example.Service", b"/org/example", b"org.example.Interface", b"Method"
    )


def test_the_bind_call_has_the_shape_the_portal_wants(lib: Any) -> None:
    message = new_message(lib)
    writer = portal_bus._Writer(lib, message)
    writer.text(ord("o"), "/org/freedesktop/portal/desktop/session/1_2/mine")
    shortcuts = writer.open(ord("a"), b"(sa{sv})")
    entry = writer.open(ord("r"), None, shortcuts)
    writer.text(ord("s"), "toggle-overlay", entry)
    writer.text_options({"description": "Show", "preferred_trigger": "CTRL+SHIFT+space"}, entry)
    writer.close(entry, shortcuts)
    writer.close(shortcuts)
    writer.text(ord("s"), "")
    writer.text_options({"handle_token": "bind_1"})

    assert portal_bus.message_arguments(lib, message) == [
        "/org/freedesktop/portal/desktop/session/1_2/mine",
        [
            (
                "toggle-overlay",
                {"description": "Show", "preferred_trigger": "CTRL+SHIFT+space"},
            )
        ],
        "",
        {"handle_token": "bind_1"},
    ]
    lib.dbus_message_unref(message)


def test_numbers_are_read_with_their_real_size_and_sign() -> None:
    assert portal_bus._fit(ord("u"), 2) == 2
    assert portal_bus._fit(ord("i"), 0xFFFFFFFF) == -1
    assert portal_bus._fit(ord("t"), 2**64 - 1) == 2**64 - 1


def test_an_empty_message_has_no_arguments(lib: Any) -> None:
    message = new_message(lib)
    assert portal_bus.message_arguments(lib, message) == []
    lib.dbus_message_unref(message)


def test_a_missing_library_is_a_portal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(_name: str) -> ctypes.CDLL:
        raise OSError("not found")

    monkeypatch.setattr(ctypes, "CDLL", refuse)
    with pytest.raises(PortalError):
        portal_bus.load_libdbus()
