"""Tests for finding and loading the HeroBridge data file."""

import os
from pathlib import Path

import pytest

from wow_coach.errors import CoachDataMissing, LuaParseError, UnsupportedFormat
from wow_coach.savedvars import find_saved_variables, load_characters

GOOD_FILE = """
HeroBridgeDB = {
["formatVersion"] = 1,
["characters"] = {
["Testchar-Testrealm"] = {
["snapshot"] = {
["name"] = "Testchar",
["savedAt"] = 100,
},
["history"] = {
{
["text"] = "Reached level 2",
},
},
["progress"] = {
{
["time"] = 100,
["level"] = 2,
},
},
["questions"] = {
{
["id"] = "100-1",
["text"] = "What next?",
["askedAt"] = 100,
},
},
},
["Bare-Realm"] = {
},
},
}
"""


def make_saved_vars(wow_dir: Path, account: str, text: str = GOOD_FILE) -> Path:
    folder = wow_dir / "WTF" / "Account" / account / "SavedVariables"
    folder.mkdir(parents=True)
    path = folder / "HeroBridge.lua"
    path.write_text(text, encoding="utf-8")
    return path


def test_find_returns_the_only_file(tmp_path: Path) -> None:
    path = make_saved_vars(tmp_path, "ACC1")
    assert find_saved_variables(tmp_path) == path


def test_find_returns_most_recently_modified(tmp_path: Path) -> None:
    old = make_saved_vars(tmp_path, "OLD")
    new = make_saved_vars(tmp_path, "NEW")
    os.utime(old, (1_000, 1_000))
    os.utime(new, (2_000, 2_000))
    assert find_saved_variables(tmp_path) == new


def test_find_missing_gives_friendly_message(tmp_path: Path) -> None:
    with pytest.raises(CoachDataMissing, match=r"HeroBridge addon.*restart WoW.*/coach"):
        find_saved_variables(tmp_path)


def test_find_nonexistent_dir_is_also_missing(tmp_path: Path) -> None:
    with pytest.raises(CoachDataMissing):
        find_saved_variables(tmp_path / "nope")


def test_load_characters(tmp_path: Path) -> None:
    path = make_saved_vars(tmp_path, "A")
    characters = load_characters(path)
    assert set(characters) == {"Testchar-Testrealm", "Bare-Realm"}
    testchar = characters["Testchar-Testrealm"]
    assert testchar.key == "Testchar-Testrealm"
    assert testchar.snapshot["name"] == "Testchar"
    assert testchar.history == [{"text": "Reached level 2"}]


def test_progress_points_are_read(tmp_path: Path) -> None:
    testchar = load_characters(make_saved_vars(tmp_path, "A"))["Testchar-Testrealm"]
    assert testchar.progress == [{"time": 100, "level": 2}]


def test_questions_from_the_coach_panel_are_read(tmp_path: Path) -> None:
    testchar = load_characters(make_saved_vars(tmp_path, "A"))["Testchar-Testrealm"]
    assert testchar.questions == [{"id": "100-1", "text": "What next?", "askedAt": 100}]


def test_character_without_pieces_gets_empty_defaults(tmp_path: Path) -> None:
    bare = load_characters(make_saved_vars(tmp_path, "A"))["Bare-Realm"]
    assert bare.snapshot == {}
    assert bare.history == []
    assert bare.progress == []
    assert bare.questions == []


def test_no_characters_table_gives_empty_dict(tmp_path: Path) -> None:
    path = make_saved_vars(tmp_path, "A", 'HeroBridgeDB = {\n["formatVersion"] = 1,\n}\n')
    assert load_characters(path) == {}


def test_unknown_format_version(tmp_path: Path) -> None:
    path = make_saved_vars(tmp_path, "A", 'HeroBridgeDB = {\n["formatVersion"] = 99,\n}\n')
    with pytest.raises(UnsupportedFormat, match="99"):
        load_characters(path)


def test_missing_database_variable(tmp_path: Path) -> None:
    path = make_saved_vars(tmp_path, "A", "Other = 1\n")
    with pytest.raises(UnsupportedFormat, match="HeroBridgeDB"):
        load_characters(path)


def test_broken_lua_raises_parse_error(tmp_path: Path) -> None:
    path = make_saved_vars(tmp_path, "A", "HeroBridgeDB = {")
    with pytest.raises(LuaParseError):
        load_characters(path)
