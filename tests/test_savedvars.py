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


# --- Players who still have the old CoachLink addon (called HeroBridge since 0.11.0) ---


def character_file(variable: str, saved_at: int, name: str = "Testchar-Testrealm") -> str:
    """A tiny save file with one character, so tests can compare which one wins."""
    return (
        f"{variable} = {{\n"
        '["formatVersion"] = 1,\n'
        '["characters"] = {\n'
        f'["{name}"] = {{\n'
        f'["snapshot"] = {{\n["savedAt"] = {saved_at},\n}},\n'
        "},\n},\n}\n"
    )


def make_file(wow_dir: Path, account: str, file_name: str, text: str) -> Path:
    folder = wow_dir / "WTF" / "Account" / account / "SavedVariables"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / file_name
    path.write_text(text, encoding="utf-8")
    return path


def test_old_coachlink_file_is_still_read_when_it_is_the_only_one(tmp_path: Path) -> None:
    old = make_file(tmp_path, "A", "CoachLink.lua", character_file("CoachLinkDB", 50))
    assert find_saved_variables(tmp_path) == old
    assert load_characters(old)["Testchar-Testrealm"].snapshot["savedAt"] == 50


def test_both_files_use_the_newer_save_for_each_character(tmp_path: Path) -> None:
    old = make_file(
        tmp_path,
        "A",
        "CoachLink.lua",
        'CoachLinkDB = {\n["formatVersion"] = 1,\n["characters"] = {\n'
        '["Both-R"] = {\n["snapshot"] = {\n["savedAt"] = 500,\n},\n},\n'
        '["OnlyOld-R"] = {\n["snapshot"] = {\n["savedAt"] = 7,\n},\n},\n},\n}\n',
    )
    new = make_file(
        tmp_path,
        "A",
        "HeroBridge.lua",
        'HeroBridgeDB = {\n["formatVersion"] = 1,\n["characters"] = {\n'
        '["Both-R"] = {\n["snapshot"] = {\n["savedAt"] = 100,\n},\n},\n'
        '["OnlyNew-R"] = {\n["snapshot"] = {\n["savedAt"] = 9,\n},\n},\n},\n}\n',
    )
    for path in (old, new):  # it must not matter which file the caller starts from
        characters = load_characters(path)
        assert set(characters) == {"Both-R", "OnlyOld-R", "OnlyNew-R"}
        assert characters["Both-R"].snapshot["savedAt"] == 500


def test_a_tie_prefers_the_herobridge_file(tmp_path: Path) -> None:
    old = make_file(tmp_path, "A", "CoachLink.lua", character_file("CoachLinkDB", 5))
    new = make_file(tmp_path, "A", "HeroBridge.lua", character_file("HeroBridgeDB", 5))
    new.write_text(new.read_text().replace('["savedAt"] = 5,', '["savedAt"] = 5,\n["name"] = "New",'))
    for path in (old, new):
        assert load_characters(path)["Testchar-Testrealm"].snapshot["name"] == "New"


def test_find_picks_the_newest_across_both_names(tmp_path: Path) -> None:
    old = make_file(tmp_path, "A", "CoachLink.lua", character_file("CoachLinkDB", 1))
    new = make_file(tmp_path, "A", "HeroBridge.lua", character_file("HeroBridgeDB", 2))
    os.utime(old, (3_000, 3_000))
    os.utime(new, (2_000, 2_000))
    assert find_saved_variables(tmp_path) == old


def test_a_broken_old_file_does_not_hide_the_new_one(tmp_path: Path) -> None:
    make_file(tmp_path, "A", "CoachLink.lua", "CoachLinkDB = {")
    new = make_file(tmp_path, "A", "HeroBridge.lua", character_file("HeroBridgeDB", 5))
    assert load_characters(new)["Testchar-Testrealm"].snapshot["savedAt"] == 5
