"""Tests for the server's text-producing functions (no MCP transport needed)."""

import asyncio
from collections.abc import Mapping
from pathlib import Path

import pytest
from mcp.server import MCPServer
from mcp.types import CallToolResult

from wow_coach.savedvars import Character
from wow_coach.server import (
    answer_character_status,
    answer_list_characters,
    answer_read_notes,
    answer_recent_history,
    answer_save_notes,
    build_server,
    pick_character,
)

NOW = 10_000.0

DATA = """
CoachLinkDB = {
["formatVersion"] = 1,
["characters"] = {
["Old-Realm"] = {
["snapshot"] = {
["name"] = "Old",
["class"] = "Priest",
["level"] = 20,
["zone"] = "Elwynn Forest",
["savedAt"] = 1000,
},
},
["Testchar-Testrealm"] = {
["snapshot"] = {
["name"] = "Testchar",
["class"] = "Mage",
["level"] = 7,
["zone"] = "Tirisfal Glades",
["savedAt"] = 9700,
},
["history"] = {
{
["time"] = 9000,
["text"] = "Reached level 7",
},
},
},
},
}
"""


@pytest.fixture
def wow_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "WTF" / "Account" / "ACC" / "SavedVariables"
    folder.mkdir(parents=True)
    (folder / "CoachLink.lua").write_text(DATA, encoding="utf-8")
    return tmp_path


def make(key: str, saved_at: float) -> Character:
    return Character(key=key, snapshot={"savedAt": saved_at}, history=[])


def test_pick_defaults_to_newest() -> None:
    chars = {"A-R": make("A-R", 1), "B-R": make("B-R", 2)}
    assert pick_character(chars, None) == chars["B-R"]


@pytest.mark.parametrize("wanted", ["a", "A", "a-r", "A-R", " a "])
def test_pick_matches_case_insensitively(wanted: str) -> None:
    chars = {"A-R": make("A-R", 1), "B-R": make("B-R", 2)}
    assert pick_character(chars, wanted) == chars["A-R"]


def test_pick_unknown_and_empty() -> None:
    assert pick_character({"A-R": make("A-R", 1)}, "zzz") is None
    assert pick_character({}, None) is None


def test_missing_file_is_friendly(tmp_path: Path) -> None:
    assert "CoachLink addon" in answer_character_status(tmp_path, None, NOW)


def test_broken_file_is_friendly(tmp_path: Path) -> None:
    folder = tmp_path / "WTF" / "Account" / "A" / "SavedVariables"
    folder.mkdir(parents=True)
    (folder / "CoachLink.lua").write_text("CoachLinkDB = {", encoding="utf-8")
    assert "line 1" in answer_character_status(tmp_path, None, NOW)


def test_list_characters(wow_dir: Path) -> None:
    lines = answer_list_characters(wow_dir, NOW).splitlines()
    assert lines[0] == "- Testchar-Testrealm: level 7 Mage, Tirisfal Glades, saved 5 min ago"
    assert lines[1].startswith("- Old-Realm: level 20 Priest")


def test_status_defaults_to_newest(wow_dir: Path) -> None:
    assert answer_character_status(wow_dir, None, NOW).startswith("# Testchar")


def test_status_by_name(wow_dir: Path) -> None:
    assert answer_character_status(wow_dir, "old", NOW).startswith("# Old")


def test_unknown_character_lists_known(wow_dir: Path) -> None:
    text = answer_character_status(wow_dir, "Nobody", NOW)
    assert "Testchar-Testrealm" in text
    assert "Old-Realm" in text


def test_history(wow_dir: Path) -> None:
    assert answer_recent_history(wow_dir, "testchar", 20, NOW) == "- 16 min ago: Reached level 7"


def test_history_limit_zero_still_returns_one(wow_dir: Path) -> None:
    assert "Reached level 7" in answer_recent_history(wow_dir, None, 0, NOW)


