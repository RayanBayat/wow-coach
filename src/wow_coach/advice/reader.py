"""Read ``Advice.lua`` back into ``AdviceFile`` objects, forgiving about damage.

wow-coach reads the file to add to it (a new answer must not erase the old ones). The
file might be missing, half edited by hand or from a newer version, so every problem
becomes "no file" (None) or a skipped entry, never a crash.
"""

from pathlib import Path

from wow_coach.advice.contract import (
    ADVICE_FORMAT_VERSION,
    ADVICE_GLOBAL,
    MAX_FILE_BYTES,
    AdviceAnswer,
    AdviceFile,
    CharacterAdvice,
    CoachPlan,
)
from wow_coach.advice.limits import is_valid_character_key, is_valid_question_id
from wow_coach.advice.safefile import read_plain_text
from wow_coach.errors import WowCoachError
from wow_coach.lua_table import LuaValue, parse_saved_variables


def read_advice_file(path: Path) -> AdviceFile | None:
    """Read the advice file at ``path``. Returns None if it is missing or unusable."""
    text = read_plain_text(path, MAX_FILE_BYTES * 2)
    return None if text is None else parse_advice_text(text)


def parse_advice_text(text: str) -> AdviceFile | None:
    """Turn the text of an advice file into an ``AdviceFile`` (None if unusable)."""
    try:
        variables = parse_saved_variables(text)
    except WowCoachError, RecursionError:
        return None
    table = variables.get(ADVICE_GLOBAL)
    if not isinstance(table, dict) or table.get("formatVersion") != ADVICE_FORMAT_VERSION:
        return None
    written_at = _read_int(table.get("writtenAt"))
    characters_table = table.get("characters")
    characters: dict[str, CharacterAdvice] = {}
    if isinstance(characters_table, dict):
        for key, value in characters_table.items():
            if not isinstance(key, str) or not is_valid_character_key(key):
                continue
            character = _read_character(value)
            if character is not None:
                characters[key] = character
    return AdviceFile(written_at=written_at or 0, characters=characters)


# ---- small helpers: each one accepts anything and returns a clean value or None ------


def _unpipe(text: str) -> str:
    """Undo the doubling of ``|`` that the writer does."""
    return text.replace("||", "|")


def _read_int(value: LuaValue) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _read_str(value: LuaValue) -> str | None:
    return _unpipe(value) if isinstance(value, str) else None


def _read_strings(value: LuaValue) -> tuple[str, ...]:
    """A Lua list of strings; anything else (including an empty ``{}``) gives nothing."""
    if not isinstance(value, list):
        return ()
    return tuple(_unpipe(item) for item in value if isinstance(item, str))


def _read_raw_strings(value: LuaValue) -> tuple[str, ...]:
    """Like ``_read_strings`` but for identifiers, which are never pipe-doubled."""
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


# ---- entries ---------------------------------------------------------------------


def _read_character(value: LuaValue) -> CharacterAdvice | None:
    if not isinstance(value, dict):
        return None
    answers_table = value.get("answers")
    answers = (
        tuple(answer for item in answers_table if (answer := _read_answer(item)) is not None)
        if isinstance(answers_table, list)
        else ()
    )
    return CharacterAdvice(
        based_on_save=_read_int(value.get("basedOnSave")),
        answers=answers,
        plan=_read_plan(value.get("plan")),
        answered_ids=tuple(
            i for i in _read_raw_strings(value.get("answeredIds")) if is_valid_question_id(i)
        ),
    )


def _read_question_id(value: LuaValue) -> str | None:
    return value if isinstance(value, str) and is_valid_question_id(value) else None


def _read_answer(value: LuaValue) -> AdviceAnswer | None:
    """One answer, or None when it lacks the two required fields."""
    if not isinstance(value, dict):
        return None
    answered_at = _read_int(value.get("answeredAt"))
    title = _read_str(value.get("title"))
    if answered_at is None or title is None:
        return None
    return AdviceAnswer(
        answered_at=answered_at,
        source=_read_str(value.get("source")) or "",
        title=title,
        steps=_read_strings(value.get("steps")),
        text=_read_str(value.get("text")) or "",
        warnings=_read_strings(value.get("warnings")),
        question_id=_read_question_id(value.get("questionId")),
        question=_read_str(value.get("question")),
        asked_at=_read_int(value.get("askedAt")),
    )


def _read_plan(value: LuaValue) -> CoachPlan | None:
    if not isinstance(value, dict):
        return None
    goal = _read_str(value.get("goal"))
    updated_at = _read_int(value.get("updatedAt"))
    if goal is None or updated_at is None:
        return None
    return CoachPlan(goal=goal, steps=_read_strings(value.get("steps")), updated_at=updated_at)
