"""Find the questions the player asked in the Coach panel that have no answer yet."""

from wow_coach.advice.contract import MAX_QUESTION_CHARS, AdviceFile, Question
from wow_coach.advice.limits import clean_text
from wow_coach.lua_table import LuaValue
from wow_coach.savedvars import Character


def _read_question(entry: LuaValue) -> Question | None:
    """Turn one saved entry into a ``Question``; None when it is damaged."""
    if not isinstance(entry, dict):
        return None
    question_id, text, asked_at = entry.get("id"), entry.get("text"), entry.get("askedAt")
    if not isinstance(question_id, str) or not question_id:
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    if isinstance(asked_at, bool) or not isinstance(asked_at, int):
        return None
    return Question(id=question_id, text=clean_text(text, MAX_QUESTION_CHARS), asked_at=asked_at)


def _answered_ids(character_key: str, advice: AdviceFile | None) -> set[str]:
    if advice is None or character_key not in advice.characters:
        return set()
    answers = advice.characters[character_key].answers
    return {answer.question_id for answer in answers if answer.question_id is not None}


def open_questions(character: Character, advice: AdviceFile | None) -> list[Question]:
    """The character's questions without an answer in ``advice``, oldest first.

    Damaged entries and repeated ids are skipped.
    """
    answered = _answered_ids(character.key, advice)
    seen: set[str] = set()
    found: list[Question] = []
    for entry in character.questions:
        question = _read_question(entry)
        if question is None or question.id in answered or question.id in seen:
            continue
        seen.add(question.id)
        found.append(question)
    return found
