"""Tests for the ``wow-coach`` command line."""

import os
from pathlib import Path

import pytest

from wow_coach import cli
from wow_coach.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "CoachLink.lua"


@pytest.fixture
def wow_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "game" / "WTF" / "Account" / "ACC" / "SavedVariables"
    folder.mkdir(parents=True)
    (folder / "CoachLink.lua").write_bytes(FIXTURE.read_bytes())
    return tmp_path / "game"


def test_status_prints_markdown_and_history(
    wow_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status", "--wow-dir", str(wow_dir)]) == 0
    out = capsys.readouterr().out
    assert "# Testchar: level 7 Undead Mage (Testrealm)" in out
    assert "Recent history" in out


def test_status_picks_a_named_character(wow_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["status", "--character", "testchar", "--wow-dir", str(wow_dir)]) == 0
    assert "# Testchar" in capsys.readouterr().out


def test_status_unknown_character_fails_politely(
    wow_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status", "--character", "Nobody", "--wow-dir", str(wow_dir)]) == 1
    assert "Nobody" in capsys.readouterr().err


def test_status_without_game_folder_explains(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WOW_COACH_WOW_DIR", raising=False)
    assert main(["status", "--wow-dir", str(tmp_path / "nope")]) == 1
    assert "nope" in capsys.readouterr().err


def test_check_command_runs(wow_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", "--wow-dir", str(wow_dir)]) == 0
    assert "Game folder" in capsys.readouterr().out


def test_watch_exits_cleanly_on_ctrl_c(
    wow_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", interrupt)
    assert main(["watch", "--wow-dir", str(wow_dir)]) == 0
    assert capsys.readouterr().out.startswith("watching for /coach saves in ")


def test_mcp_command_starts_the_server(wow_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[Path | None] = []
    monkeypatch.setattr(cli, "run_mcp_server", started.append)
    assert main(["mcp", "--wow-dir", str(wow_dir)]) == 0
    assert started == [wow_dir]


def test_no_command_shows_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main([])
    assert caught.value.code == 2
    assert "usage: wow-coach" in capsys.readouterr().err


def test_help_lists_every_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    out = capsys.readouterr().out
    for command in ("status", "watch", "mcp", "check"):
        assert command in out


def test_environment_variable_is_used(
    wow_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WOW_COACH_WOW_DIR", str(wow_dir))
    assert main(["status"]) == 0
    assert "Testchar" in capsys.readouterr().out
    assert os.environ["WOW_COACH_WOW_DIR"] == str(wow_dir)
