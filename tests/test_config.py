"""Tests for the saved settings (config.json)."""

from pathlib import Path

import pytest

from wow_coach.config import (
    CONFIG_FILE_VARIABLE,
    config_path,
    load_saved_wow_dir,
    save_wow_dir,
)
from wow_coach.errors import ConfigUnreadable


def test_env_variable_picks_the_file(tmp_path: Path) -> None:
    where = tmp_path / "mine.json"
    assert config_path(environ={CONFIG_FILE_VARIABLE: str(where)}) == where


def test_default_file_sits_next_to_the_notes_on_each_system() -> None:
    home = Path("/home/x")
    assert config_path(environ={}, platform="linux", home=home) == (
        home / ".local" / "share" / "wow-coach" / "config.json"
    )
    assert config_path(environ={"XDG_DATA_HOME": "/xdg"}, platform="linux", home=home) == (
        Path("/xdg") / "wow-coach" / "config.json"
    )
    assert config_path(environ={}, platform="darwin", home=home) == (
        home / "Library" / "Application Support" / "wow-coach" / "config.json"
    )
    assert config_path(environ={"LOCALAPPDATA": "/local"}, platform="win32", home=home) == (
        Path("/local") / "wow-coach" / "config.json"
    )


def test_nothing_saved_gives_none(tmp_path: Path) -> None:
    assert load_saved_wow_dir(tmp_path / "config.json") is None


def test_saved_folder_round_trips_and_creates_the_data_folder(tmp_path: Path) -> None:
    where = tmp_path / "new-folder" / "config.json"
    save_wow_dir(where, tmp_path / "game")
    assert load_saved_wow_dir(where) == tmp_path / "game"


def test_saving_keeps_other_settings(tmp_path: Path) -> None:
    where = tmp_path / "config.json"
    where.write_text('{"other": 1}', encoding="utf-8")
    save_wow_dir(where, tmp_path / "game")
    assert '"other": 1' in where.read_text(encoding="utf-8")


@pytest.mark.parametrize("text", ["{not json", "[1, 2]"])
def test_damaged_file_says_to_run_setup_again(tmp_path: Path, text: str) -> None:
    where = tmp_path / "config.json"
    where.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigUnreadable, match="wow-coach setup"):
        load_saved_wow_dir(where)
