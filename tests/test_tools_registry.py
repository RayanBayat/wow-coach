"""Tests for the coach tool registry, including a parity check against the MCP server."""

import asyncio
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from test_server import DATA

from wow_coach.server import build_server
from wow_coach.tools import MAX_OUTPUT_CHARACTERS, CoachTool, build_coach_tools
from wow_coach.web import Fetch

NOW = 10_000.0
FIXTURES = Path(__file__).parent / "fixtures" / "wiki"
KEY = "Testchar-Testrealm"

# Tools the MCP server has and the registry leaves out on purpose (see tools/registry.py).
LEFT_OUT = {"list_characters", "questions_from_game", "send_advice_to_game"}


@pytest.fixture
def wow_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "game" / "WTF" / "Account" / "ACC" / "SavedVariables"
    folder.mkdir(parents=True)
    (folder / "HeroBridge.lua").write_text(DATA, encoding="utf-8")
    return tmp_path / "game"


@pytest.fixture
def environ(tmp_path: Path) -> dict[str, str]:
    return {"WOW_COACH_NOTES_FILE": str(tmp_path / "data" / "coach-notes.md")}


def forbidden_fetch(_url: str, _params: Mapping[str, str]) -> str:
    raise AssertionError("this test must not use the network")


def tools_by_name(
    wow_dir: Path,
    environ: dict[str, str],
    fetch: Fetch = forbidden_fetch,
    clean: Callable[[str], str] | None = None,
) -> dict[str, CoachTool]:
    tools = build_coach_tools(
        wow_dir, KEY, environ=environ, now=lambda: NOW, clean=clean, fetch=fetch
    )
    return {tool.name: tool for tool in tools}


def test_the_registry_has_the_expected_tools(wow_dir: Path, environ: dict[str, str]) -> None:
    tools = tools_by_name(wow_dir, environ)
    assert sorted(tools) == [
        "character_status",
        "find_quest",
        "progress_summary",
        "read_coach_notes",
        "read_wiki_page",
        "recent_history",
        "save_coach_notes",
        "save_player_notes",
        "search_wiki",
    ]
    assert {name: t.kind for name, t in tools.items()} == {
        "character_status": "read",
        "recent_history": "read",
        "progress_summary": "read",
        "read_coach_notes": "read",
        "save_coach_notes": "write",
        "save_player_notes": "write",
        "search_wiki": "web",
        "read_wiki_page": "web",
        "find_quest": "web",
    }


def test_reading_tools_give_the_same_text_as_the_mcp_helpers(
    wow_dir: Path, environ: dict[str, str]
) -> None:
    tools = tools_by_name(wow_dir, environ)
    assert "Tirisfal Glades" in tools["character_status"].run({})
    assert tools["recent_history"].run({"limit": 20}) == "- 16 min ago: Reached level 7"
    assert tools["recent_history"].run({}) == "- 16 min ago: Reached level 7"  # default limit
    assert "level" in tools["progress_summary"].run({"days": 7}).lower()


def test_a_missing_game_folder_is_a_sentence(tmp_path: Path, environ: dict[str, str]) -> None:
    tools = tools_by_name(tmp_path / "nope", environ)
    assert "HeroBridge" in tools["character_status"].run({})


def test_notes_round_trip_and_the_old_version_is_kept(
    wow_dir: Path, environ: dict[str, str], tmp_path: Path
) -> None:
    tools = tools_by_name(wow_dir, environ)
    assert "no journal" in tools["read_coach_notes"].run({}).lower()
    assert "Saved" in tools["save_coach_notes"].run({"text": "Goal: level 10"})
    assert "Saved" in tools["save_coach_notes"].run({"text": "Goal: level 20"})
    assert "Goal: level 20" in tools["read_coach_notes"].run({})
    history = tmp_path / "data" / "characters" / ".history"
    assert [p.read_text(encoding="utf-8") for p in history.iterdir()] == ["Goal: level 10"]
    assert "Saved" in tools["save_player_notes"].run({"text": "Likes short answers"})
    assert "Likes short answers" in tools["read_coach_notes"].run({})


def test_a_bad_save_is_a_sentence_and_changes_nothing(
    wow_dir: Path, environ: dict[str, str], tmp_path: Path
) -> None:
    tools = tools_by_name(wow_dir, environ)
    tools["save_coach_notes"].run({"text": "keep"})
    assert "100 KB" in tools["save_coach_notes"].run({"text": "x" * 200_000})
    assert "required" in tools["save_coach_notes"].run({})
    assert "must be text" in tools["save_coach_notes"].run({"text": 5})
    journal = tmp_path / "data" / "characters" / f"{KEY}.md"
    assert journal.read_text(encoding="utf-8") == "keep"


def test_the_journal_is_always_the_tools_own_character(
    wow_dir: Path, environ: dict[str, str]
) -> None:
    tools = tools_by_name(wow_dir, environ)
    assert "no argument called 'character'" in tools["read_coach_notes"].run({"character": "Old"})


def test_every_output_goes_through_clean(wow_dir: Path, environ: dict[str, str]) -> None:
    tools = tools_by_name(wow_dir, environ, clean=lambda text: text.replace("Tirisfal", "XXXX"))
    out = tools["character_status"].run({})
    assert "XXXX Glades" in out and "Tirisfal" not in out


