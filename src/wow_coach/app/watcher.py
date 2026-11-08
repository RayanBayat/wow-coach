"""Watches the game folder and reacts: a new save, or a change to ``Advice.lua``.

Every 2 seconds it asks the operating system when two files last changed (a ``stat`` call,
answered from memory, so a slow game hard disk is never woken up). It only reads a file
after its change time moved.

* A **new save** (the player typed /coach, /reload or logged out): tell the window, show the
  open questions, and, if the player allowed it and is signed in, answer them.
* **``Advice.lua`` changed from outside** (for example the Claude Code coach wrote it):
  tell the window and notify. It never speaks and never calls the AI for this.
"""

import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from wow_coach.app.core import AppCore
from wow_coach.app.speakup import SpeakUp
from wow_coach.app.views import saved_at, select_character
from wow_coach.watch import ChangeTimes, change_times

POLL_SECONDS = 2.0
SETTLE_SECONDS = 1.0  # the game may still be writing right after the change time moves
TIMER_CHECK_SECONDS = 60.0  # how often the timer rule is looked at


class Watcher:
    """Polls the files in a background thread (or one step at a time, in tests)."""

    def __init__(
        self,
        core: AppCore,
        wow_dir: Path,
        *,
        poll_seconds: float = POLL_SECONDS,
        settle_seconds: float = SETTLE_SECONDS,
        clock: Callable[[], float] = time.time,
        local_hour: Callable[[], int] = lambda: datetime.now().hour,
    ) -> None:
        self._core = core
        self._wow_dir = wow_dir
        self._poll = poll_seconds
        self._settle = settle_seconds
        # Saves that already exist are not "new": only later changes count.
        self._save_times: ChangeTimes = change_times(wow_dir)
        self._speak_up = SpeakUp(core, core.trigger_state_file, clock=clock, local_hour=local_hour)
        self._next_timer_check = time.monotonic() + TIMER_CHECK_SECONDS
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Begin polling in a background thread."""
        self._thread = threading.Thread(target=self._run, name="coach-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop polling and wait for the thread to end."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self._poll):
            if self._save_changed():
                self._stop.wait(self._settle)  # let the game finish writing
            self.check_once()
            if time.monotonic() >= self._next_timer_check:
                self._next_timer_check = time.monotonic() + TIMER_CHECK_SECONDS
                self.check_timer()

    def check_timer(self) -> None:
        """Let the timer rule fire if its time has come (no save needed)."""
        self._core.report_errors(self._speak_up.on_timer)

    def _save_changed(self) -> bool:
        return change_times(self._wow_dir) != self._save_times

    def check_once(self) -> None:
        """Look at both files once and react to whatever changed."""
        self._core.report_errors(self._react)

    def _react(self) -> None:
        now = change_times(self._wow_dir)
        if now != self._save_times:
            self._save_times = now
            self._on_new_save()
        self._on_advice_file_change()

    # ---- a new save -------------------------------------------------------------------

    def _on_new_save(self) -> None:
        core = self._core
        game = core.game()
        newest = select_character(game, None)
        core.bus.publish("save", {"saved_at": saved_at(newest), "problem": game.problem})
        waiting = [key for key in sorted(game.characters) if core.unanswered_questions(key, game)]
        for key in waiting:
            core.publish_questions(key, game)
        settings = core.settings
        try:
            if waiting and settings.answer_questions_from_game and core.signed_in():
                self._answer(waiting)
        finally:
            self._speak_up.on_save(game.characters)  # runs even if answering failed

    def _answer(self, character_keys: list[str]) -> None:
        core = self._core
        with core.ai_lock:  # waits for any running answer: one AI call at a time
            for key in character_keys:
                # Look again inside the lock: a click on "Answer now" may have just done it.
                if core.unanswered_questions(key, core.game()):
                    core.answer_open_now(key, alert=True)

    # ---- Advice.lua written by someone else -------------------------------------------

    def _on_advice_file_change(self) -> None:
        core = self._core
        # Look while holding the AI lock: the coach's own writes are never announced as
        # outside answers, and an outside write during a call is announced after it.
        if not core.ai_lock.acquire(blocking=False):
            return  # the coach is busy right now; look again next time
        try:
            changes = core.baseline.outside_changes()
        finally:
            core.ai_lock.release()
        for key, answer in changes:
            core.publish_outside_answer(key, answer)
            core.alert(answer, allow_speak=False)
