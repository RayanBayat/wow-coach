"""Tests for the Advice.lua serializer: escaping, limits, size and reading back."""

import pytest

from wow_coach.advice.contract import (
    ADVICE_GLOBAL,
    MAX_ANSWERS_PER_CHARACTER,
    MAX_CHARACTERS,
    MAX_FILE_BYTES,
    MAX_STEP_CHARS,
    MAX_STEPS,
    MAX_TEXT_CHARS,
    MAX_TITLE_CHARS,
    AdviceAnswer,
    AdviceFile,
    CharacterAdvice,
    CoachPlan,
)
from wow_coach.advice.limits import AdviceInvalid
from wow_coach.advice.reader import parse_advice_text
from wow_coach.advice.serialize import (
    AdviceTooLarge,
    _render,
    advice_to_lua,
    lua_string,
)
from wow_coach.errors import WowCoachError
from wow_coach.lua_table import parse_saved_variables

KEY = "Testchar-Testrealm"


def one_answer(**changes: object) -> AdviceAnswer:
    fields: dict[str, object] = {"answered_at": 1794100090, "source": "Coach", "title": "Next"}
    fields.update(changes)
    return AdviceAnswer(**fields)  # type: ignore[arg-type]


def file_with(*answers: AdviceAnswer, plan: CoachPlan | None = None) -> AdviceFile:
    character = CharacterAdvice(based_on_save=1794100050, answers=answers, plan=plan)
    return AdviceFile(written_at=1794100100, characters={KEY: character})


def only_answer(advice: AdviceFile) -> AdviceAnswer:
    """Write the advice, read it back and return the character's first answer."""
    back = parse_advice_text(advice_to_lua(advice))
    assert back is not None
    return back.characters[KEY].answers[0]


def test_normal_round_trip() -> None:
    answer = one_answer(
        steps=("Go to Brill.", "Turn in the quest."),
        text="Longer words.",
        warnings=("Orange quest",),
        question_id="1794100000-1",
        question="What next?",
        asked_at=1794100000,
    )
    plan = CoachPlan(goal="Level 20", steps=("a", "b"), updated_at=5)
    advice = file_with(answer, plan=plan)
    assert parse_advice_text(advice_to_lua(advice)) == advice


def test_output_has_header_and_one_statement() -> None:
    text = advice_to_lua(file_with(one_answer()))
    assert text.startswith("-- Written by wow-coach.")
    assert list(parse_saved_variables(text)) == [ADVICE_GLOBAL]
    assert text.count(f"{ADVICE_GLOBAL} =") == 1


def test_keys_are_camel_case() -> None:
    text = advice_to_lua(file_with(one_answer(question_id="1-1", asked_at=3)))
    for name in ("formatVersion", "writtenAt", "basedOnSave", "answeredAt", "questionId"):
        assert f'["{name}"]' in text


@pytest.mark.parametrize(
    ("raw", "literal"),
    [
        ('say "hi"', r'"say \"hi\""'),
        ("back\\slash", r'"back\\slash"'),
        ("a\nb", r'"a\nb"'),
        ("a\rb", r'"a\rb"'),
        ("a\x00b", r'"a\000b"'),
        ("a\x1fb", r'"a\031b"'),
        ("a\x7fb", r'"a\127b"'),
        ("tab\there", r'"tab\009here"'),
        ("x\x001", r'"x\0001"'),  # a digit after a control character is not absorbed
    ],
)
def test_string_escaping(raw: str, literal: str) -> None:
    assert lua_string(raw) == literal


AWKWARD_TEXTS = [
    '"quoted"',
    "\\",
    "\\n literally",
    "line\nbreak\r\n",
    "\x00\x01\x1f\x7f",
    "|cff|Hitem:1|h",
    "||",
    "|",
    "emoji \U0001f600 \u00e5\u00e4\u00f6 \u4e2d\u6587 \u2028",
    "\x85\x9f",
    "'; os.exit() --",
]


@pytest.mark.parametrize("text", AWKWARD_TEXTS)
def test_awkward_text_round_trips(text: str) -> None:
    advice = file_with(one_answer(title="t" + text, steps=(text,), text=text, warnings=(text,)))
    answer = only_answer(advice)
    assert answer.text == text
    assert answer.steps == (text,)
    assert answer.warnings == (text,)


def test_pipes_are_doubled_in_the_file() -> None:
    text = advice_to_lua(file_with(one_answer(text="|cffff0000hi|r")))
    assert "|cff" not in text.replace("||", "")


def test_text_is_cut_on_whole_characters() -> None:
    emoji = "\U0001f600"
    answer = only_answer(
        file_with(one_answer(title=emoji * 200, text=emoji * (MAX_TEXT_CHARS + 5)))
    )
    assert answer.title == emoji * MAX_TITLE_CHARS
    assert answer.text == emoji * MAX_TEXT_CHARS


def test_steps_are_limited_in_number_and_length() -> None:
    steps = tuple("s" * (MAX_STEP_CHARS + 50) for _ in range(MAX_STEPS + 3))
    answer = only_answer(file_with(one_answer(steps=steps, warnings=steps)))
    assert len(answer.steps) == MAX_STEPS
    assert all(len(step) == MAX_STEP_CHARS for step in answer.steps)
    assert len(answer.warnings) == 5


