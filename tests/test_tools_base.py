"""Tests for CoachTool and the checking of an AI's tool arguments."""

import pytest

from wow_coach.ai.base import ToolSpec
from wow_coach.errors import WowCoachError
from wow_coach.tools.base import CoachTool, cap_text, check_arguments

SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "maxLength": 10},
        "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
        "section": {"type": "string"},
    },
    "required": ["query"],
}


def test_good_arguments_pass_with_defaults_filled_in() -> None:
    assert check_arguments(SCHEMA, {"query": "abc"}) == {"query": "abc", "limit": 5}


def test_null_means_not_given() -> None:
    assert check_arguments(SCHEMA, {"query": "abc", "limit": None, "section": None}) == {
        "query": "abc",
        "limit": 5,
    }


def test_numbers_are_clamped_and_text_is_cut() -> None:
    assert check_arguments(SCHEMA, {"query": "x" * 50, "limit": 999}) == {
        "query": "x" * 10,
        "limit": 10,
    }
    assert check_arguments(SCHEMA, {"query": "a", "limit": -4}) == {"query": "a", "limit": 1}


def test_a_whole_float_is_accepted_as_a_number() -> None:
    assert check_arguments(SCHEMA, {"query": "a", "limit": 3.0}) == {"query": "a", "limit": 3}


@pytest.mark.parametrize(
    ("arguments", "words"),
    [
        ({}, "'query' is required"),
        ({"query": None}, "'query' is required"),
        ({"query": 5}, "'query' must be text"),
        ({"query": "a", "limit": "3"}, "'limit' must be a whole number"),
        ({"query": "a", "limit": 2.5}, "'limit' must be a whole number"),
        ({"query": "a", "limit": True}, "'limit' must be a whole number"),
        ({"query": "a", "limit": float("nan")}, "'limit' must be a whole number"),
        ({"query": "a", "colour": "red"}, "no argument called 'colour'"),
    ],
)
def test_bad_arguments_get_a_plain_sentence(arguments: dict[str, object], words: str) -> None:
    result = check_arguments(SCHEMA, arguments)
    assert isinstance(result, str) and words in result


def make_tool(handler_output: str = "ok", *, fail: Exception | None = None) -> CoachTool:
    def handler(arguments: dict[str, object]) -> str:
        if fail is not None:
            raise fail
        return handler_output + str(arguments.get("query", ""))

    return CoachTool(
        spec=ToolSpec("demo", "A demo.", SCHEMA),
        kind="read",
        handler=handler,
        describer=lambda args: f"Demo {args['query']}",
        clean=lambda text: text.replace("secret", "a player"),
    )


def test_run_checks_runs_and_cleans() -> None:
    assert make_tool("secret-").run({"query": "q"}) == "a player-q"


def test_run_returns_the_problem_instead_of_raising() -> None:
    assert "'query' is required" in make_tool().run({})


@pytest.mark.parametrize("error", [WowCoachError("broken"), OSError("disk gone")])
def test_a_failing_handler_becomes_a_sentence(error: Exception) -> None:
    text = make_tool(fail=error).run({"query": "q"})
    assert text.startswith("The demo tool could not finish")


def test_output_is_cut_to_the_size_limit_with_a_note() -> None:
    text = make_tool("y" * 20_000).run({"query": "q"})
    assert len(text) < 12_200
    assert text.startswith("yyyy") and "Cut here" in text


def test_cap_text_leaves_short_text_alone() -> None:
    assert cap_text("short", 100) == "short"


def test_describe_uses_the_arguments_and_never_raises() -> None:
    tool = make_tool()
    assert tool.describe({"query": "q"}) == "Demo q"
    assert tool.describe({}) == "Used the demo tool"  # the describer needs 'query'
    assert tool.describe({"query": 5, "weird": [1]}) == "Demo 5"
