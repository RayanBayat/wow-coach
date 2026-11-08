"""The window's brain: everything the server and the watcher share.

It holds the settings, the live-event mailbox, the coach engine and the rule "at most one AI
call at a time". The web server (``server.py``) and the save-file watcher (``watcher.py``)
are thin layers on top of it, so the rules live in exactly one place.
"""

import logging
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from wow_coach.advice.contract import AdviceAnswer
from wow_coach.ai.base import AIError, PlanLimitReached, Provider
from wow_coach.app.baseline import AdviceBaseline
from wow_coach.app.contract import Alerts, SignIn
from wow_coach.app.events import EventBus
from wow_coach.app.views import (
    CallCounter,
    GameView,
    answer_to_json,
    build_state,
    load_game,
    open_questions_for,
    question_to_json,
    select_character,
)
from wow_coach.app_settings import (
    AppSettings,
    load_settings,
    save_settings,
    update_settings,
)
from wow_coach.engine.contract import Coach, CoachReply
from wow_coach.errors import WowCoachError
from wow_coach.triggers.state import STATE_FILE_NAME

_log = logging.getLogger(__name__)

ALERT_TITLE = "Your coach answered"
NOTICE_TITLE = "wow-coach"
UNEXPECTED_ERROR = (
    "Something unexpected went wrong inside wow-coach. Nothing was changed. "
    "Please try again, and if it keeps happening, report it on the wow-coach GitHub page."
)
WELCOME_FILE_NAME = "welcome-seen.flag"
KEYCHAIN_PROBLEM = (
    "Your password keychain could not be used. It may be locked: unlock it and try again."
)
NOTHING_TO_ANSWER = "Those questions were already answered."
BUSY_MESSAGE = "The coach is still busy with another answer. Try again in a moment."


class ModelChoice(Protocol):
    """A model the player's plan can use (``ai.chatgpt_plan.PlanModel`` fits)."""

    @property
    def slug(self) -> str:
        """The id to put in the settings."""
        ...

    @property
    def display_name(self) -> str:
        """The name to show the player."""
        ...


