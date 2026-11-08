"""Turns wow-coach's data into plain JSON-friendly dicts for the window.

Nothing here changes anything: it reads the game's save file and ``Advice.lua`` and
describes them. Every function returns simple values (str, int, list, dict) so the server
can send them as JSON.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from wow_coach.advice.contract import AdviceAnswer, AdviceFile, Question
from wow_coach.advice.paths import advice_file_path
from wow_coach.advice.questions import open_questions
from wow_coach.advice.reader import read_advice_file
from wow_coach.app_settings import AppSettings, settings_to_dict
from wow_coach.characters import pick_character
from wow_coach.errors import CoachDataMissing, WowCoachError
from wow_coach.savedvars import Character, find_saved_variables, load_characters
from wow_coach.usage import DAY_SECONDS, HOUR_SECONDS

NO_SAVE_YET = "No saved game data yet. In the game, type /coach once, then come back."


class CallCounter(Protocol):
    """Anything that can say how many AI calls happened recently (``UsageLog`` does)."""

    def calls_in_last(self, seconds: float) -> int:
        """Number of calls in the last ``seconds`` seconds."""
        ...


@dataclass(frozen=True, slots=True)
class GameView:
    """What the game folder holds right now."""

    characters: dict[str, Character]
    advice: AdviceFile | None
    problem: str | None  # a plain sentence when the save can't be read, else None


def load_game(wow_dir: Path) -> GameView:
    """Read the save file and ``Advice.lua``. Problems become a sentence, never an error."""
    advice = read_advice_file(advice_file_path(wow_dir))
    try:
        characters = load_characters(find_saved_variables(wow_dir))
    except CoachDataMissing:
        return GameView({}, advice, NO_SAVE_YET)
    except WowCoachError, OSError:
        return GameView({}, advice, "The game's save file could not be read. Try /reload in game.")
    return GameView(characters, advice, None if characters else NO_SAVE_YET)


def answer_to_json(answer: AdviceAnswer) -> dict[str, object]:
    """One answer as the page shows it."""
    return {
        "title": answer.title,
        "steps": list(answer.steps),
        "text": answer.text,
        "warnings": list(answer.warnings),
        "source": answer.source,
        "answered_at": answer.answered_at,
        "question": answer.question,
        "question_id": answer.question_id,
    }


def question_to_json(question: Question) -> dict[str, object]:
    """One open question from the game."""
    return {"id": question.id, "text": question.text, "asked_at": question.asked_at}


def settings_to_json(settings: AppSettings) -> dict[str, object]:
    """The settings as plain values."""
    return settings_to_dict(settings)


def select_character(game: GameView, wanted: str | None) -> Character | None:
    """The character the window shows: the one asked for, else the newest save."""
    chosen = pick_character(game.characters, wanted) if wanted else None
    return chosen or pick_character(game.characters, None)


def answers_for(game: GameView, character_key: str | None) -> list[dict[str, object]]:
    """The character's answers, newest first."""
    if game.advice is None or character_key is None:
        return []
    if character_key not in game.advice.characters:
        return []
    entry = game.advice.characters[character_key]
    return [answer_to_json(answer) for answer in reversed(entry.answers)]


def open_questions_for(game: GameView, character: Character | None) -> list[Question]:
    """Questions from the game's Coach panel that have no answer yet."""
    return [] if character is None else open_questions(character, game.advice)


def saved_at(character: Character | None) -> int | None:
    """When the game last saved this character (Unix time), or None."""
    if character is None:
        return None
    value = character.snapshot.get("savedAt")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def usage_counts(counter: CallCounter, settings: AppSettings) -> dict[str, int]:
    """How many AI calls were made in the last hour and day, with the player's caps."""
    return {
        "last_hour": counter.calls_in_last(HOUR_SECONDS),
        "last_day": counter.calls_in_last(DAY_SECONDS),
        "hour_cap": settings.max_calls_per_hour,
        "day_cap": settings.max_calls_per_day,
    }


def build_state(
    game: GameView,
    *,
    wanted: str | None,
    signed_in: bool,
    settings: AppSettings,
    counter: CallCounter,
    alerts_available: dict[str, bool],
) -> dict[str, object]:
    """Everything the page needs to draw itself, in one dict."""
    character = select_character(game, wanted)
    key = None if character is None else character.key
    return {
        "signed_in": signed_in,
        "settings": settings_to_json(settings),
        "characters": sorted(game.characters),
        "selected": key,
        "answers": answers_for(game, key),
        "open_questions": [question_to_json(q) for q in open_questions_for(game, character)],
        "usage": usage_counts(counter, settings),
        "last_save": saved_at(character),
        "alerts": alerts_available,
        "problem": game.problem,
    }
