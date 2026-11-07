"""End to end: fixture file on disk -> savedvars -> report."""

import shutil
from pathlib import Path

from wow_coach.report import format_history, format_status
from wow_coach.savedvars import find_saved_variables, load_characters

FIXTURE = Path(__file__).parent / "fixtures" / "CoachLink.lua"
SAVED_AT = 1793900000.0


def install_fixture(wow_dir: Path) -> None:
    folder = wow_dir / "WTF" / "Account" / "ACC" / "SavedVariables"
    folder.mkdir(parents=True)
    shutil.copy(FIXTURE, folder / "CoachLink.lua")


def test_fixture_is_written_like_wow_forever() -> None:
    raw = FIXTURE.read_bytes()
    assert raw.startswith(b"\r\n")
    assert b"\r\n" in raw
    assert b"\t" not in raw


def test_fixture_through_savedvars_and_report(tmp_path: Path) -> None:
    install_fixture(tmp_path)
    characters = load_characters(find_saved_variables(tmp_path))
    testchar = characters["Testchar-Testrealm"]

    status = format_status(testchar.snapshot, now=SAVED_AT + 120)
    assert "# Testchar: level 7 Undead Mage (Testrealm)" in status
    assert "Saved 2 min ago (coach)" in status
    assert "- [1] Rude Awakening, DONE (turn in)" in status
    assert "- [5] The Damned, 3/8 Scarlet Initiate slain" in status
    assert "Talents" not in status  # empty table is skipped
    assert "- Language: Common" not in status  # a language is not a profession
    assert 'Gnarled "Rotwood" Staff (item level 10, white)' in status
    assert "**Spells:** Fireball, Frost Armor, Frostbolt" in status
    assert "talents: attempt to index a nil value" in status

    history = format_history(testchar.history, limit=10, now=SAVED_AT).splitlines()
    assert history == ["- 1 h ago: Died in Brill (level 7)", "- 2 h ago: Reached level 7"]