class AppCore:
    """Shared state and actions of one running coach window."""

    def __init__(
        self,
        *,
        coach: Coach,
        signin: SignIn,
        alerts: Alerts,
        list_models: Callable[[], Sequence[ModelChoice]],
        settings_file: Path,
        wow_dir: Path,
        usage: CallCounter,
        on_settings_changed: Callable[[AppSettings], None] | None = None,
        triage_provider: Provider | None = None,
        small_model: Callable[[], str | None] | None = None,
        trigger_state_file: Path | None = None,
    ) -> None:
        """Create the core.

        Args:
            coach: The coach engine (a fake in tests).
            signin: The ChatGPT sign-in (a fake in tests).
            alerts: Desktop notifications (a fake in tests).
            list_models: Gives the models the player's plan can use.
            settings_file: Where ``settings.json`` is saved.
            wow_dir: The game folder.
            usage: Counts recent AI calls (``UsageLog``).
            triage_provider: The AI used for the optional triage step (None = no triage).
            small_model: Gives the small model's name for triage (None = no triage).
            trigger_state_file: Where cooldowns are remembered (default: next to settings).
            on_settings_changed: Called with the new settings after each save, so objects
                that copied a setting (such as the usage caps) can follow.
        """
        self.coach = coach
        self.signin = signin
        self.alerts = alerts
        self.wow_dir = wow_dir
        self.bus = EventBus()
        self.baseline = AdviceBaseline(wow_dir)
        # Held while the AI is working: at most one AI call at a time, from anywhere.
        self.ai_lock = threading.Lock()
        self._list_models = list_models
        self._settings_file = settings_file
        self._settings = load_settings(settings_file)
        self._settings_lock = threading.Lock()
        self._on_settings_changed = on_settings_changed
        self._usage = usage
        self.triage_provider = triage_provider
        self._welcome_file = settings_file.with_name(WELCOME_FILE_NAME)
        self._small_model = small_model
        self.trigger_state_file = trigger_state_file or settings_file.with_name(STATE_FILE_NAME)
        self._signin_busy = threading.Lock()
        # (character, question id) pairs already answered: a question is never answered twice.
        self._answered: set[tuple[str, str]] = set()

    # ---- settings ---------------------------------------------------------------------

    @property
    def settings(self) -> AppSettings:
        """The settings in force right now."""
        with self._settings_lock:
            return self._settings

    def change_settings(self, changes: dict[str, object]) -> AppSettings:
        """Apply the player's changes, save them and return the new settings."""
        with self._settings_lock:
            new = update_settings(self._settings, changes)
            save_settings(self._settings_file, new)
            self._settings = new
        if self._on_settings_changed is not None:
            self._on_settings_changed(new)
        return new

    # ---- reading ----------------------------------------------------------------------

    def game(self) -> GameView:
        """The current save file and answers."""
        return load_game(self.wow_dir)

    def state(self, wanted_character: str | None) -> dict[str, object]:
        """Everything the page needs to draw itself."""
        signed_in, keychain_problem = self._read_signed_in()
        state = build_state(
            self.game(),
            wanted=wanted_character,
            signed_in=signed_in,
            settings=self.settings,
            counter=self._usage,
            alerts_available=self.alerts_available(),
        )
        state["welcome_pending"] = signed_in and not self._welcome_file.exists()
        if keychain_problem is not None:
            state["problem"] = " ".join(
                filter(None, [str(state["problem"] or ""), keychain_problem])
            )
        return state

    def _read_signed_in(self) -> tuple[bool, str | None]:
        """(signed in?, a sentence when the keychain could not be read, e.g. it is locked)."""
        try:
            return self.signin.is_signed_in, None
        except AIError:
            return False, KEYCHAIN_PROBLEM

    def signed_in(self) -> bool:
        """True when signed in. A locked keychain counts as "not signed in", not as a crash."""
        return self._read_signed_in()[0]

    # ---- the welcome message (shown once, after the first sign-in) -----------------------

    def welcome_pending(self) -> bool:
        """True when the player is signed in and has not yet pressed "Got it".

        The "seen" flag is a tiny file next to settings.json (in wow-coach's data folder),
        so it survives a different browser or a cleared browser cache.
        """
        return self.signed_in() and not self._welcome_file.exists()

    def dismiss_welcome(self) -> None:
        """Remember that the welcome message was read."""
        self._welcome_file.parent.mkdir(parents=True, exist_ok=True)
        self._welcome_file.write_text("seen\n", encoding="utf-8")

    def alerts_available(self) -> dict[str, bool]:
        """What this computer can do outside the window (notify)."""
        ask = getattr(self.alerts, "available", None)
        found = ask() if callable(ask) else {}
        return {"notify": bool(found.get("notify", True))}

    def models(self) -> list[dict[str, str]]:
        """The models the plan can use, as ``{slug, name}`` dicts."""
        return [{"slug": m.slug, "name": m.display_name} for m in self._list_models()]

    # ---- AI work (one at a time) ------------------------------------------------------

    def start_ask(self, question: str, character: str | None) -> bool:
        """Ask in the background. False when the coach is busy (nothing was started)."""
        return self._start_ai_job(lambda: self._ask_now(question, character))

    def start_answer_open(self, character: str | None) -> str:
        """Answer the game's open questions in the background.

        Returns "started", "busy" (another answer is running) or "none" (nothing to answer).
        """
        game = self.game()
        chosen = select_character(game, character)
        if chosen is None or not self.unanswered_questions(chosen.key, game):
            return "none"
        key = chosen.key
        started = self._start_ai_job(lambda: self.answer_open_now(key, alert=False))
        return "started" if started else "busy"

    def _start_ai_job(self, job: Callable[[], None]) -> bool:
        if not self.ai_lock.acquire(blocking=False):
            return False

        def run() -> None:
            try:
                self.report_errors(job)
            finally:
                self.ai_lock.release()

        threading.Thread(target=run, name="coach-ai-job", daemon=True).start()
        return True

    def _ask_now(self, question: str, character: str | None) -> None:
        reply = self.coach.ask(question, character=character)
        self.publish_reply(reply)

    def answer_open_now(self, character: str | None, *, alert: bool) -> None:
        """Answer open questions now. The caller must hold ``ai_lock``."""
        waiting = self._open_ids(character)
        replies = self.coach.answer_open_questions(character=character)
        # The engine skips questions it already answered (its own list), and replies lack an
        # id at worst. Either way, every question that was waiting now counts as answered, so
        # one save can never cost the plan twice.
        self._answered.update(waiting)
        if not replies:
            self.bus.publish("info", {"text": NOTHING_TO_ANSWER})
        for reply in replies:
            self.publish_reply(reply)
            if alert:
                self.alert(reply.answer)

    def _open_ids(self, character: str | None) -> list[tuple[str, str]]:
        """(character, question id) of every open question of this character, oldest first."""
        game = self.game()
        chosen = select_character(game, character)
        if chosen is None:
            return []
        return [(chosen.key, q.id) for q in open_questions_for(game, chosen)]

    def unanswered_questions(self, character_key: str, game: GameView) -> bool:
        """True when this character has open questions we have not answered yet."""
        character = select_character(game, character_key)
        found = open_questions_for(game, character)
        return any((character_key, q.id) not in self._answered for q in found)

    def report_errors(self, work: Callable[[], None]) -> None:
        """Run ``work``; any failure becomes an ``error`` event with a plain sentence."""
        try:
            work()
        except PlanLimitReached as error:
            self.publish_error(str(error), kind="limit")
        except AIError as error:
            self.publish_error(str(error))
        except WowCoachError as error:
            self.publish_error(str(error))
        except Exception:
            _log.exception("Unexpected failure in a background job")
            self.publish_error(UNEXPECTED_ERROR)

    # ---- events and alerts ------------------------------------------------------------

    def publish_error(self, message: str, kind: str = "error") -> None:
        """Tell every open window about a problem, in one plain sentence.

        ``kind`` is "limit" when the plan's (or the player's own) usage limit was reached:
        the page then offers "Manage usage" as the main action.
        """
        self.bus.publish("error", {"message": message, "kind": kind})

    def publish_reply(self, reply: CoachReply) -> None:
        """Send a finished answer to the window (and remember its question as answered).

        The answer was just written by wow-coach, so it is also noted as "our own": only
        answers written by someone else count as outside changes.
        """
        self.baseline.note_own_answer(reply.character_key, reply.answer)
        if reply.answer.question_id is not None:
            self._answered.add((reply.character_key, reply.answer.question_id))
        self.bus.publish(
            "answer",
            {
                "character": reply.character_key,
                "answer": answer_to_json(reply.answer),
                "note": reply.note,
                "written_to_game": reply.written_to_game,
            },
        )

    def publish_outside_answer(self, character_key: str, answer: AdviceAnswer) -> None:
        """Send an answer that someone else wrote into ``Advice.lua``."""
        self.bus.publish(
            "answer",
            {
                "character": character_key,
                "answer": answer_to_json(answer),
                "note": "",
                "written_to_game": True,
            },
        )

    def publish_questions(self, character_key: str, game: GameView) -> None:
        """Tell the window which questions from the game are still open."""
        found = open_questions_for(game, select_character(game, character_key))
        if found:
            self.bus.publish(
                "question",
                {"character": character_key, "questions": [question_to_json(q) for q in found]},
            )

    def small_model(self) -> str | None:
        """The small model's name for triage, or None when unknown."""
        return None if self._small_model is None else self._small_model()

    def notify_text(self, text: str) -> None:
        """A desktop notification for something the coach noticed (if notifications are on)."""
        if self.settings.notify:
            self._safely(lambda: self.alerts.notify(NOTICE_TITLE, text))

    def alert(self, answer: AdviceAnswer) -> None:
        """Notify according to the settings. Never raises."""
        if self.settings.notify:
            self._safely(lambda: self.alerts.notify(ALERT_TITLE, answer.title))

    @staticmethod
    def _safely(action: Callable[[], object]) -> None:
        try:
            action()
        except Exception:
            _log.exception("Could not tell the player outside the window")

    # ---- sign-in ----------------------------------------------------------------------

    def start_sign_in(self) -> bool:
        """Start the browser sign-in in the background. False if one is already running."""
        if not self._signin_busy.acquire(blocking=False):
            return False

        def run() -> None:
            try:
                self.report_errors(self._sign_in_now)
            finally:
                self._signin_busy.release()

        threading.Thread(target=run, name="coach-sign-in", daemon=True).start()
        return True

    def _sign_in_now(self) -> None:
        def on_url(url: str) -> None:
            self.bus.publish("signin", {"state": "waiting", "url": url})

        self.signin.sign_in(on_url)
        self.bus.publish("signin", {"state": "signed_in"})

    def sign_out(self) -> bool:
        """Sign out. False when OpenAI did not confirm (the sign-in is gone here anyway)."""
        confirmed = self.signin.sign_out()
        self.bus.publish("signin", {"state": "signed_out"})
        return confirmed
