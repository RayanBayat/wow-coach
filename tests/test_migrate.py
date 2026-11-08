"""Moving a player from CoachLink to HeroBridge: the save, the answers, the old folders."""

import os
from pathlib import Path

import pytest

from wow_coach.advice.contract import AdviceAnswer, AdviceFile, CharacterAdvice
from wow_coach.advice.reader import read_advice_file
from wow_coach.advice.writer import write_advice
from wow_coach.errors import WowCoachError
from wow_coach.game_running import GAME_PROGRAM_NAMES, is_game_running
from wow_coach.migrate import (
    GAME_RUNNING_SENTENCE,
    copy_saves_to_herobridge,
    finish_upgrade,
    old_folders_to_remove,
    renamed_save_text,
    upgrade_pending,
)
from wow_coach.savedvars import load_characters

OLD_SAVE = (
    'CoachLinkDB = {\n["formatVersion"] = 1,\n["characters"] = {\n'
    '["Testchar-Testrealm"] = {\n["snapshot"] = {\n["savedAt"] = 42,\n'
    '["note"] = "CoachLinkDB = is just text here",\n},\n},\n},\n}\n'
)


def make_game(tmp_path: Path, *accounts: str) -> Path:
    for account in accounts:
        folder = tmp_path / "WTF" / "Account" / account / "SavedVariables"
        folder.mkdir(parents=True)
        (folder / "CoachLink.lua").write_text(OLD_SAVE, encoding="utf-8", newline="")
    (tmp_path / "Interface" / "AddOns").mkdir(parents=True)
    return tmp_path


def save_path(game: Path, account: str, name: str) -> Path:
    return game / "WTF" / "Account" / account / "SavedVariables" / name


# ---- the renaming itself -------------------------------------------------------------------


def test_only_the_top_level_assignment_is_renamed() -> None:
    new = renamed_save_text(OLD_SAVE)
    assert new.startswith("HeroBridgeDB = {")
    assert '"CoachLinkDB = is just text here"' in new  # text inside the data is untouched
    assert new.replace("HeroBridgeDB", "CoachLinkDB", 1) == OLD_SAVE


def test_a_file_without_the_variable_is_refused() -> None:
    with pytest.raises(WowCoachError, match="CoachLinkDB"):
        renamed_save_text("Other = {}\n")


def test_a_file_that_is_not_lua_data_is_refused() -> None:
    with pytest.raises(WowCoachError):
        renamed_save_text("CoachLinkDB = {")


# ---- copying the save ---------------------------------------------------------------------


def test_the_save_is_copied_for_every_account_and_the_old_one_stays(tmp_path: Path) -> None:
    game = make_game(tmp_path, "ACC1", "ACC2")
    report = copy_saves_to_herobridge(game, is_running=False)
    assert report.ok
    for account in ("ACC1", "ACC2"):
        assert save_path(game, account, "CoachLink.lua").read_text() == OLD_SAVE
        new = save_path(game, account, "HeroBridge.lua")
        assert load_characters(new)["Testchar-Testrealm"].snapshot["savedAt"] == 42
    assert not list((game / "WTF").rglob(".tmp-*"))


def test_line_endings_are_kept(tmp_path: Path) -> None:
    game = make_game(tmp_path, "A")
    old = save_path(game, "A", "CoachLink.lua")
    old.write_bytes(OLD_SAVE.replace("\n", "\r\n").encode())
    copy_saves_to_herobridge(game, is_running=False)
    assert b"\r\n" in save_path(game, "A", "HeroBridge.lua").read_bytes()


def test_an_existing_herobridge_save_is_never_replaced(tmp_path: Path) -> None:
    game = make_game(tmp_path, "A")
    existing = save_path(game, "A", "HeroBridge.lua")
    existing.write_text("HeroBridgeDB = {}\n")
    report = copy_saves_to_herobridge(game, is_running=False)
    assert report.ok
    assert existing.read_text() == "HeroBridgeDB = {}\n"


def test_nothing_is_copied_while_the_game_runs(tmp_path: Path) -> None:
    game = make_game(tmp_path, "A")
    report = copy_saves_to_herobridge(game, is_running=True)
    assert report.problems == [GAME_RUNNING_SENTENCE]
    assert not save_path(game, "A", "HeroBridge.lua").exists()


def test_a_broken_old_save_is_reported_and_writes_nothing(tmp_path: Path) -> None:
    game = make_game(tmp_path, "A", "B")
    save_path(game, "A", "CoachLink.lua").write_text("CoachLinkDB = {")
    report = copy_saves_to_herobridge(game, is_running=False)
    assert len(report.problems) == 1
    assert "account A" in report.problems[0]
    assert not save_path(game, "A", "HeroBridge.lua").exists()
    assert save_path(game, "B", "HeroBridge.lua").is_file()  # the other account still moved


