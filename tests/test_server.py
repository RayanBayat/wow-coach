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
    answer_progress_summary,
    answer_read_notes,
    answer_recent_history,
    answer_save_notes,
    build_server,
    pick_character,
)

NOW = 10_000.0

DATA = """
HeroBridgeDB = {
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
["race"] = "Undead",
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
["progress"] = {
{
["time"] = 9700,
["level"] = 7,
["xp"] = 100,
["xpMax"] = 1000,
["money"] = 500,
["zone"] = "Tirisfal Glades",
["subZone"] = "Brill",
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
    (folder / "HeroBridge.lua").write_text(DATA, encoding="utf-8")
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
    assert "HeroBridge addon" in answer_character_status(tmp_path, None, NOW)


def test_broken_file_is_friendly(tmp_path: Path) -> None:
    folder = tmp_path / "WTF" / "Account" / "A" / "SavedVariables"
    folder.mkdir(parents=True)
    (folder / "HeroBridge.lua").write_text("HeroBridgeDB = {", encoding="utf-8")
    assert "line 1" in answer_character_status(tmp_path, None, NOW)


def test_list_characters_newest_first_with_journal_state(wow_dir: Path, tmp_path: Path) -> None:
    env = {"WOW_COACH_NOTES_FILE": str(tmp_path / "notes" / "coach-notes.md")}
    lines = answer_list_characters(wow_dir, NOW, env).splitlines()
    assert lines[0] == (
        "- Testchar-Testrealm: level 7 Undead Mage, Tirisfal Glades, "
        "last played 5 min ago, no journal yet"
    )
    assert lines[1].startswith("- Old-Realm: level 20 Priest, Elwynn Forest, last played")


def test_list_characters_shows_the_goal_from_the_journal(wow_dir: Path, tmp_path: Path) -> None:
    env = {"WOW_COACH_NOTES_FILE": str(tmp_path / "notes" / "coach-notes.md")}
    journals = tmp_path / "notes" / "characters"
    journals.mkdir(parents=True)
    (journals / "Testchar-Testrealm.md").write_text("## Goals\n- Level 20\n", encoding="utf-8")
    (journals / "Old-Realm.md").write_text("## Choices\n- Holy\n", encoding="utf-8")
    lines = answer_list_characters(wow_dir, NOW, env).splitlines()
    assert lines[0].endswith("last played 5 min ago, goal: Level 20")
    assert lines[1].endswith("journal has no goal yet")


def test_progress_summary(wow_dir: Path) -> None:
    text = answer_progress_summary(wow_dir, "testchar", 7, NOW)
    assert "**Last played:** 5 min ago, level 7 in Brill, Tirisfal Glades." in text
    assert "No progress recorded" in answer_progress_summary(wow_dir, "old", 7, NOW)
    assert "No character matches" in answer_progress_summary(wow_dir, "nobody", 7, NOW)


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
        "find_quest",
        "list_characters",
        "progress_summary",
        "questions_from_game",
        "read_coach_notes",
        "read_wiki_page",
        "recent_history",
        "save_coach_notes",
        "save_player_notes",
        "search_wiki",
        "send_advice_to_game",
    ]
    assert server.instructions is not None
    assert "character_status" in server.instructions
    assert "questions_from_game" in server.instructions
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


def notes_server(tmp_path: Path, wow_dir: Path) -> MCPServer:
    env = {"WOW_COACH_NOTES_FILE": str(tmp_path / "data" / "coach-notes.md")}
    return build_server(wow_dir_flag=wow_dir, environ=env)


def test_read_notes_before_anything_is_saved(tmp_path: Path, wow_dir: Path) -> None:
    text = call_tool(notes_server(tmp_path, wow_dir), "read_coach_notes", {})
    assert "# Player notes (shared by all characters)" in text
    assert "no player notes yet" in text.lower()
    assert "# Character journal: Testchar-Testrealm" in text
    assert "no journal for Testchar-Testrealm yet" in text


def test_journal_and_player_notes_are_kept_apart(tmp_path: Path, wow_dir: Path) -> None:
    server = notes_server(tmp_path, wow_dir)
    assert "journal" in call_tool(server, "save_coach_notes", {"text": "## Goals\n- Level 10"})
    saved = call_tool(server, "save_player_notes", {"text": "Wants click steps"})
    assert "player notes" in saved
    assert (tmp_path / "data" / "coach-notes.md").read_text("utf-8") == "Wants click steps"
    journal = tmp_path / "data" / "characters" / "Testchar-Testrealm.md"
    assert journal.read_text("utf-8") == "## Goals\n- Level 10"
    text = call_tool(server, "read_coach_notes", {})
    assert text.index("Wants click steps") < text.index("- Level 10")


def test_each_character_has_its_own_journal(tmp_path: Path, wow_dir: Path) -> None:
    server = notes_server(tmp_path, wow_dir)
    call_tool(server, "save_coach_notes", {"text": "mage notes"})
    call_tool(server, "save_coach_notes", {"text": "priest notes", "character": "old"})
    assert "mage notes" in call_tool(server, "read_coach_notes", {})
    other = call_tool(server, "read_coach_notes", {"character": "OLD-realm"})
    assert "priest notes" in other
    assert "mage notes" not in other
    assert "Old-Realm" in call_tool(server, "list_characters", {})


def test_notes_for_an_unknown_character_explain_instead_of_guessing(
    tmp_path: Path, wow_dir: Path
) -> None:
    server = notes_server(tmp_path, wow_dir)
    assert "No character matches" in call_tool(
        server, "save_coach_notes", {"text": "x", "character": "Nobody"}
    )
    assert not (tmp_path / "data" / "characters").exists()
    text = call_tool(server, "read_coach_notes", {"character": "Nobody"})
    assert "# Player notes" in text
    assert "No character matches" in text


def test_notes_without_a_game_folder_still_show_the_player_notes(tmp_path: Path) -> None:
    env = {"WOW_COACH_NOTES_FILE": str(tmp_path / "coach-notes.md")}
    server = build_server(wow_dir_flag=tmp_path / "nope", environ=env)
    call_tool(server, "save_player_notes", {"text": "Solo player"})
    text = call_tool(server, "read_coach_notes", {})
    assert "Solo player" in text
    assert "--wow-dir" in text


def test_progress_summary_tool(tmp_path: Path, wow_dir: Path) -> None:
    text = call_tool(notes_server(tmp_path, wow_dir), "progress_summary", {"days": 3})
    assert "**Last 3 days:**" in text


def test_answer_save_notes_reports_too_large_as_a_message(tmp_path: Path) -> None:
    assert "100 KB" in answer_save_notes(tmp_path / "n.md", "x" * 200_000, "journal")


def test_answer_notes_report_os_errors(tmp_path: Path) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("x", encoding="utf-8")
    # A folder cannot be created under a regular file, so saving fails with an OSError.
    assert "Could not save the journal" in answer_save_notes(
        blocked / "sub" / "n.md", "hi", "journal"
    )
    # A folder where the file should be cannot be read as text.
    folder_as_file = tmp_path / "dir.md"
    folder_as_file.mkdir()
    assert "no player notes yet" in answer_read_notes(folder_as_file, None, "why").lower()


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


def test_find_quest_tool_uses_the_injected_fetch() -> None:
    fixtures = Path(__file__).parent / "fixtures" / "wiki"
    body = (fixtures / "search_quest_365.json").read_text(encoding="utf-8")
    server = build_server(fetch=lambda _url, _params: body)
    text = call_tool(server, "find_quest", {"quest_id": 365})
    assert "Fields of Grief (Classic)" in text


def test_find_quest_tool_is_a_read_only_web_lookup() -> None:
    tools = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}
    annotations = tools["find_quest"].annotations
    assert annotations is not None
    assert annotations.read_only_hint is True
    assert annotations.open_world_hint is True
    assert "quest ID" in (tools["find_quest"].description or "")


def test_wiki_tool_descriptions_say_what_they_are_good_for() -> None:
    tools = {tool.name: tool.description or "" for tool in asyncio.run(build_server().list_tools())}
    assert "vendor" in tools["read_wiki_page"]
    assert "Forever" in tools["read_wiki_page"]
    assert "search_wiki" in tools["read_wiki_page"]


def panel_game(tmp_path: Path) -> Path:
    """A game folder with a save holding one question asked in the Coach panel."""
    folder = tmp_path / "WTF" / "Account" / "ACC" / "SavedVariables"
    folder.mkdir(parents=True)
    question = (
        '["questions"] = {\n{\n["id"] = "9600-1",\n'
        '["text"] = "Where is Brill?",\n["askedAt"] = 9600,\n},\n},\n'
    )
    data = DATA.replace(
        '["Testchar-Testrealm"] = {\n', '["Testchar-Testrealm"] = {\n' + question, 1
    )
    (folder / "HeroBridge.lua").write_text(data, encoding="utf-8")
    (tmp_path / "Interface" / "AddOns").mkdir(parents=True)
    return tmp_path


def test_questions_from_game_lists_the_open_question(tmp_path: Path) -> None:
    server = build_server(wow_dir_flag=panel_game(tmp_path), environ={})
    text = call_tool(server, "questions_from_game", {"character": "Testchar"})
    assert "id 9600-1" in text
    assert "Where is Brill?" in text


def test_send_advice_to_game_answers_the_question(tmp_path: Path) -> None:
    game = panel_game(tmp_path)
    server = build_server(wow_dir_flag=game, environ={})
    reply = call_tool(
        server,
        "send_advice_to_game",
        {
            "character": "Testchar",
            "title": "Brill",
            "steps": ["Follow the road east from Deathknell."],
            "question_id": "9600-1",
        },
    )
    assert "/reload" in reply
    advice = game / "Interface" / "AddOns" / "HeroBridge_Advice" / "Advice.lua"
    written = advice.read_text(encoding="utf-8")
    assert "Follow the road east from Deathknell." in written
    assert "Where is Brill?" in written  # the answer carries its question
    assert '["basedOnSave"] = 9700' in written
    assert "no open questions" in call_tool(server, "questions_from_game", {})


def test_send_advice_to_game_for_an_unknown_character_explains(tmp_path: Path) -> None:
    server = build_server(wow_dir_flag=panel_game(tmp_path), environ={})
    reply = call_tool(
        server, "send_advice_to_game", {"character": "Nobody", "title": "x", "steps": []}
    )
    assert "Nobody" in reply
    assert not (tmp_path / "Interface" / "AddOns" / "HeroBridge_Advice").exists()


def test_send_advice_to_game_writes_but_destroys_nothing() -> None:
    tools = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}
    annotations = tools["send_advice_to_game"].annotations
    assert annotations is not None
    assert annotations.read_only_hint is False
    assert annotations.destructive_hint is False
    assert tools["questions_from_game"].annotations is not None
    assert tools["questions_from_game"].annotations.read_only_hint is True
