"""The words the hotkey and the portal client use to talk to each other.

These are plain Python types with no D-Bus and no Qt in them, so ``hotkey.py`` can import this
file on every system (Windows and macOS too), and tests can use a fake portal.

The conversation is simple:

1. The hotkey calls ``start`` with the shortcut it wants.
2. The portal client does the slow work in the background and reports what happens as
   ``PortalEvent`` values: ``PortalBound`` once, or ``PortalFailed`` once, then
   ``PortalActivated`` every time the player presses the key.
3. The hotkey calls ``close`` when it is done.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class PortalError(Exception):
    """The portal client could not even be created. The text is for the log."""


@dataclass(frozen=True, slots=True)
class ShortcutRequest:
    """The one shortcut we ask the desktop for."""

    shortcut_id: str  # our own name for it, sent back to us in every key press
    description: str  # shown by the desktop in its question and its shortcut settings
    trigger: str  # the key we would like, in the portal's text ("CTRL+SHIFT+space")


class PortalFailure(Enum):
    """Why the portal could not give us the key."""

    UNAVAILABLE = "unavailable"  # no session bus, no portal, or something broke on the way
    DECLINED = "declined"  # the player (or the desktop) said no
    REFUSED = "refused"  # the desktop would not take the request; it often does not know the app
    TIMED_OUT = "timed_out"  # the desktop never answered


@dataclass(frozen=True, slots=True)
class PortalBound:
    """The desktop accepted the shortcut. ``trigger_description`` is the key it really bound."""

    trigger_description: str = ""


@dataclass(frozen=True, slots=True)
class PortalFailed:
    """The key will not work. Nothing more arrives after this."""

    reason: PortalFailure


@dataclass(frozen=True, slots=True)
class PortalActivated:
    """The player pressed the key."""


PortalEvent = PortalBound | PortalFailed | PortalActivated


class PortalConnection(Protocol):
    """What the hotkey needs from the portal. Real: ``JeepneyPortal``. Tests: a fake.

    One connection serves one registration: the hotkey asks for a new one each time the key is
    registered, and calls ``close`` when it is done with it.
    """

    def start(self, request: ShortcutRequest, report: Callable[[PortalEvent], None]) -> None:
        """Begin asking the desktop for the shortcut. Returns at once.

        ``report`` may be called from another thread, so it must be thread-safe.
        """

    def close(self) -> None:
        """Give the shortcut back, hang up and stop reporting."""
