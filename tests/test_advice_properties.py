"""Property tests: any text and any mix of answers survive writing and reading."""

from hypothesis import given, settings
from hypothesis import strategies as st

from wow_coach.advice.contract import (
    AdviceAnswer,
    AdviceFile,
    CharacterAdvice,
    CoachPlan,
)
from wow_coach.advice.limits import limit_advice
from wow_coach.advice.reader import parse_advice_text
from wow_coach.advice.serialize import advice_to_lua
from wow_coach.lua_table import parse_saved_variables

# Any text at all, including control characters, quotes, backslashes, pipes and emoji.
# (Lone surrogates can't be written as UTF-8; the writer replaces them, tested separately.)
any_text = st.text(max_size=120)
numbers = st.integers(min_value=0, max_value=2**40)
maybe_text = st.none() | any_text
maybe_number = st.none() | numbers

answers = st.builds(
    AdviceAnswer,
    answered_at=numbers,
    source=any_text,
    title=any_text,
    steps=st.lists(any_text, max_size=7).map(tuple),
    text=any_text,
    warnings=st.lists(any_text, max_size=7).map(tuple),
    question_id=maybe_text,
    question=maybe_text,
    asked_at=maybe_number,
)
plans = st.none() | st.builds(
    CoachPlan, goal=any_text, steps=st.lists(any_text, max_size=7).map(tuple), updated_at=numbers
)
characters = st.builds(
    CharacterAdvice,
    based_on_save=maybe_number,
    answers=st.lists(answers, max_size=12).map(tuple),
    plan=plans,
)
advice_files = st.builds(
    AdviceFile,
    written_at=numbers,
    characters=st.dictionaries(st.text(min_size=1, max_size=30), characters, max_size=3),
)


@settings(max_examples=150, deadline=None)
@given(advice_files)
def test_write_then_read_gives_the_same_advice(advice: AdviceFile) -> None:
    expected = limit_advice(advice)
    assert parse_advice_text(advice_to_lua(advice)) == expected


@settings(max_examples=100, deadline=None)
@given(advice_files)
def test_output_is_one_statement_and_stable(advice: AdviceFile) -> None:
    text = advice_to_lua(advice)
    assert list(parse_saved_variables(text)) == ["CoachLinkAdvice"]
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