def test_every_output_is_size_capped(wow_dir: Path, environ: dict[str, str]) -> None:
    tools = tools_by_name(wow_dir, environ)
    tools["save_coach_notes"].run({"text": "z" * 90_000})
    out = tools["read_coach_notes"].run({})
    assert len(out) < MAX_OUTPUT_CHARACTERS + 200 and "Cut here" in out


def test_wiki_tools_use_the_given_fetch(wow_dir: Path, environ: dict[str, str]) -> None:
    search = (FIXTURES / "search_abigail.json").read_text(encoding="utf-8")
    page = (FIXTURES / "parse_Abigail_Shiel.json").read_text(encoding="utf-8")
    quest = (FIXTURES / "search_quest_365.json").read_text(encoding="utf-8")
    asked: list[Mapping[str, str]] = []

    def fetch(_url: str, params: Mapping[str, str]) -> str:
        asked.append(params)
        if params["action"] == "parse":
            return page
        return quest if "365" in params.get("srsearch", "") else search

    tools = tools_by_name(wow_dir, environ, fetch=fetch)
    assert "1. Abigail Shiel" in tools["search_wiki"].run({"query": "Abigail Shiel"})
    assert "Coarse Thread | 10c" in tools["read_wiki_page"].run(
        {"title": "Abigail Shiel", "section": "Sells"}
    )
    assert "Fields of Grief (Classic)" in tools["find_quest"].run({"quest_id": 365})
    assert asked  # and the test above never reached the network


def test_wiki_limits_are_clamped(wow_dir: Path, environ: dict[str, str]) -> None:
    search = (FIXTURES / "search_abigail.json").read_text(encoding="utf-8")
    seen: list[Mapping[str, str]] = []

    def fetch(_url: str, params: Mapping[str, str]) -> str:
        seen.append(params)
        return search

    tools = tools_by_name(wow_dir, environ, fetch=fetch)
    tools["search_wiki"].run({"query": "q" * 1000, "limit": 500})
    assert seen[0]["srlimit"] == "10"
    assert len(seen[0]["srsearch"]) == 200


def test_descriptions_are_short_plain_sentences(wow_dir: Path, environ: dict[str, str]) -> None:
    tools = tools_by_name(wow_dir, environ)
    assert (
        tools["search_wiki"].describe({"query": "Hides for the Forsaken"})
        == 'Searched the Warcraft Wiki for "Hides for the Forsaken"'
    )
    assert (
        tools["read_wiki_page"].describe({"title": "Abigail Shiel", "section": "Sells"})
        == 'Read the Warcraft Wiki page "Abigail Shiel", section "Sells"'
    )
    assert tools["read_wiki_page"].describe({"title": "Camping 101"}) == (
        'Read the Warcraft Wiki page "Camping 101"'
    )
    assert tools["find_quest"].describe({"quest_id": 365}) == (
        "Looked up quest 365 on the Warcraft Wiki"
    )
    assert tools["read_coach_notes"].describe({}) == "Read your character journal"
    assert tools["save_coach_notes"].describe({"text": "x"}) == "Saved your character journal"
    assert tools["save_player_notes"].describe({"text": "x"}) == "Saved your player notes"
    assert tools["character_status"].describe({}) == "Read your character status"


def test_a_long_or_messy_query_is_shortened_in_the_description(
    wow_dir: Path, environ: dict[str, str]
) -> None:
    tools = tools_by_name(wow_dir, environ)
    text = tools["search_wiki"].describe({"query": "a\nb " + "x" * 500})
    assert "\n" not in text and len(text) < 140


def test_describing_a_bad_call_does_not_raise(wow_dir: Path, environ: dict[str, str]) -> None:
    tools = tools_by_name(wow_dir, environ)
    for tool in tools.values():
        assert tool.describe({"nonsense": object()})


# ---- parity with the MCP server --------------------------------------------------------


def _base_type(definition: Mapping[str, object]) -> object:
    """The type of an MCP property, ignoring ``null`` alternatives."""
    if "type" in definition:
        return definition["type"]
    options = definition.get("anyOf")
    kinds = (
        [o.get("type") for o in options if isinstance(o, dict)] if isinstance(options, list) else []
    )
    return next(kind for kind in kinds if kind != "null")


def test_registry_tools_match_the_mcp_servers_tools(wow_dir: Path, environ: dict[str, str]) -> None:
    mcp = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}
    mine = tools_by_name(wow_dir, environ)
    # Same names (apart from the ones left out on purpose) ...
    assert set(mine) == set(mcp) - LEFT_OUT
    for name, tool in mine.items():
        mcp_schema = mcp[name].input_schema
        mcp_properties = dict(mcp_schema.get("properties", {}))
        # ... and the same arguments. 'character' is the one difference: the registry's
        # tools are built for a single character.
        mcp_properties.pop("character", None)
        mine_properties = tool.spec.parameters["properties"]
        assert isinstance(mine_properties, dict)
        assert set(mine_properties) == set(mcp_properties), name
        assert set(tool.spec.parameters["required"]) == set(mcp_schema.get("required", [])), name  # type: ignore[call-overload]
        for argument, definition in mcp_properties.items():
            assert mine_properties[argument]["type"] == _base_type(definition), (name, argument)
            if definition.get("default") is not None:
                assert mine_properties[argument]["default"] == definition["default"], (
                    name,
                    argument,
                )
