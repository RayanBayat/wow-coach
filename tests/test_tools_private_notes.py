"""Sections about the player's computer never reach the AI through the notes tools."""

from pathlib import Path

import pytest

from wow_coach.tools import CoachTool, build_coach_tools

KEY = "Testchar-Testrealm"
JOURNAL = (
    "# Journal\n\n## Goals\nLevel 20\n\n## This computer\nGame is in /opt/example-games/wow\n\n"
    "## Progress log\n2026-11-08 level 7\n"
)


@pytest.fixture
def setup(tmp_path: Path) -> tuple[dict[str, CoachTool], Path]:
    notes_dir = tmp_path / "data"
    environ = {"WOW_COACH_NOTES_FILE": str(notes_dir / "coach-notes.md")}
    journal = notes_dir / "characters" / f"{KEY}.md"
    journal.parent.mkdir(parents=True)
    journal.write_text(JOURNAL, encoding="utf-8")
    tools = build_coach_tools(
        tmp_path / "game", KEY, environ=environ, hide_private_notes=True, fetch=lambda *_: ""
    )
    return {tool.name: tool for tool in tools}, journal


def test_reading_leaves_out_the_computer_section(setup: tuple[dict[str, CoachTool], Path]) -> None:
    tools, _journal = setup
    text = tools["read_coach_notes"].run({})
    assert "Level 20" in text and "2026-11-08 level 7" in text
    assert "This computer" not in text and "/opt/example-games/wow" not in text


def test_saving_keeps_the_computer_section_on_disk(
    setup: tuple[dict[str, CoachTool], Path],
) -> None:
    tools, journal = setup
    shown = tools["read_coach_notes"].run({})
    assert "Saved" in tools["save_coach_notes"].run({"text": "# Journal\n\n## Goals\nLevel 30\n"})
    saved = journal.read_text(encoding="utf-8")
    assert "Level 30" in saved and "Level 20" not in saved
    assert "## This computer\nGame is in /opt/example-games/wow" in saved
    assert shown  # the AI never needed the section to save


def test_a_section_the_ai_wrote_itself_is_not_doubled(
    setup: tuple[dict[str, CoachTool], Path],
) -> None:
    tools, journal = setup
    tools["save_coach_notes"].run({"text": "## Goals\nx\n\n## This computer\nnew words\n"})
    saved = journal.read_text(encoding="utf-8")
    assert saved.count("## This computer") == 1 and "new words" in saved


def test_without_the_option_the_whole_file_is_read(tmp_path: Path) -> None:
    journal = tmp_path / "data" / "characters" / f"{KEY}.md"
    journal.parent.mkdir(parents=True)
    journal.write_text(JOURNAL, encoding="utf-8")
    environ = {"WOW_COACH_NOTES_FILE": str(tmp_path / "data" / "coach-notes.md")}
    tools = {t.name: t for t in build_coach_tools(tmp_path / "g", KEY, environ=environ)}
    assert "This computer" in tools["read_coach_notes"].run({})