def test_blank_steps_are_dropped() -> None:
    assert only_answer(file_with(one_answer(steps=("a", "  ", "")))).steps == ("a",)


def test_only_the_newest_answers_are_kept() -> None:
    answers = tuple(one_answer(answered_at=n, title=f"t{n}") for n in range(15))
    back = parse_advice_text(advice_to_lua(file_with(*answers)))
    assert back is not None
    kept = back.characters[KEY].answers
    assert [a.answered_at for a in kept] == list(range(15 - MAX_ANSWERS_PER_CHARACTER, 15))


def test_lone_surrogates_are_replaced() -> None:
    assert only_answer(file_with(one_answer(text="a\ud800b"))).text == "a�b"


def test_a_full_file_drops_the_oldest_answers_across_characters() -> None:
    big = "\x01" * MAX_TEXT_CHARS  # each one becomes 4 bytes
    characters = {
        f"Char{n}-Realm": CharacterAdvice(
            based_on_save=1,
            answers=tuple(one_answer(text=big, answered_at=1000 * n + k) for k in range(10)),
            answered_ids=("1-1",),
        )
        for n in range(6)
    }
    text = advice_to_lua(AdviceFile(written_at=1, characters=characters))
    assert len(text.encode("utf-8")) <= MAX_FILE_BYTES
    back = parse_advice_text(text)
    assert back is not None
    # The newest character is untouched; the oldest answers went first.
    assert len(back.characters["Char5-Realm"].answers) == 10
    assert len(back.characters["Char0-Realm"].answers) < 10
    assert back.characters["Char0-Realm"].answered_ids == ("1-1",)


def test_one_answer_that_cannot_fit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("wow_coach.advice.serialize.MAX_FILE_BYTES", 100)
    with pytest.raises(AdviceTooLarge) as caught:
        advice_to_lua(file_with(one_answer(text="x" * 500)))
    assert isinstance(caught.value, WowCoachError)
    assert "100" in str(caught.value)
    assert "your" not in str(caught.value).lower()  # not worded as the AI's own fault


def test_more_than_the_allowed_characters_drops_the_stalest() -> None:
    characters = {
        f"C{n:02d}-R": CharacterAdvice(1, (one_answer(answered_at=100 + n),)) for n in range(25)
    }
    back = parse_advice_text(advice_to_lua(AdviceFile(1, characters)))
    assert back is not None
    assert len(back.characters) == MAX_CHARACTERS
    assert "C00-R" not in back.characters and "C24-R" in back.characters


@pytest.mark.parametrize("key", ["", "a|b", "a\nb", "x" * 101, "bell\x07"])
def test_bad_character_keys_are_refused(key: str) -> None:
    with pytest.raises(AdviceInvalid):
        advice_to_lua(AdviceFile(1, {key: CharacterAdvice(1)}))


def test_answered_ids_are_written_and_read() -> None:
    character = CharacterAdvice(1, (), None, ("1-1", "2-1"))
    back = parse_advice_text(advice_to_lua(AdviceFile(1, {KEY: character})))
    assert back is not None and back.characters[KEY].answered_ids == ("1-1", "2-1")


def test_invalid_question_ids_are_dropped_not_cut() -> None:
    long_id = "1-" + "9" * 50
    answer = only_answer(file_with(one_answer(question_id=long_id, question="q", asked_at=4)))
    assert (answer.question_id, answer.question, answer.asked_at) == (None, None, None)


def test_numbers_are_clamped() -> None:
    assert only_answer(file_with(one_answer(answered_at=-(10**30)))).answered_at == 0
    assert only_answer(file_with(one_answer(answered_at=10**30))).answered_at == 2**40


def test_blank_steps_after_cutting_are_dropped() -> None:
    assert only_answer(file_with(one_answer(steps=("   ", "ok")))).steps == ("ok",)


def test_wrong_types_are_refused_not_crashed() -> None:
    with pytest.raises(AdviceInvalid):
        advice_to_lua(file_with(one_answer(steps="abc")))
    with pytest.raises(AdviceInvalid):
        advice_to_lua(file_with(one_answer(text=5)))
    with pytest.raises(AdviceInvalid):
        advice_to_lua(file_with(one_answer(answered_at="5")))
    with pytest.raises(AdviceInvalid):
        _render(object(), 0)  # type: ignore[arg-type]


def test_empty_file_is_valid() -> None:
    assert parse_advice_text(advice_to_lua(AdviceFile(written_at=7))) == AdviceFile(written_at=7)


def test_characters_are_written_in_stable_order() -> None:
    forward = {"A-R": CharacterAdvice(None), "B-R": CharacterAdvice(None)}
    backward = {"B-R": CharacterAdvice(None), "A-R": CharacterAdvice(None)}
    text = advice_to_lua(AdviceFile(written_at=1, characters=forward))
    assert text.index('"A-R"') < text.index('"B-R"')
    assert text == advice_to_lua(AdviceFile(written_at=1, characters=backward))
