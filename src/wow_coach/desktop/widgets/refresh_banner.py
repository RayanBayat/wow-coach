"""The banner that guides the player through "Refresh game data".

A program outside the game can never press keys in WoW (Blizzard's rules), so we cannot
refresh the data ourselves. Instead the banner tells the player how to do it and waits for
the watcher's ``save`` event. It has three states:

* ``idle``: hidden.
* ``waiting``: "Press your Save for the coach key...", with moving dots and a Cancel button.
  After two minutes a hint asks whether the addon is turned on.
* ``done``: "Got it: fresh data from just now", which fades away by itself.
"""

import time
from collections.abc import Callable
from typing import Final, Literal

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from wow_coach.desktop.theme import SPACE, SPACE_SMALL
from wow_coach.desktop.widgets.animation import fade, remove_effect
from wow_coach.desktop.widgets.bubbles import TypingIndicator, plain_label
from wow_coach.desktop.widgets.formatting import relative_time

type BannerState = Literal["idle", "waiting", "done"]

WAITING_TEXT: Final = (
    "Press your Save for the coach key in WoW, or type /coach. "
    "The game reloads for a few seconds, then this updates by itself."
)
KEY_TIP: Final = "Set the key: Options → Keybindings → CoachLink"
STILL_WAITING_TEXT: Final = (
    "Still waiting. Is the CoachLink addon turned on in the game's AddOns list?"
)
HINT_AFTER_SECONDS: Final = 120.0  # how long to wait before asking about the addon
DONE_VISIBLE_MS: Final = 4_000  # how long the success message stays before it fades


class RefreshBanner(QFrame):
    """The inline refresh helper. It never blocks the window (it is not a dialog)."""

    # Emitted when the player cancels, so the page can ask a waiting question right away.
    cancelled = Signal()
    # Emitted when the banner is hidden again after a success (or a cancel).
    closed = Signal()

    def __init__(
        self,
        *,
        now: Callable[[], float] = time.time,
        done_visible_ms: int = DONE_VISIBLE_MS,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("refreshBanner")
        self._now = now
        self._started_at = 0.0
        self._state: BannerState = "idle"
        self.setProperty("state", "idle")

        column = QVBoxLayout(self)
        column.setContentsMargins(SPACE, SPACE - 2, SPACE, SPACE - 2)
        column.setSpacing(SPACE_SMALL)
        top = QHBoxLayout()
        top.setSpacing(SPACE)
        self._dots = TypingIndicator()
        top.addWidget(self._dots)
        self._message = plain_label(WAITING_TEXT)
        top.addWidget(self._message, 1)
        self._cancel = QPushButton("Cancel")
        self._cancel.setProperty("kind", "ghost")
        self._cancel.setToolTip("Stop waiting for new game data. Nothing is changed.")
        self._cancel.clicked.connect(self.cancel)
        top.addWidget(self._cancel)
        column.addLayout(top)
        self._tip = plain_label(KEY_TIP, "small")
        column.addWidget(self._tip)
        self._hint = plain_label(STILL_WAITING_TEXT, "muted")
        column.addWidget(self._hint)

        # Looks once a second whether it is time for the hint (the clock is injected in tests).
        self._ticker = QTimer(self)
        self._ticker.setInterval(1_000)
        self._ticker.timeout.connect(self.tick)
        self._done_timer = QTimer(self)
        self._done_timer.setSingleShot(True)
        self._done_timer.setInterval(done_visible_ms)
        self._done_timer.timeout.connect(self._fade_away)
        self.hide()

    # ---- reading ------------------------------------------------------------------------

    @property
    def state(self) -> BannerState:
        """``idle``, ``waiting`` or ``done``."""
        return self._state

    @property
    def message(self) -> str:
        """The main sentence now shown."""
        return self._message.text()

    @property
    def hint_visible(self) -> bool:
        """True when the "Still waiting" hint is shown."""
        return not self._hint.isHidden()

    # ---- the three moves ----------------------------------------------------------------

    def start(self) -> None:
        """Show the instructions and begin waiting for a save."""
        self._done_timer.stop()
        self._started_at = self._now()
        self._set_state("waiting")
        self._message.setText(WAITING_TEXT)
        self._tip.show()
        self._hint.hide()
        self._cancel.show()
        self._dots.show()
        self._ticker.start()
        remove_effect(self)
        self.show()

    def cancel(self) -> None:
        """Stop waiting (the player pressed Cancel)."""
        if self._state != "waiting":
            return
        self._hide_now()
        self.cancelled.emit()

    def mark_saved(self, saved_at: int | None) -> None:
        """A ``save`` event arrived: turn into a success message that fades away."""
        if self._state != "waiting":
            return
        self._ticker.stop()
        age = 0.0 if saved_at is None else self._now() - saved_at
        self._set_state("done")
        self._message.setText(f"Got it: fresh data from {relative_time(age)}")
        self._tip.hide()
        self._hint.hide()
        self._cancel.hide()
        self._dots.hide()
        self._done_timer.start()

    # ---- time ---------------------------------------------------------------------------

    def tick(self) -> None:
        """Show the "Still waiting" hint once the wait has been long enough."""
        if self._state == "waiting" and self._now() - self._started_at >= HINT_AFTER_SECONDS:
            self._hint.show()

    # ---- helpers ------------------------------------------------------------------------

    def _set_state(self, state: BannerState) -> None:
        self._state = state
        self.setProperty("state", state)
        self.style().unpolish(self)  # make Qt re-read the stylesheet for the new state
        self.style().polish(self)

    def _fade_away(self) -> None:
        fade(self, start=1.0, end=0.0, on_done=self._hide_now)

    def _hide_now(self) -> None:
        self._ticker.stop()
        self._done_timer.stop()
        self._set_state("idle")
        self.hide()
        remove_effect(self)
        self.closed.emit()