# ---- the whole upgrade --------------------------------------------------------------------


def make_old_addons(game: Path) -> Path:
    addons = game / "Interface" / "AddOns"
    for name in ("CoachLink", "CoachLink_Advice", "HeroBridge"):
        (addons / name).mkdir()
    (addons / "HeroBridge" / "HeroBridge.toc").write_text("## Interface: 16001\n")
    (addons / "CoachLink" / "CoachLink.toc").write_text("## Version: 0.10.0\n")
    return addons


def test_finish_upgrade_copies_saves_then_removes_the_old_folders(tmp_path: Path) -> None:
    game = make_game(tmp_path, "A")
    addons = make_old_addons(game)
    assert upgrade_pending(game)
    report = finish_upgrade(game, is_running=False)
    assert report.ok
    assert save_path(game, "A", "HeroBridge.lua").is_file()
    assert not (addons / "CoachLink").exists()
    assert not (addons / "CoachLink_Advice").exists()
    assert (addons / "HeroBridge").is_dir()
    assert not upgrade_pending(game)


def test_old_answers_come_along(tmp_path: Path) -> None:
    game = make_game(tmp_path, "A")
    addons = make_old_addons(game)
    advice = AdviceFile(
        written_at=5,
        characters={
            "Testchar-Testrealm": CharacterAdvice(
                based_on_save=1,
                answers=(AdviceAnswer(answered_at=5, source="s", title="Old answer"),),
            )
        },
    )
    # The old addon is the only one at this moment, so the old names are written.
    old_only = tmp_path / "old_only"
    (old_only / "CoachLink").mkdir(parents=True)
    write_advice(old_only, advice, interface="16001")
    (old_only / "CoachLink_Advice" / "Advice.lua").replace(
        addons / "CoachLink_Advice" / "Advice.lua"
    )
    finish_upgrade(game, is_running=False)
    moved = read_advice_file(addons / "HeroBridge_Advice" / "Advice.lua")
    assert moved is not None
    assert moved.characters["Testchar-Testrealm"].answers[0].title == "Old answer"


def test_a_failed_save_copy_keeps_the_old_folders(tmp_path: Path) -> None:
    game = make_game(tmp_path, "A")
    addons = make_old_addons(game)
    save_path(game, "A", "CoachLink.lua").write_text("CoachLinkDB = {")
    report = finish_upgrade(game, is_running=False)
    assert not report.ok
    assert (addons / "CoachLink").is_dir()


def test_nothing_changes_while_the_game_runs(tmp_path: Path) -> None:
    game = make_game(tmp_path, "A")
    addons = make_old_addons(game)
    report = finish_upgrade(game, is_running=True)
    assert not report.ok
    assert (addons / "CoachLink").is_dir()


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs special rights on Windows")
def test_a_linked_old_addon_is_left_alone_and_reported(tmp_path: Path) -> None:
    game = make_game(tmp_path, "A")
    addons = game / "Interface" / "AddOns"
    repo_copy = tmp_path / "repo" / "CoachLink"
    repo_copy.mkdir(parents=True)
    (repo_copy / "keep.txt").write_text("mine")
    (addons / "CoachLink").symlink_to(repo_copy, target_is_directory=True)
    (addons / "CoachLink_Advice").mkdir()
    assert old_folders_to_remove(addons) == [addons / "CoachLink_Advice"]
    report = finish_upgrade(game, is_running=False)
    assert report.ok
    assert (repo_copy / "keep.txt").read_text() == "mine"
    assert (addons / "CoachLink").is_symlink()
    assert any("link" in note for note in report.notes)
    assert not (addons / "CoachLink_Advice").exists()


# ---- is the game running? -----------------------------------------------------------------


def test_game_running_sees_the_game_by_name() -> None:
    assert is_game_running(lambda: ["bash", "Wow.exe"])
    assert is_game_running(lambda: ["WowClassic.exe"])


def test_game_running_ignores_other_programs_even_if_they_start_with_wow() -> None:
    assert not is_game_running(lambda: ["wow-coach", "wow-coach-app", "bash"])


def test_game_running_says_no_when_the_list_cannot_be_read() -> None:
    def broken() -> list[str]:
        raise OSError("no /proc here")

    assert not is_game_running(broken)


def test_all_listed_names_are_lower_case() -> None:
    assert all(name == name.lower() for name in GAME_PROGRAM_NAMES)
