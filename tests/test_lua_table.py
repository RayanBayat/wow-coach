"""Tests for the Lua SavedVariables parser."""

import pytest

from wow_coach.errors import LuaParseError, WowCoachError
from wow_coach.lua_table import LuaValue, parse_saved_variables


def parse_one(value_text: str) -> LuaValue:
    """Parse ``X = <value_text>`` and return the value of X."""
    return parse_saved_variables(f"X = {value_text}\n")["X"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("42", 42),
        ("-7", -7),
        ("0", 0),
        ("3.5", 3.5),
        ("-0.25", -0.25),
        ("1e3", 1000.0),
        ("true", True),
        ("false", False),
        ("nil", None),
        ('"hello"', "hello"),
        ('""', ""),
        ('"say \\"hi\\""', 'say "hi"'),
        ('"a\\\\b"', "a\\b"),
        ('"line1\\nline2"', "line1\nline2"),
        ('"tab\\there"', "tab\there"),
        ('"cr\\rx"', "cr\rx"),
        ('"\\065\\66"', "AB"),
    ],
)
def test_scalar_values(text: str, expected: LuaValue) -> None:
    assert parse_one(text) == expected


def test_bool_is_not_confused_with_int() -> None:
    assert parse_one("true") is True


def test_empty_table_is_empty_dict() -> None:
    assert parse_one("{}") == {}


def test_positional_table_is_list() -> None:
    assert parse_one('{ 1, "two", 3.5, }') == [1, "two", 3.5]


def test_keyed_table_is_dict() -> None:
    assert parse_one('{ ["a"] = 1, ["b"] = "x" }') == {"a": 1, "b": "x"}


def test_mixed_table_puts_positions_under_int_keys() -> None:
    assert parse_one('{ "first", ["k"] = 5, "second" }') == {1: "first", 2: "second", "k": 5}


def test_nil_holes_become_none() -> None:
    assert parse_one("{\nnil,\n2,\nnil,\n}") == [None, 2, None]


def test_zero_numeric_key() -> None:
    assert parse_one("{\n[0] = 5,\n[2] = 6,\n}") == {0: 5, 2: 6}


def test_nested_tables() -> None:
    text = '{ ["quests"] = { { ["title"] = "A", ["done"] = false }, { ["title"] = "B" } } }'
    assert parse_one(text) == {"quests": [{"title": "A", "done": False}, {"title": "B"}]}


def test_trailing_comment_after_list_items() -> None:
    text = '{\n"a", -- [1]\n"b", -- [2]\n}'
    assert parse_one(text) == ["a", "b"]


def test_comment_inside_string_is_kept() -> None:
    assert parse_one('"a -- b"') == "a -- b"


def test_multiple_assignments() -> None:
    assert parse_saved_variables("A = 1\nB = 2\n") == {"A": 1, "B": 2}


def test_empty_file() -> None:
    assert parse_saved_variables("") == {}


def test_crlf_no_indentation_like_wow_forever() -> None:
    text = (
        "\r\nCoachLinkDB = {\r\n"
        '["formatVersion"] = 1,\r\n'
        '["characters"] = {\r\n'
        '["Testchar-Testrealm"] = {\r\n'
        '["history"] = {\r\n'
        "nil, -- [1]\r\n"
        "{\r\n"
        '["text"] = "Died\\nagain",\r\n'
        "}, -- [2]\r\n"
        "},\r\n"
        "},\r\n"
        "},\r\n"
        "}\r\n"
    )
    db = parse_saved_variables(text)["CoachLinkDB"]
    assert db == {
        "formatVersion": 1,
        "characters": {"Testchar-Testrealm": {"history": [None, {"text": "Died\nagain"}]}},
    }


@pytest.mark.parametrize(
    ("text", "line", "expected"),
    [
        ("X = {\n1,\n@\n}", 3, "a value"),
        ('X = "abc', 1, "closing quote"),
        ("X = {\n1,\n2", 3, "'}'"),
        ("\n\nX 5", 3, "'='"),
        ("X = \n", 2, "a value"),
        ('X = "bad \\q"', 1, "escape"),
        ("X = 1.2.3", 1, "a number"),
    ],
)
def test_errors_report_line_and_expectation(text: str, line: int, expected: str) -> None:
    with pytest.raises(LuaParseError) as info:
        parse_saved_variables(text)
    assert f"line {line}" in str(info.value)
    assert expected in str(info.value)


def test_parse_error_is_a_project_error() -> None:
    assert issubclass(LuaParseError, WowCoachError)


@pytest.mark.parametrize("escape", ["\\²", "\\①", "\\256", "\\999"])
def test_a_bad_number_escape_is_a_parse_error_not_a_crash(escape: str) -> None:
    # Only ASCII digits count, and Lua's \ddd is one byte (at most 255). A damaged file
    # must give LuaParseError, which callers handle, never ValueError.
    with pytest.raises(LuaParseError):
        parse_saved_variables(f'X = "a{escape}b"')
