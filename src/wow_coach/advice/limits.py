"""Cut advice down to the limits in ``contract`` before it is written.

The addon can't hold unlimited text, so wow-coach shortens what is too long instead of
failing: text is cut on whole characters, and only the newest answers are kept.
"""

from dataclasses import replace

from wow_coach.advice.contract import (
    MAX_ANSWERS_PER_CHARACTER,
    MAX_QUESTION_CHARS,
    MAX_SOURCE_CHARS,
    MAX_STEP_CHARS,
    MAX_STEPS,
    MAX_TEXT_CHARS,
    MAX_TITLE_CHARS,
    MAX_WARNINGS,
    AdviceAnswer,
    AdviceFile,
    CharacterAdvice,
    CoachPlan,
)

MAX_ID_CHARS = 40  # a question id looks like "1794100000-1"
MAX_KEY_CHARS = 100  # a "Name-Realm" key


def clean_text(text: str, limit: int) -> str:
    """Make ``text`` safe and short: no lone surrogates, at most ``limit`` characters.

    A lone surrogate can't be written as UTF-8, so it becomes the replacement character.
    Python slices strings by whole characters, so a letter is never cut in half.
    """
    fixed = "".join("�" if 0xD800 <= ord(char) <= 0xDFFF else char for char in text)
    return fixed[:limit]


def _clean_list(items: tuple[str, ...], max_items: int, max_chars: int) -> tuple[str, ...]:
    """Drop blank items, keep the first ``max_items`` (the order is the order to act in)."""
    cleaned = [clean_text(item, max_chars) for item in items if item.strip()]
    return tuple(cleaned[:max_items])


def _clean_optional(text: str | None, limit: int) -> str | None:
    return None if text is None else clean_text(text, limit)


def limit_answer(answer: AdviceAnswer) -> AdviceAnswer:
    """Return the answer with every field cut to its limit."""
    return replace(
        answer,
        source=clean_text(answer.source, MAX_SOURCE_CHARS),
        title=clean_text(answer.title, MAX_TITLE_CHARS),
        steps=_clean_list(answer.steps, MAX_STEPS, MAX_STEP_CHARS),
        text=clean_text(answer.text, MAX_TEXT_CHARS),
        warnings=_clean_list(answer.warnings, MAX_WARNINGS, MAX_STEP_CHARS),
        question_id=_clean_optional(answer.question_id, MAX_ID_CHARS),
        question=_clean_optional(answer.question, MAX_QUESTION_CHARS),
    )


def limit_plan(plan: CoachPlan) -> CoachPlan:
    """Return the plan with its goal and steps cut to their limits."""
    return replace(
        plan,
        goal=clean_text(plan.goal, MAX_TITLE_CHARS),
        steps=_clean_list(plan.steps, MAX_STEPS, MAX_STEP_CHARS),
    )


def limit_character(character: CharacterAdvice) -> CharacterAdvice:
    """Cut one character's advice: keep only the newest answers (they are stored oldest first)."""
    newest = character.answers[-MAX_ANSWERS_PER_CHARACTER:]
    return replace(
        character,
        answers=tuple(limit_answer(answer) for answer in newest),
        plan=None if character.plan is None else limit_plan(character.plan),
    )


def limit_advice(advice: AdviceFile) -> AdviceFile:
    """Cut the whole file's content to the limits (the file size is checked separately)."""
    characters = {
        clean_text(key, MAX_KEY_CHARS): limit_character(value)
        for key, value in advice.characters.items()
    }
    return replace(advice, characters=characters)
