"""Tests for where wow-coach keeps its own files."""

from pathlib import Path

from wow_coach.datafolder import data_folder


def test_the_data_dir_variable_wins_on_every_system(tmp_path: Path) -> None:
    environ = {"WOW_COACH_DATA_DIR": str(tmp_path / "mine"), "XDG_DATA_HOME": "/elsewhere"}
    for platform in ("linux", "darwin", "win32"):
        assert data_folder(environ=environ, platform=platform, home=tmp_path) == tmp_path / "mine"


def test_without_the_variable_each_system_has_its_usual_place(tmp_path: Path) -> None:
    home = tmp_path
    assert data_folder(environ={}, platform="linux", home=home) == home / ".local/share/wow-coach"
    mac = data_folder(environ={}, platform="darwin", home=home)
    assert mac == home / "Library/Application Support/wow-coach"
    win = data_folder(environ={"LOCALAPPDATA": str(home / "L")}, platform="win32", home=home)
    assert win == home / "L" / "wow-coach"


def test_a_blank_variable_is_ignored(tmp_path: Path) -> None:
    linux = data_folder(environ={"WOW_COACH_DATA_DIR": "  "}, platform="linux", home=tmp_path)
    assert linux == tmp_path / ".local/share/wow-coach"
