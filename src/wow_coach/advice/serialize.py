"""Turn advice into the text of ``Advice.lua``. Security-critical: the game RUNS this file.

Rules that keep it safe:

* The output is one header comment plus exactly one statement, ``CoachLinkAdvice = { ... }``.
* Only tables, double-quoted strings, whole numbers and booleans are ever written. There
  is no way for advice text to become code, because every string is escaped.
* Every ``|`` is doubled to ``||``, so AI text can never make a WoW color code or link.
* After writing, we read the text back with our own parser and compare. If anything
  differs, we refuse rather than hand the game something we did not mean.
"""

from collections.abc import Sequence
from dataclasses import replace

from wow_coach.advice.contract import (
    ADVICE_FORMAT_VERSION,
    ADVICE_GLOBAL,
    MAX_FILE_BYTES,
    AdviceAnswer,
    AdviceFile,
    CharacterAdvice,
    CoachPlan,
)
from wow_coach.advice.limits import AdviceInvalid, limit_advice
from wow_coach.errors import WowCoachError
from wow_coach.lua_table import parse_saved_variables

HEADER = "-- Written by wow-coach. Data only, rewritten each time; don't edit.\n"
_INDENT = "  "

# What we can write. (bool is listed for completeness; the advice has no booleans yet.)
type Data = str | int | bool | list[Data] | dict[str, Data]


class AdviceTooLarge(WowCoachError):  # noqa: N818  (reads better than "...Error")
    """The file would be over the size limit even with only one answer left in it."""


class AdviceNotRepeatable(WowCoachError):  # noqa: N818
    """Reading the written text back did not give what we meant to write (a bug)."""


# ---- strings -----------------------------------------------------------------


def lua_string(text: str) -> str:
    """Return ``text`` as a double-quoted Lua string literal that is safe to run.

    Backslash, quote and line breaks get the usual escapes. Every other control character
    (and DEL) becomes ``\\ddd`` with three digits, so a digit that follows is never absorbed.
    ``|`` is NOT touched here: the data builders below double it before it gets here.
    """
    return '"' + "".join(_escape_char(char) for char in text) + '"'


def _escape_char(char: str) -> str:
    if char == "\\":
        return "\\\\"
    if char == '"':
        return '\\"'
    if char == "\n":
        return "\\n"
    if char == "\r":
        return "\\r"
    if ord(char) < 0x20 or ord(char) == 0x7F:
        return f"\\{ord(char):03d}"
    return char


# ---- advice -> plain data ------------------------------------------------------
# We first build plain nested data, then write it as text, then parse the text and
# compare with the data. Display strings in the data already have their "|" doubled, because
# that is what the parser will see in the file. Character keys and question ids are checked
# in ``limits`` to have no "|" at all, so they are written as they are.


def _pipes(text: str) -> str:
    return text.replace("|", "||")


def _answer_data(answer: AdviceAnswer) -> dict[str, Data]:
    """One answer, in the key order of the design doc; empty optional fields are left out."""
    data: dict[str, Data] = {"answeredAt": answer.answered_at}
    if answer.source:
        data["source"] = _pipes(answer.source)
    data["title"] = _pipes(answer.title)
    if answer.steps:
        data["steps"] = [_pipes(step) for step in answer.steps]
    if answer.text:
        data["text"] = _pipes(answer.text)
    if answer.warnings:
        data["warnings"] = [_pipes(warning) for warning in answer.warnings]
    if answer.question_id is not None:
        data["questionId"] = answer.question_id
    if answer.question is not None:
        data["question"] = _pipes(answer.question)
    if answer.asked_at is not None:
        data["askedAt"] = answer.asked_at
    return data


def _plan_data(plan: CoachPlan) -> dict[str, Data]:
    data: dict[str, Data] = {"goal": _pipes(plan.goal)}
    if plan.steps:
        data["steps"] = [_pipes(step) for step in plan.steps]
    data["updatedAt"] = plan.updated_at
    return data


