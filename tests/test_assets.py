"""Tests for the packaged files and the notes templates taken from the skill."""

import pytest

from wow_coach import assets
from wow_coach.assets import journal_template, notebook_template


def test_player_notes_template() -> None:
    notes = notebook_template()
    assert notes.startswith("# Player notes\n")
    assert notes.endswith("\n")
    assert "## Goals" not in notes  # goals belong to a character, not to the player


def test_journal_template_has_the_sections_the_coach_relies_on() -> None:
    journal = journal_template()
    assert journal.startswith("# Journal: ")
    for heading in ("## Goals", "## Choices", "## Progress log", "## Open advice / next steps"):
        assert heading in journal


def test_templates_work_when_git_checked_the_skill_out_with_windows_line_endings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = assets.read_asset

    def with_crlf(relative_path: str) -> bytes:
        return original(relative_path).replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")

    monkeypatch.setattr(assets, "read_asset", with_crlf)
    assert "\r" not in notebook_template()
    assert "\r" not in journal_template()