def test_server_registers_all_tools_and_instructions() -> None:
    server = build_server()
    tools = asyncio.run(server.list_tools())
    assert sorted(tool.name for tool in tools) == [
        "character_status",
        "list_characters",
        "read_coach_notes",
        "read_wiki_page",
        "recent_history",
        "save_coach_notes",
        "search_wiki",
    ]
    assert server.instructions is not None
    assert "character_status" in server.instructions
    assert "save_coach_notes" in server.instructions
    assert "read_wiki_page" in server.instructions


def test_every_tool_tells_the_ai_when_to_use_it() -> None:
    tools = asyncio.run(build_server().list_tools())
    assert all(tool.description and "Use" in tool.description for tool in tools)


def call_tool(server: MCPServer, name: str, arguments: dict[str, object]) -> str:
    """Call a tool through the MCP layer and return its text."""
    result = asyncio.run(server.call_tool(name, arguments))
    assert isinstance(result, CallToolResult)
    return "".join(getattr(block, "text", "") for block in result.content)


def test_tool_without_a_game_folder_explains_the_fix(tmp_path: Path) -> None:
    server = build_server(wow_dir_flag=tmp_path / "nope", environ={})
    text = call_tool(server, "character_status", {})
    assert "--wow-dir" in text
    assert "nope" in text


def test_tool_reads_the_game_folder_from_the_flag(wow_dir: Path) -> None:
    server = build_server(wow_dir_flag=wow_dir, environ={})
    assert call_tool(server, "character_status", {}).startswith("# Testchar")


def test_notes_tools_round_trip(tmp_path: Path) -> None:
    env = {"WOW_COACH_NOTES_FILE": str(tmp_path / "notes.md")}
    server = build_server(environ=env)
    assert "no coach notes yet" in call_tool(server, "read_coach_notes", {}).lower()
    saved = call_tool(server, "save_coach_notes", {"text": "Goal: level 10"})
    assert "notes.md" in saved
    assert call_tool(server, "read_coach_notes", {}) == "Goal: level 10"


def test_answer_save_notes_reports_too_large_as_a_message(tmp_path: Path) -> None:
    assert "100 KB" in answer_save_notes(tmp_path / "n.md", "x" * 200_000)


def test_answer_notes_report_os_errors(tmp_path: Path) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("x", encoding="utf-8")
    # A folder cannot be created under a regular file, so saving fails with an OSError.
    assert "Could not save" in answer_save_notes(blocked / "sub" / "n.md", "hi")
    # A folder where the file should be cannot be read as text.
    folder_as_file = tmp_path / "dir.md"
    folder_as_file.mkdir()
    assert "no coach notes yet" in answer_read_notes(folder_as_file).lower()


def test_wiki_tools_use_the_injected_fetch_and_never_the_network() -> None:
    fixtures = Path(__file__).parent / "fixtures" / "wiki"
    search_body = (fixtures / "search_abigail.json").read_text(encoding="utf-8")
    page_body = (fixtures / "parse_Abigail_Shiel.json").read_text(encoding="utf-8")

    def fake_fetch(_url: str, params: Mapping[str, str]) -> str:
        return search_body if params["action"] == "query" else page_body

    server = build_server(fetch=fake_fetch)
    found = call_tool(server, "search_wiki", {"query": "Abigail Shiel"})
    assert "1. Abigail Shiel" in found
    page = call_tool(server, "read_wiki_page", {"title": "Abigail Shiel", "section": "Sells"})
    assert "Coarse Thread | 10c" in page


def test_wiki_tool_descriptions_say_what_they_are_good_for() -> None:
    tools = {tool.name: tool.description or "" for tool in asyncio.run(build_server().list_tools())}
    assert "vendor" in tools["read_wiki_page"]
    assert "Forever" in tools["read_wiki_page"]
    assert "search_wiki" in tools["read_wiki_page"]