def _character_data(character: CharacterAdvice) -> dict[str, Data]:
    data: dict[str, Data] = {}
    if character.based_on_save is not None:
        data["basedOnSave"] = character.based_on_save
    if character.answers:
        data["answers"] = [_answer_data(answer) for answer in character.answers]
    if character.plan is not None:
        data["plan"] = _plan_data(character.plan)
    if character.answered_ids:
        data["answeredIds"] = list(character.answered_ids)
    return data


def advice_data(advice: AdviceFile) -> dict[str, Data]:
    """The whole file as plain nested data (what ``CoachLinkAdvice`` should contain)."""
    characters: dict[str, Data] = {
        key: _character_data(value) for key, value in sorted(advice.characters.items())
    }
    return {
        "formatVersion": ADVICE_FORMAT_VERSION,
        "writtenAt": advice.written_at,
        "characters": characters,
    }


# ---- plain data -> Lua text ------------------------------------------------------


def _render(value: Data, depth: int) -> str:
    """Write one value. Tables go over several lines, indented by ``depth``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return lua_string(value)
    if isinstance(value, list):
        return _render_table([(None, item) for item in value], depth)
    if isinstance(value, dict):
        return _render_table(list(value.items()), depth)
    raise AdviceInvalid(f"Can't write a value of type {type(value).__name__}.")


def _render_table(entries: Sequence[tuple[str | None, Data]], depth: int) -> str:
    if not entries:
        return "{}"
    inner = _INDENT * (depth + 1)
    lines = ["{"]
    for key, item in entries:
        prefix = "" if key is None else f"[{lua_string(key)}] = "
        lines.append(f"{inner}{prefix}{_render(item, depth + 1)},")
    lines.append(_INDENT * depth + "}")
    return "\n".join(lines)


# ---- public ---------------------------------------------------------------------


def _render_file(data: dict[str, Data]) -> str:
    return f"{HEADER}{ADVICE_GLOBAL} = {_render(data, 0)}\n"


def _drop_oldest_answer(advice: AdviceFile) -> AdviceFile | None:
    """Remove the answer written longest ago, across all characters (None if none left).

    The question id stays in ``answered_ids``, so that question does not look open again.
    """
    oldest: tuple[int, str] | None = None
    for key, character in advice.characters.items():
        if character.answers and (oldest is None or character.answers[0].answered_at < oldest[0]):
            oldest = (character.answers[0].answered_at, key)
    if oldest is None:
        return None
    character = advice.characters[oldest[1]]
    shorter = replace(character, answers=character.answers[1:])
    return replace(advice, characters={**advice.characters, oldest[1]: shorter})


def advice_to_lua(advice: AdviceFile) -> str:
    """Return the full text of ``Advice.lua`` for ``advice``.

    The advice is first cut to the contract's limits. If the file is still too big, the
    oldest answers (of any character) are dropped until it fits.

    Raises:
        AdviceInvalid: For a bad character key or a value of the wrong type.
        AdviceTooLarge: If even one answer would not fit in ``MAX_FILE_BYTES`` bytes.
        AdviceNotRepeatable: If reading the text back does not give the same data.
    """
    limited = limit_advice(advice)
    text = _render_file(advice_data(limited))
    while len(text.encode("utf-8")) > MAX_FILE_BYTES and _answer_count(limited) > 1:
        shorter = _drop_oldest_answer(limited)
        if shorter is None:
            break
        limited = shorter
        text = _render_file(advice_data(limited))
    size = len(text.encode("utf-8"))
    if size > MAX_FILE_BYTES:
        raise AdviceTooLarge(
            f"The Coach panel file would be {size} bytes even with a single answer, "
            f"more than the {MAX_FILE_BYTES} allowed."
        )
    _check_round_trip(text, advice_data(limited))
    return text


def _answer_count(advice: AdviceFile) -> int:
    return sum(len(character.answers) for character in advice.characters.values())


def _check_round_trip(text: str, data: dict[str, Data]) -> None:
    """Parse our own output and make sure it is exactly the data we meant to write."""
    try:
        parsed = parse_saved_variables(text)
    except WowCoachError as error:
        raise AdviceNotRepeatable(f"The advice text could not be read back: {error}") from error
    if parsed != {ADVICE_GLOBAL: data}:
        raise AdviceNotRepeatable("The advice text read back differently from what was meant.")
