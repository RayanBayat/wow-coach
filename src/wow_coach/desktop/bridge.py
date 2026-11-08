"""The bridge between the Qt windows and the coach's brain (``AppCore``).

Two rules keep the app smooth:

1. **The window never waits.** Reading the state reads the game's save file, and the game
   may live on a slow hard disk. Signing out and listing models talk to the internet. So all
   of that runs in a background thread, and the result comes back as a Qt signal.
2. **Qt widgets only talk to this bridge**, never to ``AppCore`` directly. Tests can then
   drive the windows with a fake core.

Qt signals are safe to emit from a background thread: Qt delivers them to the window's
thread, so the pages always run in one thread and need no locks.
"""

import contextlib
import logging
import queue
import threading
from collections.abc import Callable, Mapping
from typing import Final, Protocol

from PySide6.QtCore import QObject, Signal

from wow_coach.app.events import EventBus, Mailbox
from wow_coach.app_settings import AppSettings
from wow_coach.desktop.state import StateView, read_state

_log = logging.getLogger(__name__)

READ_PROBLEM: Final = (
    "wow-coach could not read its data just now. It will try again on the next change."
)

type Runner = Callable[[Callable[[], None]], None]


class CoreLike(Protocol):
    """What the bridge needs from ``AppCore`` (tests pass a fake with the same methods)."""

    bus: EventBus

    def state(self, wanted_character: str | None) -> dict[str, object]:
        """Everything the window needs to draw itself."""
        ...

    def start_ask(self, question: str, character: str | None) -> bool:
        """Ask in the background; False when the coach is busy."""
        ...

    def start_answer_open(self, character: str | None) -> str:
        """Answer the game's open questions: "started", "busy" or "none"."""
        ...

    def change_settings(self, changes: dict[str, object]) -> AppSettings:
        """Save the player's changes and return the new settings."""
        ...

    def models(self) -> list[dict[str, str]]:
        """The models the plan can use (talks to the internet)."""
        ...

    def start_sign_in(self) -> bool:
        """Start the browser sign-in in the background; False if one is running."""
        ...

    def sign_out(self) -> bool:
        """Sign out (talks to the internet); False when OpenAI did not confirm."""
        ...

    def dismiss_welcome(self) -> None:
        """Remember that the player read the welcome message."""
        ...


def run_in_thread(work: Callable[[], None]) -> None:
    """Run ``work`` in a background thread (the default ``Runner``)."""
    threading.Thread(target=work, name="desktop-work", daemon=True).start()


class CoreBridge(QObject):
    """Turns the core's events into Qt signals and runs slow work off the window's thread."""

    # (kind, data): one live event from the core ("answer", "save", "error"...).
    event_arrived = Signal(str, object)
    # A fresh StateView, after every change.
    state_changed = Signal(object)
    # The models the plan can use: a list of {"slug", "name"} dicts (empty when unknown).
    models_loaded = Signal(object)
    # True when OpenAI confirmed the sign-out.
    signed_out = Signal(bool)

    def __init__(self, core: CoreLike, *, runner: Runner = run_in_thread) -> None:
        """Create the bridge.

        Args:
            core: The coach's brain (``AppCore``), or a fake in tests.
            runner: How slow work is started; tests pass one that runs it at once.
        """
        super().__init__()
        self._core = core
        self._run = runner
        self._selected: str | None = None
        self._latest = StateView()
        self._mailbox: Mailbox | None = None
        # The state is read by one background job at a time. A refresh asked for while one
        # is running sets ``_again``, and the running job simply reads once more.
        self._lock = threading.Lock()
        self._reading = False
        self._again = False

    # ---- starting and stopping ---------------------------------------------------------

    def start(self) -> None:
        """Start listening to the core's events and read the state once."""
        self._mailbox = self._core.bus.subscribe()
        mailbox = self._mailbox
        threading.Thread(
            target=lambda: self._listen(mailbox), name="desktop-events", daemon=True
        ).start()
        self.refresh_state()

    def stop(self) -> None:
        """Stop listening (the app is closing)."""
        mailbox, self._mailbox = self._mailbox, None
        if mailbox is not None:
            self._core.bus.unsubscribe(mailbox)
            # Wake the listening thread so it ends. A full mailbox doesn't matter: the thread
            # is a daemon thread, so it ends with the app anyway.
            with contextlib.suppress(queue.Full):
                mailbox.put_nowait(None)

    def _listen(self, mailbox: Mailbox) -> None:
        """Background thread: forward each event, then read the state again."""
        while True:
            event = mailbox.get()
            if event is None:
                return
            self.event_arrived.emit(event.kind, event.data)
            self.refresh_state()

    # ---- the state ----------------------------------------------------------------------

    @property
    def latest_state(self) -> StateView:
        """The newest state read so far (an empty state before the first read)."""
        return self._latest

    @property
    def selected_character(self) -> str | None:
        """The character the window shows (None = the newest save)."""
        return self._selected

    def select_character(self, key: str | None) -> None:
        """Show another character, and read its state."""
        self._selected = key
        self.refresh_state()

    def refresh_state(self) -> None:
        """Read the state in the background; ``state_changed`` brings the result."""
        with self._lock:
            if self._reading:
                self._again = True
                return
            self._reading = True
        self._run(self._read_until_current)

    def _read_until_current(self) -> None:
        while True:
            view = self._read_once()
            self._latest = view
            self.state_changed.emit(view)
            with self._lock:
                if not self._again:
                    self._reading = False
                    return
                self._again = False

    def _read_once(self) -> StateView:
        try:
            return read_state(self._core.state(self._selected))
        except Exception:
            # A page must always be able to draw something, so a failure becomes a sentence.
            _log.exception("Could not read the state for the desktop window")
            return StateView(problem=READ_PROBLEM)

    # ---- actions ------------------------------------------------------------------------

    def ask(self, question: str) -> bool:
        """Ask the coach about the shown character. False when it is busy with another answer."""
        return self._core.start_ask(question, self._selected)

    def answer_open_questions(self) -> str:
        """Answer the questions typed in game: "started", "busy" or "none"."""
        return self._core.start_answer_open(self._selected)

    def change_settings(self, changes: Mapping[str, object]) -> AppSettings:
        """Save setting changes (a small local file, so this is quick) and redraw."""
        new = self._core.change_settings(dict(changes))
        self.refresh_state()
        return new

    def load_models(self) -> None:
        """Fetch the plan's models in the background; ``models_loaded`` brings them."""

        def work() -> None:
            try:
                found = self._core.models()
            except Exception:
                _log.exception("Could not list the plan's models")
                found = []
            self.models_loaded.emit(found)

        self._run(work)

    def start_sign_in(self) -> bool:
        """Open OpenAI's sign-in page; "signin" events tell how it goes."""
        return self._core.start_sign_in()

    def sign_out(self) -> None:
        """Sign out in the background; ``signed_out`` brings the result."""

        def work() -> None:
            try:
                confirmed = self._core.sign_out()
            except Exception:
                _log.exception("Sign-out failed")
                confirmed = False
            self.signed_out.emit(confirmed)
            self.refresh_state()

        self._run(work)

    def dismiss_welcome(self) -> None:
        """Remember that the welcome message was read, and redraw."""
        self._core.dismiss_welcome()
        self.refresh_state()
