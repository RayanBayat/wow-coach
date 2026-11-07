"""Tests for ``wow-coach check`` (friendly troubleshooting output)."""

import io
import os
from collections.abc import Mapping
from pathlib import Path

from wow_coach.check import run_check

NOW = 1_000_000.0
DATA = (
    'CoachLinkDB = {\n["formatVersion"] = 1,\n["characters"] = {\n'
    '["Testchar-Testrealm"] = {\n["snapshot"] = {\n["name"] = "Testchar",\n'
    '["class"] = "Mage",\n["level"] = 7,\n["zone"] = "Brill",\n["savedAt"] = 999700,\n'
    "},\n},\n},\n}\n"
)


def check(
    flag: Path | None,
    *,
    environ: Mapping[str, str] | None = None,
    candidates: list[Path] | None = None,
) -> tuple[int, str]:
    out = io.StringIO()
    env = {"WOW_COACH_NOTES_FILE": "/notes/coach-notes.md", **(environ or {})}
    code = run_check(flag, environ=env, candidates=candidates or [], now=NOW, out=out)
    return code, out.getvalue()


def install_save(game: Path, text: str = DATA) -> Path:
    folder = game / "WTF" / "Account" / "ACC" / "SavedVariables"
    folder.mkdir(parents=True)
    path = folder / "CoachLink.lua"
    path.write_text(text, encoding="utf-8")
    os.utime(path, (NOW - 300, NOW - 300))
    return path


def test_everything_fine(tmp_path: Path) -> None:
    save = install_save(tmp_path)
    code, text = check(tmp_path)
    assert code == 0
    assert str(tmp_path) in text
    assert "--wow-dir" in text  # says how the folder was found
    assert str(save) in text
    assert "5 min ago" in text
    assert "Testchar-Testrealm: level 7 Mage, Brill" in text
    assert "Everything looks good" in text


def test_game_folder_not_found_lists_places_and_fix(tmp_path: Path) -> None:
    code, text = check(None, candidates=[tmp_path / "nowhere"])
    assert code == 1
    assert "nowhere" in text
    assert "--wow-dir" in text


def test_no_save_file_yet_and_addon_not_installed(tmp_path: Path) -> None:
    (tmp_path / "WTF").mkdir()
    code, text = check(tmp_path)
    assert code == 1
    assert "No save file yet" in text
    assert "start WoW with the CoachLink addon enabled and type /coach" in text
    assert "CoachLink addon is not installed" in text


def test_no_save_file_but_addon_installed(tmp_path: Path) -> None:
    (tmp_path / "WTF").mkdir()
    (tmp_path / "Interface" / "AddOns" / "CoachLink").mkdir(parents=True)
    _, text = check(tmp_path)
    assert "No save file yet" in text
    assert "not installed" not in text


def test_unreadable_save_file(tmp_path: Path) -> None:
    install_save(tmp_path, "CoachLinkDB = {")
    code, text = check(tmp_path)
    assert code == 1
    assert "could not be read" in text


def test_save_file_without_characters(tmp_path: Path) -> None:
    install_save(tmp_path, 'CoachLinkDB = {\n["formatVersion"] = 1,\n}\n')
    code, text = check(tmp_path)
    assert code == 1
    assert "no characters" in text
    assert "/coach" in text


def test_notes_file_location_is_shown(tmp_path: Path) -> None:
    install_save(tmp_path)
    _, text = check(tmp_path)
    assert "/notes/coach-notes.md" in text
