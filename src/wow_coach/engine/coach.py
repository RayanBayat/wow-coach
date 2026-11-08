"""``ChatCoach``: answers questions with the player's AI and shows them in the Coach panel.

One question goes through these steps: load the character from the save, build the
messages, ask the AI, read the JSON reply, write it to ``Advice.lua`` and remember the
conversation. An ``AIError`` is not caught here: the window or the CLI shows its sentence.
"""

import contextlib
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Final

from wow_coach.advice.contract import (
    ADVICE_ADDON_NAME,
    ADVICE_FILE_NAME,
    AdviceAnswer,
    AdviceFile,
    Question,
)
from wow_coach.advice.limits import limit_answer
from wow_coach.advice.merge import add_answer
from wow_coach.advice.questions import open_questions
from wow_coach.advice.reader import read_advice_file
from wow_coach.advice.writer import interface_from_coachlink, update_advice
from wow_coach.ai.base import Provider
from wow_coach.app_settings import AppSettings
from wow_coach.characters import pick_character
from wow_coach.engine.answer import ANSWER_SCHEMA, parse_answer
from wow_coach.engine.contract import CoachReply
from wow_coach.engine.conversation import Turn, append_turns, conversation_path, load_turns
from wow_coach.engine.memory import LocalMemory
from wow_coach.engine.prompt import PromptData, build_messages
from wow_coach.engine.redact import other_player_names, without_own_names
from wow_coach.errors import WowCoachError
from wow_coach.notes import journal_path, notes_path
from wow_coach.report import format_history, format_status
from wow_coach.savedvars import Character, find_saved_variables, load_characters

MAX_OUTPUT_TOKENS: Final = 800
HISTORY_EVENTS: Final = 10
_WRITE_ERRORS: Final = (WowCoachError, OSError, ValueError, OverflowError, RecursionError)


class NoSuchCharacterError(WowCoachError):
    """The save has no character with the requested name."""


def _read_text_or_empty(path: Path) -> str:
    """A text file's content; empty when it is missing or unreadable."""
    try:
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    except OSError:
        return ""


def _saved_at(character: Character) -> int | None:
    value = character.snapshot.get("savedAt")
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _answer_as_text(answer: AdviceAnswer) -> str:
    """The answer in one piece of text, for the conversation memory."""
    steps = "; ".join(answer.steps)
    return " ".join(part for part in (answer.title + ".", steps, answer.text) if part)


