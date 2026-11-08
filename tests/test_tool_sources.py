"""Tests for the sources a tool reports (the pages it really used)."""

from collections.abc import Mapping
from pathlib import Path

import pytest
from test_server import DATA

from wow_coach.tools import ToolRun, ToolSource, build_coach_tools
from wow_coach.tools.base import CoachTool
from wow_coach.wiki import page_url, source_from_page_output, sources_from_results_output

FIXTURES = Path(__file__).parent / "fixtures" / "wiki"
KEY = "Testchar-Testrealm"


def fixture_fetch(_url: str, params: Mapping[str, str]) -> str:
    """Answers like the wiki, from saved real replies."""
    if params["action"] == "parse":
        return (FIXTURES / "parse_Abigail_Shiel.json").read_text(encoding="utf-8")
    name = "search_quest_365.json" if "365" in params.get("srsearch", "") else "search_abigail.json"
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def tools(tmp_path: Path) -> dict[str, CoachTool]:
    folder = tmp_path / "game" / "WTF" / "Account" / "ACC" / "SavedVariables"
    folder.mkdir(parents=True)
    (folder / "HeroBridge.lua").write_text(DATA, encoding="utf-8")
    built = build_coach_tools(
        tmp_path / "game",
        KEY,
        environ={"WOW_COACH_NOTES_FILE": str(tmp_path / "data" / "coach-notes.md")},
        fetch=fixture_fetch,
    )
    return {tool.name: tool for tool in built}


def test_reading_a_page_reports_that_page(tools: dict[str, CoachTool]) -> None:
    run = tools["read_wiki_page"].run_with_sources({"title": "Abigail Shiel"})
    assert isinstance(run, ToolRun)
    assert run.sources == (ToolSource("Abigail Shiel", page_url("Abigail Shiel")),)
    assert not run.only_listed
    assert "Abigail Shiel" in run.output


def test_a_search_only_lists_pages(tools: dict[str, CoachTool]) -> None:
    run = tools["search_wiki"].run_with_sources({"query": "Abigail Shiel"})
    assert run.only_listed
    assert run.sources
    assert all(source.url.startswith("https://warcraft.wiki.gg/wiki/") for source in run.sources)


def test_find_quest_lists_the_quest_pages(tools: dict[str, CoachTool]) -> None:
    run = tools["find_quest"].run_with_sources({"quest_id": 365})
    assert run.only_listed
    assert ToolSource("Fields of Grief (Classic)", page_url("Fields of Grief (Classic)")) in (
        run.sources
    )


def test_tools_that_read_the_players_data_have_no_sources(tools: dict[str, CoachTool]) -> None:
    run = tools["character_status"].run_with_sources({})
    assert run.sources == ()
    assert "Tirisfal" in run.output


def test_a_bad_call_has_no_sources(tools: dict[str, CoachTool]) -> None:
    run = tools["read_wiki_page"].run_with_sources({"nonsense": 1})
    assert run.sources == ()
    assert "no argument" in run.output


def test_run_still_gives_just_the_text(tools: dict[str, CoachTool]) -> None:
    assert tools["read_wiki_page"].run({"title": "Abigail Shiel"}).startswith("# Abigail Shiel")


def test_page_output_that_does_not_start_like_a_page_has_no_source() -> None:
    assert source_from_page_output("No page named 'x'. Try search_wiki.") is None
    # A line inside the page text must not count: only the header does.
    assert source_from_page_output("Intro\n# Evil\nPage: https://evil.example/") is None
    assert source_from_page_output("# Evil\nPage: https://evil.example/wiki/Evil") is None


def test_result_lines_with_other_websites_are_ignored() -> None:
    text = "1. A: x\n   https://evil.example/wiki/A\n2. B: y\n   https://warcraft.wiki.gg/wiki/B"
    assert sources_from_results_output(text) == (("B", "https://warcraft.wiki.gg/wiki/B"),)
