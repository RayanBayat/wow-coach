"""Answers keep working for players who still have the old CoachLink addon.

HeroBridge was called CoachLink before 0.11.0. With HeroBridge (or nothing) installed we write
``HeroBridge_Advice``; with only the old CoachLink we keep writing ``CoachLink_Advice``.
"""

from pathlib import Path

from wow_coach.advice.contract import AdviceAnswer, AdviceFile, CharacterAdvice
from wow_coach.advice.paths import advice_addon_for, advice_file_path
from wow_coach.advice.reader import read_advice_file
from wow_coach.advice.writer import interface_from_herobridge, update_advice, write_advice

ADVICE = AdviceFile(
    written_at=10,
    characters={
        "Testchar-Testrealm": CharacterAdvice(
            based_on_save=5,
            answers=(AdviceAnswer(answered_at=10, source="test", title="Hi", steps=("Go",)),),
        )
    },
)


def make_addons(tmp_path: Path, *folders: str) -> Path:
    addons = tmp_path / "Interface" / "AddOns"
    addons.mkdir(parents=True)
    for name in folders:
        (addons / name).mkdir()
    return addons


def test_with_herobridge_installed_the_new_addon_is_written(tmp_path: Path) -> None:
    addons = make_addons(tmp_path, "HeroBridge")
    write_advice(addons, ADVICE, interface="16001")
    text = (addons / "HeroBridge_Advice" / "Advice.lua").read_text()
    assert text.count("HeroBridgeAdvice = {") == 1
    assert "CoachLink" not in text
    assert not (addons / "CoachLink_Advice").exists()
    assert (addons / "HeroBridge_Advice" / "HeroBridge_Advice.toc").is_file()


def test_with_nothing_installed_yet_the_new_addon_is_written(tmp_path: Path) -> None:
    addons = make_addons(tmp_path)
    assert advice_addon_for(addons).folder_name == "HeroBridge_Advice"


def test_with_only_the_old_coachlink_the_old_addon_is_written(tmp_path: Path) -> None:
    addons = make_addons(tmp_path, "CoachLink")
    write_advice(addons, ADVICE, interface="16001")
    folder = addons / "CoachLink_Advice"
    assert "CoachLinkAdvice = {" in (folder / "Advice.lua").read_text()
    assert "## Title: CoachLink Advice" in (folder / "CoachLink_Advice.toc").read_text()
    assert not (addons / "HeroBridge_Advice").exists()


def test_with_both_installed_herobridge_wins(tmp_path: Path) -> None:
    addons = make_addons(tmp_path, "CoachLink", "HeroBridge")
    assert advice_addon_for(addons).folder_name == "HeroBridge_Advice"


def test_update_advice_for_the_old_addon_reads_and_keeps_the_old_global(tmp_path: Path) -> None:
    addons = make_addons(tmp_path, "CoachLink")
    write_advice(addons, ADVICE, interface="16001")
    update_advice(addons, lambda current: current, interface="16001", now=20)
    written = read_advice_file(advice_file_path(tmp_path))
    assert written is not None
    assert "Testchar-Testrealm" in written.characters
    assert "CoachLinkAdvice = {" in (addons / "CoachLink_Advice" / "Advice.lua").read_text()


def test_the_reader_understands_a_file_with_the_old_global(tmp_path: Path) -> None:
    addons = make_addons(tmp_path, "CoachLink")
    write_advice(addons, ADVICE, interface="16001")
    path = addons / "CoachLink_Advice" / "Advice.lua"
    assert read_advice_file(path) == ADVICE


def test_interface_number_falls_back_to_the_old_toc(tmp_path: Path) -> None:
    addons = make_addons(tmp_path, "CoachLink")
    (addons / "CoachLink" / "CoachLink.toc").write_text("## Interface: 16002\n")
    assert interface_from_herobridge(addons) == "16002"
