"""Tests for the coach's notebook (where it lives, reading, saving)."""

from pathlib import Path

import pytest

from wow_coach.errors import NotesTooLarge
from wow_coach.notes import (
    MAX_BACKUPS,
    MAX_NOTES_BYTES,
    journal_goal,
    journal_path,
    journals_folder,
    notes_path,
    read_notes,
    safe_file_name,
    save_notes,
)

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
    assert "no player notes yet" in text.lower()
    assert "save_player_notes" in text


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


def test_save_confirmation_names_the_kind_of_notes(tmp_path: Path) -> None:
    confirmation = save_notes(tmp_path / "j.md", "hi", what="journal")
    assert confirmation.startswith("Saved 2 bytes of journal to ")


def test_read_with_a_custom_missing_message(tmp_path: Path) -> None:
    assert read_notes(tmp_path / "none.md", missing_message="nothing here") == "nothing here"


# --- journals -------------------------------------------------------------


def test_journals_live_in_a_characters_folder_next_to_the_player_notes() -> None:
    path = journal_path("Testchar-Testrealm", environ={}, platform="linux", home=HOME)
    assert path == HOME / ".local/share/wow-coach/characters/Testchar-Testrealm.md"


def test_journals_follow_the_notes_file_variable() -> None:
    env = {"WOW_COACH_NOTES_FILE": "/notes/mine.md"}
    assert journals_folder(environ=env, platform="linux", home=HOME) == Path("/notes/characters")


def test_journal_path_on_windows() -> None:
    env = {"LOCALAPPDATA": "C:/Users/x/AppData/Local"}
    path = journal_path("Testchar-Testrealm", environ=env, platform="win32", home=HOME)
    assert path == Path("C:/Users/x/AppData/Local/wow-coach/characters/Testchar-Testrealm.md")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Testchar-Some Realm 8 PvP", "Testchar-Some Realm 8 PvP"),
        ('a<b>c:d"e/f\\g|h?i*j', "a_b_c_d_e_f_g_h_i_j"),
        ("tab\there\nnewline", "tab_here_newline"),
        ("Ünïcode-Ørealm", "Ünïcode-Ørealm"),
        ("ends with dot.", "ends with dot"),
        ("  padded  ", "padded"),
        ("../../evil", "_.._evil"),
        ("..", "character"),
        ("", "character"),
    ],
)
def test_safe_file_name(text: str, expected: str) -> None:
    assert safe_file_name(text) == expected


def test_a_journal_name_can_never_leave_its_folder() -> None:
    path = journal_path("../../evil-Realm", environ={}, platform="linux", home=HOME)
    assert path.parent == journals_folder(environ={}, platform="linux", home=HOME)


def write_journal(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "j.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_goal_is_the_first_bullet_under_goals(tmp_path: Path) -> None:
    path = write_journal(
        tmp_path,
        "# Journal\n\n## Choices\n- Frost\n\n## Goals\n\n- Level 20 by Sunday\n- Second\n"
        "\n## Other\n- x\n",
    )
    assert journal_goal(path) == "Level 20 by Sunday"


def test_goal_accepts_star_bullets_and_other_heading_levels(tmp_path: Path) -> None:
    assert journal_goal(write_journal(tmp_path, "### Goals\n* 100 gold\n")) == "100 gold"


def test_goal_ignores_other_sections_and_templates(tmp_path: Path) -> None:
    assert journal_goal(write_journal(tmp_path, "## Choices\n- Frost\n")) is None
    template = "## Goals\n- Goal: <measurable target> by <date>\n- Plan: real plan\n"
    assert journal_goal(write_journal(tmp_path, template)) == "Plan: real plan"
    assert journal_goal(write_journal(tmp_path, "## Goals\n-\n")) is None


def test_goal_of_a_missing_file_is_none(tmp_path: Path) -> None:
    assert journal_goal(tmp_path / "none.md") is None


# ---- backups: a bad save can always be undone -----------------------------------------


def _backups(target: Path) -> list[Path]:
    return sorted((target.parent / ".history").glob("*"))


def test_overwriting_keeps_the_previous_version_in_history(tmp_path: Path) -> None:
    target = tmp_path / "characters" / "Gorbo-Realm.md"
    save_notes(target, "first")
    assert not (target.parent / ".history").exists()  # nothing to back up yet
    save_notes(target, "second", now=1_700_000_000.0)
    [backup] = _backups(target)
    assert backup.read_text(encoding="utf-8") == "first"
    assert backup.name.startswith("Gorbo-Realm-20231114-221320")
    assert backup.suffix == ".md"
    assert target.read_text(encoding="utf-8") == "second"


def test_saving_the_same_text_again_makes_no_backup(tmp_path: Path) -> None:
    target = tmp_path / "n.md"
    save_notes(target, "same")
    save_notes(target, "same")
    assert _backups(target) == []


def test_only_the_newest_twenty_versions_are_kept(tmp_path: Path) -> None:
    target = tmp_path / "n.md"
    for number in range(30):
        save_notes(target, f"version {number}", now=1_700_000_000.0 + number)
    backups = _backups(target)
    assert len(backups) == MAX_BACKUPS == 20
    # versions 0..28 were replaced; the newest 20 of them are 9..28
    assert backups[0].read_text(encoding="utf-8") == "version 9"
    assert backups[-1].read_text(encoding="utf-8") == "version 28"


def test_two_saves_in_the_same_instant_do_not_overwrite_each_others_backup(
    tmp_path: Path,
) -> None:
    target = tmp_path / "n.md"
    save_notes(target, "a")
    save_notes(target, "b", now=1_700_000_000.0)
    save_notes(target, "c", now=1_700_000_000.0)
    assert sorted(p.read_text(encoding="utf-8") for p in _backups(target)) == ["a", "b"]


def test_backups_of_different_files_do_not_prune_each_other(tmp_path: Path) -> None:
    for name in ("a.md", "b.md"):
        for number in range(25):
            save_notes(tmp_path / name, f"{number}", now=1_700_000_000.0 + number)
    assert len(list((tmp_path / ".history").glob("a-*"))) == 20
    assert len(list((tmp_path / ".history").glob("b-*"))) == 20


def test_a_refused_save_leaves_no_backup(tmp_path: Path) -> None:
    target = tmp_path / "n.md"
    save_notes(target, "keep me")
    with pytest.raises(NotesTooLarge):
        save_notes(target, "x" * (MAX_NOTES_BYTES + 1))
    assert _backups(target) == []
    assert target.read_text(encoding="utf-8") == "keep me"
