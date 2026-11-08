"""Property tests: any text and any mix of answers survive writing and reading."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from wow_coach.advice.contract import (
    ADVICE_GLOBAL,
    MAX_FILE_BYTES,
    AdviceAnswer,
    AdviceFile,
    CharacterAdvice,
    CoachPlan,
)
from wow_coach.advice.limits import AdviceInvalid, is_valid_character_key, limit_advice
from wow_coach.advice.reader import parse_advice_text
from wow_coach.advice.serialize import (
    AdviceTooLarge,
    _render_file,
    advice_data,
    advice_to_lua,
)
from wow_coach.lua_table import parse_saved_variables

# Short text of any kind: control characters, quotes, backslashes, pipes, emoji, blanks.
# (Lone surrogates can't be written as UTF-8; the writer replaces them, tested separately.)
short_text = st.text(max_size=120)
blank_text = st.text(alphabet=" \t\n\u00a0", max_size=5)
# Text around the limits (80 title, 300 step, 4000 text): a repeated character.
near_limit_text = st.builds(
    lambda size, char: char * size,
    st.integers(min_value=0, max_value=4100),
    st.sampled_from(["a", "|", "\U0001f600", "\\"]),
)
any_text = short_text | blank_text | near_limit_text
step_text = short_text | blank_text | st.integers(250, 350).map(lambda n: "s" * n)
# Numbers, including negative and enormous ones: they are clamped to a sane range.
numbers = st.integers(min_value=-(10**30), max_value=10**30) | st.integers(0, 2**40)
question_ids = st.none() | st.from_regex(r"[0-9]{1,12}-[0-9]{1,6}", fullmatch=True)
valid_keys = st.from_regex(r"[A-Za-z]{1,12}-[A-Za-z]{1,12}", fullmatch=True)

answers = st.builds(
    AdviceAnswer,
    answered_at=numbers,
    source=short_text,
    title=short_text | blank_text,
    steps=st.lists(step_text, max_size=7).map(tuple),
    text=any_text,
    warnings=st.lists(step_text, max_size=7).map(tuple),
    question_id=question_ids,
    question=st.none() | short_text,
    asked_at=st.none() | numbers,
)
plans = st.none() | st.builds(
    CoachPlan, goal=short_text, steps=st.lists(step_text, max_size=7).map(tuple), updated_at=numbers
)
characters = st.builds(
    CharacterAdvice,
    based_on_save=st.none() | numbers,
    answers=st.lists(answers, max_size=4).map(tuple),
    plan=plans,
    answered_ids=st.lists(question_ids.filter(bool), max_size=45).map(tuple),
)
advice_files = st.builds(
    AdviceFile,
    written_at=numbers,
    characters=st.dictionaries(valid_keys, characters, max_size=2),
)


@settings(max_examples=150, deadline=None)
@given(advice_files)
def test_write_then_read_gives_the_same_advice(advice: AdviceFile) -> None:
    expected = limit_advice(advice)
    text = advice_to_lua(advice)
    assert len(text.encode("utf-8")) <= MAX_FILE_BYTES
    full_size = len(_render_file(advice_data(expected), ADVICE_GLOBAL).encode("utf-8"))
    if full_size <= MAX_FILE_BYTES:
        assert parse_advice_text(text) == expected  # nothing had to be dropped
    else:
        assert parse_advice_text(text) is not None  # oldest answers were dropped to fit


@settings(max_examples=100, deadline=None)
@given(advice_files)
def test_output_is_one_statement_and_stable(advice: AdviceFile) -> None:
    text = advice_to_lua(advice)
    assert list(parse_saved_variables(text)) == ["HeroBridgeAdvice"]
    assert advice_to_lua(advice) == text
    # Writing what we read gives the same file again.
    again = parse_advice_text(text)
    assert again is not None
    assert advice_to_lua(again) == text


@settings(max_examples=100, deadline=None)
@given(any_text)
def test_no_color_code_or_link_can_get_through(text: str) -> None:
    advice = AdviceFile(1, {"A-R": CharacterAdvice(1, (AdviceAnswer(1, "S", "t", text=text),))})
    body = advice_to_lua(advice)
    # After removing every doubled pipe, no single pipe may be left.
    assert "|" not in body.replace("||", "")


@settings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(valid_keys, st.integers(0, 10**6)), min_size=1, max_size=4))
def test_the_size_limit_holds_for_many_big_answers(seeded: list[tuple[str, int]]) -> None:
    big = "\x01" * 4000  # each one becomes 4 bytes in the file
    characters = {
        key: CharacterAdvice(
            1, tuple(AdviceAnswer(seed + n, "S", "t", text=big) for n in range(10))
        )
        for key, seed in seeded
    }
    try:
        text = advice_to_lua(AdviceFile(1, characters))
    except AdviceTooLarge:  # allowed only if one answer alone can't fit; never here
        pytest.fail("a single 4000-character answer must always fit")
    assert len(text.encode("utf-8")) <= MAX_FILE_BYTES


@settings(max_examples=150, deadline=None)
@given(st.text(max_size=140))
def test_hostile_character_keys_are_refused_or_written_safely(key: str) -> None:
    advice = AdviceFile(1, {key: CharacterAdvice(1, (AdviceAnswer(1, "S", "t"),))})
    if is_valid_character_key(key):
        back = parse_advice_text(advice_to_lua(advice))
        assert back is not None and list(back.characters) == [key]
    else:
        with pytest.raises(AdviceInvalid):
            advice_to_lua(advice)
