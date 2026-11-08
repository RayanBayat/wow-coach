"""Tests for the data addon writer: folder, .toc, atomic write and path safety."""

import os
from pathlib import Path

import pytest

from wow_coach.advice.contract import AdviceAnswer, AdviceFile, CharacterAdvice
from wow_coach.advice.reader import read_advice_file
from wow_coach.advice.serialize import AdviceTooLarge
from wow_coach.advice.writer import (
    UnsafeAdvicePath,
    install_advice_addon,
    interface_from_herobridge,
    write_advice,
)
from wow_coach.errors import WowCoachError

KEY = "Testchar-Testrealm"


def advice_with(title: str) -> AdviceFile:
    answer = AdviceAnswer(answered_at=1, source="S", title=title)
    return AdviceFile(1, {KEY: CharacterAdvice(1, (answer,))})


@pytest.fixture
def addons(tmp_path: Path) -> Path:
    folder = tmp_path / "Interface" / "AddOns"
    folder.mkdir(parents=True)
    return folder


def test_install_makes_the_toc(addons: Path) -> None:
    folder = install_advice_addon(addons, interface="16001")
    assert folder == addons / "HeroBridge_Advice"
    lines = (folder / "HeroBridge_Advice.toc").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "## Interface: 16001"
    assert lines[1] == "## Title: HeroBridge Advice"
    assert lines[2].startswith("## Notes:") and "wow-coach" in lines[2]
    assert lines[3].startswith("## Version: ")
    assert lines[-1] == "Advice.lua"
    assert not any("SavedVariables" in line for line in lines)


def test_install_refreshes_the_interface_number(addons: Path) -> None:
    install_advice_addon(addons, interface="16001")
    folder = install_advice_addon(addons, interface="16002")
    assert "## Interface: 16002" in (folder / "HeroBridge_Advice.toc").read_text(encoding="utf-8")


@pytest.mark.parametrize("bad", ["", "16001\n## SavedVariables: X", "abc", "1;2"])
def test_install_refuses_a_bad_interface(addons: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="Interface"):
        install_advice_addon(addons, interface=bad)
    assert not (addons / "HeroBridge_Advice").exists()


def test_install_refuses_a_missing_addons_folder(tmp_path: Path) -> None:
    with pytest.raises(UnsafeAdvicePath):
        install_advice_addon(tmp_path / "nope", interface="16001")
    assert not (tmp_path / "nope").exists()


def test_write_advice_round_trips_and_installs(addons: Path) -> None:
    path = write_advice(addons, advice_with("hello"), interface="16001")
    assert path == addons / "HeroBridge_Advice" / "Advice.lua"
    assert (addons / "HeroBridge_Advice" / "HeroBridge_Advice.toc").is_file()
    assert read_advice_file(path) == advice_with("hello")


def test_only_two_files_are_left_behind(addons: Path) -> None:
    write_advice(addons, advice_with("a"), interface="16001")
    write_advice(addons, advice_with("b"), interface="16001")
    names = sorted(p.name for p in (addons / "HeroBridge_Advice").iterdir())
    assert names == ["Advice.lua", "HeroBridge_Advice.toc"]


def test_a_failed_write_keeps_the_old_file(addons: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_advice(addons, advice_with("old"), interface="16001")
    before = path.read_bytes()

    def broken_replace(*_paths: object) -> None:
        raise OSError("disk exploded")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError, match="disk exploded"):
        write_advice(addons, advice_with("new"), interface="16001")
    assert path.read_bytes() == before
    assert sorted(p.name for p in path.parent.iterdir()) == ["Advice.lua", "HeroBridge_Advice.toc"]


def test_too_large_advice_changes_nothing(addons: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_advice(addons, advice_with("old"), interface="16001")
    before = path.read_bytes()
    monkeypatch.setattr("wow_coach.advice.serialize.MAX_FILE_BYTES", 100)
    with pytest.raises(AdviceTooLarge):
        write_advice(addons, advice_with("x" * 70), interface="16001")
    assert path.read_bytes() == before


def test_symlinked_folder_is_refused_and_nothing_is_written(addons: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (addons / "HeroBridge_Advice").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnsafeAdvicePath):
        write_advice(addons, advice_with("x"), interface="16001")
    assert list(outside.iterdir()) == []


def test_dangling_symlinked_folder_is_refused(addons: Path, tmp_path: Path) -> None:
    (addons / "HeroBridge_Advice").symlink_to(tmp_path / "not-there", target_is_directory=True)
    with pytest.raises(UnsafeAdvicePath):
        install_advice_addon(addons, interface="16001")
    assert not (tmp_path / "not-there").exists()


def test_symlinked_advice_file_is_refused(addons: Path, tmp_path: Path) -> None:
    folder = install_advice_addon(addons, interface="16001")
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me", encoding="utf-8")
    (folder / "Advice.lua").symlink_to(victim)
    with pytest.raises(UnsafeAdvicePath):
        write_advice(addons, advice_with("x"), interface="16001")
    assert victim.read_text(encoding="utf-8") == "keep me"


def test_symlinked_toc_is_refused(addons: Path, tmp_path: Path) -> None:
    folder = addons / "HeroBridge_Advice"
    folder.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me", encoding="utf-8")
    (folder / "HeroBridge_Advice.toc").symlink_to(victim)
    with pytest.raises(UnsafeAdvicePath):
        install_advice_addon(addons, interface="16001")
    assert victim.read_text(encoding="utf-8") == "keep me"


def test_a_plain_file_in_place_of_the_folder_is_refused(addons: Path) -> None:
    (addons / "HeroBridge_Advice").write_text("oops", encoding="utf-8")
    with pytest.raises(UnsafeAdvicePath):
        install_advice_addon(addons, interface="16001")


def test_refusals_are_wow_coach_errors() -> None:
    assert issubclass(UnsafeAdvicePath, WowCoachError)


def test_symlinked_addons_next_to_ours_are_fine(addons: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (addons / "OtherAddon").symlink_to(elsewhere, target_is_directory=True)
    write_advice(addons, advice_with("x"), interface="16001")
    assert list(elsewhere.iterdir()) == []


def test_symlinked_addons_folder_itself_is_fine(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "AddOns"
    link.symlink_to(real, target_is_directory=True)
    write_advice(link, advice_with("x"), interface="16001")
    assert (real / "HeroBridge_Advice" / "Advice.lua").is_file()


# ---- interface_from_herobridge -----------------------------------------------------------


def test_interface_is_read_from_herobridge_toc(addons: Path) -> None:
    (addons / "HeroBridge").mkdir()
    (addons / "HeroBridge" / "HeroBridge.toc").write_text(
        "## Interface: 16002\n## Title: HeroBridge\n", encoding="utf-8"
    )
    assert interface_from_herobridge(addons) == "16002"


def test_interface_falls_back(addons: Path) -> None:
    assert interface_from_herobridge(addons) == "16001"
    (addons / "HeroBridge").mkdir()
    (addons / "HeroBridge" / "HeroBridge.toc").write_text(
        "## Title: HeroBridge\n", encoding="utf-8"
    )
    assert interface_from_herobridge(addons) == "16001"
