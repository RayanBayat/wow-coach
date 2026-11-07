"""Tests for finding the game folder (flag, environment variable, auto-detect)."""

from pathlib import Path

import pytest

from wow_coach.errors import GameFolderNotFound
from wow_coach.gamedir import (
    ENV_VARIABLE,
    GameFolder,
    default_candidates,
    resolve_game_folder,
)


def make_game(root: Path) -> Path:
    (root / "WTF").mkdir(parents=True)
    return root


def test_flag_wins_over_env_and_candidates(tmp_path: Path) -> None:
    flag = make_game(tmp_path / "flag")
    env = make_game(tmp_path / "env")
    auto = make_game(tmp_path / "auto")
    found = resolve_game_folder(flag, environ={ENV_VARIABLE: str(env)}, candidates=[auto])
    assert found == GameFolder(path=flag, how_found="the --wow-dir option")


def test_env_wins_over_candidates(tmp_path: Path) -> None:
    env = make_game(tmp_path / "env")
    auto = make_game(tmp_path / "auto")
    found = resolve_game_folder(None, environ={ENV_VARIABLE: str(env)}, candidates=[auto])
    assert found.path == env
    assert ENV_VARIABLE in found.how_found


def test_blank_env_is_ignored(tmp_path: Path) -> None:
    auto = make_game(tmp_path / "auto")
    found = resolve_game_folder(None, environ={ENV_VARIABLE: "  "}, candidates=[auto])
    assert found.path == auto


def test_auto_detect_takes_first_candidate_with_a_wtf_folder(tmp_path: Path) -> None:
    no_wtf = tmp_path / "empty"
    no_wtf.mkdir()
    second = make_game(tmp_path / "second")
    third = make_game(tmp_path / "third")
    found = resolve_game_folder(None, environ={}, candidates=[no_wtf, second, third])
    assert found.path == second
    assert "auto-detected" in found.how_found


def test_flag_that_does_not_exist_names_the_value(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    with pytest.raises(GameFolderNotFound, match="nope"):
        resolve_game_folder(missing, environ={}, candidates=[])


def test_env_that_does_not_exist_names_the_variable(tmp_path: Path) -> None:
    with pytest.raises(GameFolderNotFound, match=ENV_VARIABLE):
        resolve_game_folder(None, environ={ENV_VARIABLE: str(tmp_path / "nope")}, candidates=[])


def test_nothing_found_lists_what_was_tried_and_the_fix(tmp_path: Path) -> None:
    tried = tmp_path / "tried-here"
    with pytest.raises(GameFolderNotFound) as caught:
        resolve_game_folder(None, environ={}, candidates=[tried])
    message = str(caught.value)
    assert str(tried) in message
    assert "--wow-dir" in message
    assert ENV_VARIABLE in message


def test_windows_candidates_cover_both_program_files_and_other_drives() -> None:
    drives = {"C:", "D:"}
    paths = default_candidates(
        platform="win32", home=Path("C:/Users/x"), existing_drives=lambda: drives
    )
    text = [str(path) for path in paths]
    assert any("Program Files (x86)" in item and item.startswith("C:") for item in text)
    assert any("Program Files" in item and item.startswith("D:") for item in text)
    assert all(item.endswith("_forever_") for item in text)
    assert not any(item.startswith("E:") for item in text)


def test_macos_candidate() -> None:
    paths = default_candidates(platform="darwin", home=Path("/Users/x"))
    assert paths == [Path("/Applications/World of Warcraft/_forever_")]


def test_linux_candidates_are_under_home() -> None:
    home = Path("/home/x")
    paths = default_candidates(platform="linux", home=home)
    assert paths == [
        home / "Games/battlenet/drive_c/Program Files (x86)/World of Warcraft/_forever_",
        home / ".wine/drive_c/Program Files (x86)/World of Warcraft/_forever_",
    ]
