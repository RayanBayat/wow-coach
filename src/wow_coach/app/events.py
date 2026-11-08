"""A tiny publish/subscribe "mailbox" that carries live updates to the open window.

Every open page asks for ``/api/events`` and gets its own mailbox (a queue). Whenever
something happens (an answer is ready, the game saved...) the program calls ``publish`` and
a copy of the event lands in every mailbox. A slow page can never block the program: a full
mailbox simply drops new events (the page re-reads the whole state on the next event).
"""

import contextlib
import queue
import threading
from dataclasses import dataclass
from typing import Final

# The only event names the page understands.
# "history" = new chat messages were imported; the browser page ignores it, the app redraws.
# "activity" = the coach is looking something up right now ({character, text, kind}); the
# browser page ignores it, the app shows the newest line in its typing bubble.
EVENT_KINDS: Final = (
    "answer", "question", "save", "error", "signin", "decision", "info", "history", "activity",
)  # fmt: skip
MAILBOX_SIZE: Final = 200


@dataclass(frozen=True, slots=True)
class Event:
    """One thing that happened."""

    kind: str  # one of EVENT_KINDS
    data: dict[str, object]


type Mailbox = queue.Queue[Event | None]  # None means "the program is shutting down"


class EventBus:
    """Hands each event to every subscribed mailbox."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mailboxes: set[Mailbox] = set()
        self._closed = False

    def subscribe(self) -> Mailbox:
        """A new mailbox that receives every event published from now on."""
        mailbox: Mailbox = queue.Queue(maxsize=MAILBOX_SIZE)
        with self._lock:
            if self._closed:
                mailbox.put_nowait(None)
            else:
                self._mailboxes.add(mailbox)
        return mailbox

    def unsubscribe(self, mailbox: Mailbox) -> None:
        """Stop sending to this mailbox (the page went away)."""
        with self._lock:
            self._mailboxes.discard(mailbox)

    def publish(self, kind: str, data: dict[str, object]) -> None:
        """Send an event to everyone listening."""
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind: {kind}")
        event = Event(kind, data)
        with self._lock:
            mailboxes = list(self._mailboxes)
        for mailbox in mailboxes:
            with contextlib.suppress(queue.Full):  # a stuck page must not hold anything up
                mailbox.put_nowait(event)

    def close(self) -> None:
        """Wake every listener with "shutting down" so their connections end."""
        with self._lock:
            self._closed = True
            mailboxes = list(self._mailboxes)
            self._mailboxes.clear()
        for mailbox in mailboxes:
            with contextlib.suppress(queue.Full):
                mailbox.put_nowait(None)
