"""Tests for the ``wow-coach`` command line."""

import importlib.metadata
import io
import os
import zipfile
from collections.abc import Mapping
from pathlib import Path

import pytest

from wow_coach import cli
from wow_coach.cli import main


def addon_zip_bytes() -> bytes:
    version = importlib.metadata.version("wow-coach")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("CoachLink/CoachLink.toc", f"## Version: {version}\n")
    return buffer.getvalue()


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


WIKI_FIXTURES = Path(__file__).parent / "fixtures" / "wiki"


def _fake_wiki(_url: str, params: Mapping[str, str]) -> str:
    name = "search_abigail.json" if params["action"] == "query" else "parse_Abigail_Shiel.json"
    return (WIKI_FIXTURES / name).read_text(encoding="utf-8")


def test_wiki_searches(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["wiki", "Abigail Shiel"], fetch=_fake_wiki) == 0
    out = capsys.readouterr().out
    assert "1. Abigail Shiel" in out
    assert "Source: Warcraft Wiki" in out


def test_wiki_reads_a_page_and_a_section(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["wiki", "Abigail Shiel", "--page", "Abigail Shiel"], fetch=_fake_wiki) == 0
    assert "- Title: Trade Supplies" in capsys.readouterr().out
    assert main(["wiki", "--page", "Abigail Shiel", "--section", "Sells"], fetch=_fake_wiki) == 0
    assert "Section: Sells" in capsys.readouterr().out


def test_wiki_without_anything_to_do_explains(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["wiki"], fetch=_fake_wiki) == 2
    assert "--page" in capsys.readouterr().err


def test_setup_command_runs_with_fake_downloads(
    wow_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WOW_COACH_NOTES_FILE", str(tmp_path / "notes.md"))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")

    def fake_download(_url: str) -> bytes:
        return addon_zip_bytes()

    assert main(["setup", "--wow-dir", str(wow_dir), "--yes"], download=fake_download) == 0
    out = capsys.readouterr().out
    assert "Step 1 of 5" in out
    assert (wow_dir / "Interface" / "AddOns" / "CoachLink" / "CoachLink.toc").is_file()
    assert not (tmp_path / "home").exists()  # no --claude-code, so ~/.claude is untouched
