"""Add an answer or a plan to an ``AdviceFile``. Pure functions: they return a new file."""

from dataclasses import replace

from wow_coach.advice.contract import (
    MAX_ANSWERED_IDS,
    MAX_ANSWERS_PER_CHARACTER,
    AdviceAnswer,
    AdviceFile,
    CharacterAdvice,
    CoachPlan,
)


def _with_character(
    advice: AdviceFile, character_key: str, character: CharacterAdvice, now: int
) -> AdviceFile:
    characters = {**advice.characters, character_key: character}
    return replace(advice, written_at=now, characters=characters)


def add_answer(
    advice: AdviceFile,
    character_key: str,
    answer: AdviceAnswer,
    *,
    based_on_save: int | None,
    now: int,
) -> AdviceFile:
    """Return ``advice`` with ``answer`` added as the newest answer of the character.

    * An older answer to the same question is replaced, so a question has one answer.
    * Only the newest ``MAX_ANSWERS_PER_CHARACTER`` answers are kept.
    * The question id is remembered in ``answered_ids`` (newest last, capped), so the question
      does not look open again once its answer is pushed out.
    * ``based_on_save`` replaces the old value unless it is None.
    """
    current = advice.characters.get(character_key, CharacterAdvice(based_on_save=None))
    kept = [
        old
        for old in current.answers
        if answer.question_id is None or old.question_id != answer.question_id
    ]
    answers = tuple([*kept, answer][-MAX_ANSWERS_PER_CHARACTER:])
    updated = replace(
        current,
        answers=answers,
        answered_ids=_remember_id(current.answered_ids, answer.question_id),
        based_on_save=current.based_on_save if based_on_save is None else based_on_save,
    )
    return _with_character(advice, character_key, updated, now)


def set_plan(
    advice: AdviceFile,
    character_key: str,
    plan: CoachPlan,
    *,
    based_on_save: int | None,
    now: int,
) -> AdviceFile:
    """Return ``advice`` with the character's plan replaced by ``plan``."""
    current = advice.characters.get(character_key, CharacterAdvice(based_on_save=None))
    updated = replace(
        current,
        plan=plan,
        based_on_save=current.based_on_save if based_on_save is None else based_on_save,
    )
    return _with_character(advice, character_key, updated, now)


def _remember_id(ids: tuple[str, ...], question_id: str | None) -> tuple[str, ...]:
    """Add ``question_id`` as the newest answered id (once), keeping the newest few."""
    if question_id is None:
        return ids
    others = [old for old in ids if old != question_id]
    return tuple([*others, question_id][-MAX_ANSWERED_IDS:])
