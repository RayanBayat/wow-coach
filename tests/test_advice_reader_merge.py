"""Tests for reading Advice.lua tolerantly and for merging answers."""

from pathlib import Path

from wow_coach.advice.contract import (
    MAX_ANSWERS_PER_CHARACTER,
    AdviceAnswer,
    AdviceFile,
    CharacterAdvice,
    CoachPlan,
)
from wow_coach.advice.merge import add_answer, set_plan
from wow_coach.advice.reader import parse_advice_text, read_advice_file
from wow_coach.advice.serialize import advice_to_lua

KEY = "Testchar-Testrealm"
HEAD = 'HeroBridgeAdvice = {\n["formatVersion"] = 1,\n["writtenAt"] = 9,\n'


def answer(n: int, **changes: object) -> AdviceAnswer:
    fields: dict[str, object] = {"answered_at": n, "source": "S", "title": f"t{n}"}
    fields.update(changes)
    return AdviceAnswer(**fields)  # type: ignore[arg-type]


# ---- reader -------------------------------------------------------------------------


def test_missing_file_is_none(tmp_path: Path) -> None:
    assert read_advice_file(tmp_path / "nope.lua") is None


def test_damaged_files_are_none(tmp_path: Path) -> None:
    for content in ("HeroBridgeAdvice = {", "not lua at all (((", "", "Other = {}"):
        path = tmp_path / "a.lua"
        path.write_text(content, encoding="utf-8")
        assert read_advice_file(path) is None


def test_binary_garbage_and_directories_are_none(tmp_path: Path) -> None:
    path = tmp_path / "a.lua"
    path.write_bytes(b"\xff\xfe\x00\x80")
    assert read_advice_file(path) is None
    assert read_advice_file(tmp_path) is None


def test_deeply_nested_garbage_is_none() -> None:
    assert parse_advice_text("HeroBridgeAdvice = " + "{" * 5000 + "}" * 5000) is None


def test_unknown_format_version_is_none() -> None:
    assert parse_advice_text('HeroBridgeAdvice = { ["formatVersion"] = 99 }') is None


def test_damaged_entries_are_skipped() -> None:
    text = (
        HEAD + '["characters"] = { ["A-R"] = { ["answers"] = {\n'
        '{ ["answeredAt"] = 1, ["title"] = "ok" },\n'
        '{ ["answeredAt"] = "bad", ["title"] = "x" },\n'
        '{ ["title"] = "no time" },\n'
        '"just a string",\n'
        '{ ["answeredAt"] = 2, ["title"] = "also ok", ["steps"] = 5 },\n'
        '} }, ["B-R"] = "junk" } }'
    )
    advice = parse_advice_text(text)
    assert advice is not None
    assert list(advice.characters) == ["A-R"]
    assert [a.title for a in advice.characters["A-R"].answers] == ["ok", "also ok"]
    assert advice.characters["A-R"].answers[1].steps == ()


def test_pipes_are_undone() -> None:
    text = (
        HEAD + '["characters"] = { ["A-R"] = { ["answers"] = '
        '{ { ["answeredAt"] = 1, ["title"] = "a||b" } } } } }'
    )
    advice = parse_advice_text(text)
    assert advice is not None
    assert advice.characters["A-R"].answers[0].title == "a|b"


def test_file_round_trip_on_disk(tmp_path: Path) -> None:
    advice = AdviceFile(2, {KEY: CharacterAdvice(1, (answer(1),), CoachPlan("g", ("s",), 3))})
    path = tmp_path / "Advice.lua"
    path.write_text(advice_to_lua(advice), encoding="utf-8")
    assert read_advice_file(path) == advice


# ---- merge --------------------------------------------------------------------------


def test_add_answer_to_empty_file() -> None:
    result = add_answer(AdviceFile(0), KEY, answer(5), based_on_save=4, now=10)
    assert result.written_at == 10
    assert result.characters[KEY].based_on_save == 4
    assert result.characters[KEY].answers == (answer(5),)


def test_add_answer_is_pure_and_keeps_other_characters() -> None:
    start = AdviceFile(1, {"Other-R": CharacterAdvice(1, (answer(1),))})
    result = add_answer(start, KEY, answer(2), based_on_save=None, now=3)
    assert "Other-R" in result.characters
    assert KEY not in start.characters


def test_only_newest_answers_survive() -> None:
    advice = AdviceFile(0)
    for n in range(MAX_ANSWERS_PER_CHARACTER + 4):
        advice = add_answer(advice, KEY, answer(n), based_on_save=None, now=n)
    kept = advice.characters[KEY].answers
    assert len(kept) == MAX_ANSWERS_PER_CHARACTER
    assert kept[-1].answered_at == MAX_ANSWERS_PER_CHARACTER + 3


def test_same_question_is_answered_once() -> None:
    advice = add_answer(AdviceFile(0), KEY, answer(1, question_id="q"), based_on_save=1, now=1)
    advice = add_answer(advice, KEY, answer(2, question_id="q"), based_on_save=None, now=2)
    assert [a.answered_at for a in advice.characters[KEY].answers] == [2]
    assert advice.characters[KEY].based_on_save == 1


def test_set_plan_keeps_answers() -> None:
    advice = add_answer(AdviceFile(0), KEY, answer(1), based_on_save=1, now=1)
    plan = CoachPlan("Level 20", ("a",), 9)
    result = set_plan(advice, KEY, plan, based_on_save=7, now=9)
    assert result.characters[KEY].plan == plan
    assert result.characters[KEY].answers == (answer(1),)
    assert result.characters[KEY].based_on_save == 7
