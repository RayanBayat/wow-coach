"""Tests for the coach's notebook (where it lives, reading, saving)."""

from pathlib import Path

import pytest

from wow_coach.errors import NotesTooLarge
from wow_coach.notes import MAX_NOTES_BYTES, notes_path, read_notes, save_notes

HOME = Path("/home/x")


def test_env_variable_wins() -> None:
    path = notes_path(
        environ={"WOW_COACH_NOTES_FILE": "/notes/mine.md"}, platform="linux", home=HOME
    )
    assert path == Path("/notes/mine.md")


def test_linux_default_is_the_xdg_data_folder() -> None:
    path = notes_path(environ={}, platform="linux", home=HOME)
    assert path == HOME / ".local/share/wow-coach/coach-notes.md"


def test_linux_respects_xdg_data_home() -> None:
    path = notes_path(environ={"XDG_DATA_HOME": "/data/xdg"}, platform="linux", home=HOME)
    assert path == Path("/data/xdg/wow-coach/coach-notes.md")


def test_macos_default() -> None:
    path = notes_path(environ={}, platform="darwin", home=Path("/Users/x"))
    assert path == Path("/Users/x/Library/Application Support/wow-coach/coach-notes.md")


def test_windows_uses_localappdata() -> None:
    path = notes_path(
        environ={"LOCALAPPDATA": "C:/Users/x/AppData/Local"}, platform="win32", home=HOME
    )
    assert path == Path("C:/Users/x/AppData/Local/wow-coach/coach-notes.md")


def test_windows_without_localappdata_falls_back_to_home() -> None:
    path = notes_path(environ={}, platform="win32", home=HOME)
    assert path == HOME / "AppData/Local/wow-coach/coach-notes.md"


def test_read_when_no_notes_yet(tmp_path: Path) -> None:
    text = read_notes(tmp_path / "none.md")
    assert "no coach notes yet" in text.lower()
    assert "save_coach_notes" in text


def test_save_then_read_round_trip_creates_folders(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "notes.md"
    confirmation = save_notes(target, "Plan: finish Brill quests. Ünïcode ok.")
    assert str(target) in confirmation
    assert read_notes(target) == "Plan: finish Brill quests. Ünïcode ok."


def test_save_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    save_notes(target, "old")
    save_notes(target, "new")
    assert read_notes(target) == "new"


def test_save_refuses_text_over_the_limit(tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    with pytest.raises(NotesTooLarge, match="100 KB"):
        save_notes(target, "x" * (MAX_NOTES_BYTES + 1))
    assert not target.exists()


def test_limit_counts_bytes_not_characters(tmp_path: Path) -> None:
    with pytest.raises(NotesTooLarge):
        save_notes(tmp_path / "n.md", "é" * (MAX_NOTES_BYTES // 2 + 1))


def test_save_at_exactly_the_limit_works(tmp_path: Path) -> None:
    save_notes(tmp_path / "n.md", "x" * MAX_NOTES_BYTES)