class ChatCoach:
    """The coach engine (see ``engine/contract.py``) on top of any ``Provider``."""

    def __init__(
        self,
        provider: Provider,
        *,
        model: str,
        wow_dir: Path,
        environ: Mapping[str, str],
        settings: AppSettings,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._provider = provider
        self._model = model
        self._wow_dir = wow_dir
        self._environ = environ
        self._settings = settings
        self._now = now
        self._memory = LocalMemory(environ=environ)
        self._own_characters: frozenset[str] = frozenset()  # every character in the save

    # ---- the Coach contract ---------------------------------------------------------

    def ask(self, question: str, *, character: str | None = None) -> CoachReply:
        """Answer a question typed outside the game."""
        text = question.strip()
        if not text:
            raise WowCoachError("Type a question first.")
        return self._answer(self._load_character(character), text, None)

    def answer_open_questions(self, *, character: str | None = None) -> list[CoachReply]:
        """Answer every question from the Coach panel that has no answer yet."""
        found = self._load_character(character)
        advice = read_advice_file(self._advice_path())
        done = self._memory.answered_ids(found.key)
        todo = [q for q in open_questions(found, advice) if q.id not in done]
        return [self._answer(found, item.text, item) for item in todo]

    # ---- steps ---------------------------------------------------------------------

    def _advice_path(self) -> Path:
        return self._wow_dir / "Interface" / "AddOns" / ADVICE_ADDON_NAME / ADVICE_FILE_NAME

    def _load_character(self, wanted: str | None) -> Character:
        """Read the save and pick the character. Raises a plain ``WowCoachError`` if none."""
        characters = load_characters(find_saved_variables(self._wow_dir))
        found = pick_character(characters, wanted)
        if found is None:
            known = ", ".join(sorted(characters)) or "none yet"
            raise NoSuchCharacterError(
                f"No saved character matches {wanted!r}. Characters in the save: {known}."
            )
        self._own_characters = frozenset(key.split("-", 1)[0] for key in characters)
        return found

    def _prompt_data(self, found: Character, question: str, turns: list[Turn]) -> PromptData:
        now = self._now()
        return PromptData(
            status=format_status(found.snapshot, now=now),
            history=format_history(found.history, limit=HISTORY_EVENTS, now=now),
            journal=self._coach_notes(journal_path(found.key, environ=self._environ)),
            player_notes=self._coach_notes(notes_path(environ=self._environ)),
            turns=turns,
            question=question,
        )

    def _coach_notes(self, path: Path) -> str:
        """A notes file's text, or nothing when the player keeps their notes to themselves."""
        return _read_text_or_empty(path) if self._settings.send_coach_notes else ""

    def _names_to_hide(self, found: Character) -> set[str]:
        """Other players' names in this save plus those seen in earlier saves."""
        if self._settings.share_other_player_names:
            return set()
        current = other_player_names(found, own=self._own_characters)
        with contextlib.suppress(OSError):
            self._memory.add_seen_names(found.key, current)
        return without_own_names(
            current | self._memory.seen_names(found.key), found, own=self._own_characters
        )

    def _answer(self, found: Character, question: str, asked: Question | None) -> CoachReply:
        turns = load_turns(conversation_path(found.key, environ=self._environ))
        hidden = self._names_to_hide(found)
        messages = build_messages(self._prompt_data(found, question, turns), hidden_names=hidden)
        reply = self._provider.ask(
            messages,
            model=self._model,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            json_schema=ANSWER_SCHEMA,
        )
        parsed = parse_answer(reply.text, answered_at=int(self._now()), source=self._provider.name)
        answer = self._tie_to_question(parsed, asked)
        if asked is not None:  # before the write, which may fail
            with contextlib.suppress(OSError):
                self._memory.add_answered(found.key, asked.id)
        written, note = self._write(found, answer)
        self._remember(found.key, question, answer)
        return CoachReply(
            character_key=found.key, answer=answer, written_to_game=written, note=note
        )

    @staticmethod
    def _tie_to_question(answer: AdviceAnswer, asked: Question | None) -> AdviceAnswer:
        """Mark the answer as the one for a game question, so the question counts as answered."""
        if asked is None:
            return answer
        return limit_answer(
            replace(answer, question_id=asked.id, question=asked.text, asked_at=asked.asked_at)
        )

    def _write(self, found: Character, answer: AdviceAnswer) -> tuple[bool, str]:
        """Put the answer in Advice.lua. Returns (written, a plain note for the player)."""
        addons_dir = self._wow_dir / "Interface" / "AddOns"
        first_time = not (addons_dir / ADVICE_ADDON_NAME).exists()

        def change(current: AdviceFile) -> AdviceFile:
            return add_answer(
                current,
                found.key,
                answer,
                based_on_save=_saved_at(found),
                now=answer.answered_at,
            )

        try:
            update_advice(
                addons_dir,
                change,
                interface=interface_from_coachlink(addons_dir),
                now=answer.answered_at,
            )
        except _WRITE_ERRORS as error:
            return False, f"The answer is here, but it could not be saved for the game: {error}"
        if first_time:
            return True, (
                "In the game after you restart it completely once (a /reload is not enough "
                "the first time). After that, a /reload shows new answers."
            )
        return True, "In the game after your next /reload."

    def _remember(self, character_key: str, question: str, answer: AdviceAnswer) -> None:
        """Keep the question and answer for follow-ups. A failure here is not worth an error."""
        turns = [Turn("user", question), Turn("assistant", _answer_as_text(answer))]
        with contextlib.suppress(OSError):
            append_turns(conversation_path(character_key, environ=self._environ), turns)
