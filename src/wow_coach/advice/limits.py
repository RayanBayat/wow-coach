"""Check and cut advice down to the limits in ``contract`` before it is written.

The addon can't hold unlimited text, so wow-coach shortens what is too long instead of
failing: text is cut on whole characters, numbers are kept in a sane range, and only the
newest answers are kept.

Two kinds of text are treated differently:

* **Display text** (titles, steps, text, warnings, the question): cut to the limit, and
  ``|`` is doubled when written, so it can never become a color code or link.
* **Identifiers** (character keys, question ids): never changed. If one is not valid it is
  refused or left out, because a changed id would no longer match the game's.
"""

import re

from wow_coach.advice.contract import (
    MAX_ANSWERED_IDS,
    MAX_ANSWERS_PER_CHARACTER,
    MAX_CHARACTER_KEY_CHARS,
    MAX_CHARACTERS,
    MAX_QUESTION_CHARS,
    MAX_SOURCE_CHARS,
    MAX_STEP_CHARS,
    MAX_STEPS,
    MAX_TEXT_CHARS,
    MAX_TITLE_CHARS,
    MAX_WARNINGS,
    QUESTION_ID_PATTERN,
    AdviceAnswer,
    AdviceFile,
    CharacterAdvice,
    CoachPlan,
)
from wow_coach.errors import WowCoachError

MAX_NUMBER = 2**40  # far beyond any Unix time we will see, far below Lua's exact-number limit
_QUESTION_ID = re.compile(QUESTION_ID_PATTERN)


class AdviceInvalid(WowCoachError):  # noqa: N818  (reads better than "...Error")
    """The advice holds something that can't be written: a wrong type or a bad character key."""


# ---- single values ---------------------------------------------------------------------


def clean_text(text: str, limit: int) -> str:
    """Make ``text`` safe and short: no lone surrogates, at most ``limit`` characters.

    A lone surrogate can't be written as UTF-8, so it becomes the replacement character.
    Python slices strings by whole characters, so a letter is never cut in half.
    """
    if not isinstance(text, str):
        raise AdviceInvalid(f"Expected text but got {type(text).__name__}.")
    fixed = "".join("�" if 0xD800 <= ord(char) <= 0xDFFF else char for char in text)
    return fixed[:limit]


def clamp_int(value: int) -> int:
    """Keep a number (a Unix time) between 0 and ``MAX_NUMBER``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdviceInvalid(f"Expected a whole number but got {type(value).__name__}.")
    return max(0, min(value, MAX_NUMBER))


def _clamp_optional(value: int | None) -> int | None:
    return None if value is None else clamp_int(value)


def is_valid_question_id(question_id: str) -> bool:
    """True for ids the addon makes: ``<time>-<counter>``."""
    return isinstance(question_id, str) and _QUESTION_ID.fullmatch(question_id) is not None


def is_valid_character_key(key: str) -> bool:
    """True for a ``Name-Realm`` key we can write: not empty, no ``|``, no control characters."""
    return (
        isinstance(key, str)
        and 0 < len(key) <= MAX_CHARACTER_KEY_CHARS
        and "|" not in key
        and all(ord(char) >= 0x20 and ord(char) != 0x7F for char in key)
        and not any(0xD800 <= ord(char) <= 0xDFFF for char in key)
    )


def _clean_list(items: tuple[str, ...], max_items: int, max_chars: int) -> tuple[str, ...]:
    """Cut each item, drop the ones left blank, keep the first ``max_items``.

    The order is the order to act in, so the first items are the ones that matter. Blank is
    checked after cutting, so the result is the same however many times it is cleaned.
    """
    if not isinstance(items, (tuple, list)):
        raise AdviceInvalid("Expected a list of texts but got a single value.")
    cleaned = [clean_text(item, max_chars) for item in items]
    return tuple([item for item in cleaned if item.strip()][:max_items])


# ---- whole structures --------------------------------------------------------------------


def limit_answer(answer: AdviceAnswer) -> AdviceAnswer:
    """Return the answer with every field cut to its limit.

    A ``question_id`` that is not a real id is dropped (with the question that went with it).
    """
    question_id = answer.question_id
    valid_id = question_id is not None and is_valid_question_id(question_id)
    return AdviceAnswer(
        answered_at=clamp_int(answer.answered_at),
        source=clean_text(answer.source, MAX_SOURCE_CHARS),
        title=clean_text(answer.title, MAX_TITLE_CHARS),
        steps=_clean_list(answer.steps, MAX_STEPS, MAX_STEP_CHARS),
        text=clean_text(answer.text, MAX_TEXT_CHARS),
        warnings=_clean_list(answer.warnings, MAX_WARNINGS, MAX_STEP_CHARS),
        question_id=question_id if valid_id else None,
        question=_clean_optional(answer.question, MAX_QUESTION_CHARS) if valid_id else None,
        asked_at=_clamp_optional(answer.asked_at) if valid_id else None,
    )


def _clean_optional(text: str | None, limit: int) -> str | None:
    return None if text is None else clean_text(text, limit)


def limit_plan(plan: CoachPlan) -> CoachPlan:
    """Return the plan with its goal and steps cut to their limits."""
    return CoachPlan(
        goal=clean_text(plan.goal, MAX_TITLE_CHARS),
        steps=_clean_list(plan.steps, MAX_STEPS, MAX_STEP_CHARS),
        updated_at=clamp_int(plan.updated_at),
    )


def limit_answered_ids(ids: tuple[str, ...]) -> tuple[str, ...]:
    """Keep valid ids once each, newest last, at most ``MAX_ANSWERED_IDS``."""
    unique: list[str] = []
    for question_id in ids:
        if is_valid_question_id(question_id) and question_id not in unique:
            unique.append(question_id)
    return tuple(unique[-MAX_ANSWERED_IDS:])


def limit_character(character: CharacterAdvice) -> CharacterAdvice:
    """Cut one character's advice: keep only the newest answers (stored oldest first)."""
    newest = character.answers[-MAX_ANSWERS_PER_CHARACTER:]
    return CharacterAdvice(
        based_on_save=_clamp_optional(character.based_on_save),
        answers=tuple(limit_answer(answer) for answer in newest),
        plan=None if character.plan is None else limit_plan(character.plan),
        answered_ids=limit_answered_ids(character.answered_ids),
    )


def newest_activity(character: CharacterAdvice) -> int:
    """When the character was last written to (0 if never): used to decide who to drop."""
    times = [answer.answered_at for answer in character.answers]
    if character.plan is not None:
        times.append(character.plan.updated_at)
    return max(times, default=0)


def limit_advice(advice: AdviceFile) -> AdviceFile:
    """Cut the whole file's content to the limits (the file size is checked separately).

    Raises:
        AdviceInvalid: For a bad character key or a value of the wrong type.
    """
    characters: dict[str, CharacterAdvice] = {}
    for key, value in advice.characters.items():
        if not is_valid_character_key(key):
            raise AdviceInvalid(
                "A character name must be 1 to "
                f"{MAX_CHARACTER_KEY_CHARS} characters, without '|' or control characters."
            )
        characters[key] = limit_character(value)
    # Too many characters: drop the ones written to longest ago.
    while len(characters) > MAX_CHARACTERS:
        stalest = min(characters, key=lambda key: newest_activity(characters[key]))
        del characters[stalest]
    return AdviceFile(written_at=clamp_int(advice.written_at), characters=characters)
