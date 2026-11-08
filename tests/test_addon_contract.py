"""Contract test: the Python reader understands what the real addon writes.

``addon/tests/run_addon_test.lua`` runs the actual HeroBridge addon against a fake
WoW API and writes its HeroBridgeDB in WoW Forever's file format. Here we read that
output with the real Python code. If either side changes the data format without
the other, this test fails.

Needs LuaJIT (``sudo dnf install luajit``); skipped when it is not installed.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from wow_coach.report import format_history, format_status
from wow_coach.savedvars import load_characters

REPO_ROOT = Path(__file__).resolve().parent.parent
HARNESS = REPO_ROOT / "addon" / "tests" / "run_addon_test.lua"
LUAJIT = shutil.which("luajit")
FAKE_NOW = 1793995200  # the harness's fixed clock

# CI also runs on Windows and macOS, where LuaJIT is usually missing.
pytestmark = pytest.mark.skipif(LUAJIT is None, reason="luajit is not installed")


@pytest.fixture
def addon_output(tmp_path: Path) -> Path:
    """Run the addon harness and return the SavedVariables file it wrote."""
    assert LUAJIT is not None  # guaranteed by the skipif above; helps mypy
    output = tmp_path / "HeroBridge.lua"
    # Trusted input: our own harness script and a temp path, no shell involved.
    result = subprocess.run(  # noqa: S603
        [LUAJIT, str(HARNESS), str(output)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return output


def test_addon_output_loads_one_character(addon_output: Path) -> None:
    characters = load_characters(addon_output)

    assert list(characters) == ["Testchar-Testrealm"]


def test_addon_output_formats_into_a_full_status(addon_output: Path) -> None:
    character = load_characters(addon_output)["Testchar-Testrealm"]

    status = format_status(character.snapshot, now=FAKE_NOW)

    for expected in (
        "Testchar",
        "level 7",
        "1g 23s 45c",
        "Brill",
        "Fields of Grief",
        "Frost",
        "Frostbite",
        "Tailoring",
        "Apprentice's Robe",
        "Frostbolt",
    ):
        assert expected in status, f"{expected!r} missing from:\n{status}"


def test_addon_output_history_newest_first(addon_output: Path) -> None:
    character = load_characters(addon_output)["Testchar-Testrealm"]

    history = format_history(character.history, limit=10, now=FAKE_NOW)

    assert history.splitlines()[0].endswith("Died in Brill (level 7)")


def test_addon_output_lists_each_skill_once_in_its_group(addon_output: Path) -> None:
    character = load_characters(addon_output)["Testchar-Testrealm"]

    status = format_status(character.snapshot, now=FAKE_NOW)

    assert status.count("Tailoring: 23/75") == 1, status
    assert "**Weapon skills:** Staves 35/35" in status, status


def test_addon_output_has_a_progress_point(addon_output: Path) -> None:
    character = load_characters(addon_output)["Testchar-Testrealm"]

    assert len(character.progress) == 1
    point = character.progress[0]
    assert isinstance(point, dict)
    assert point["level"] == 7
    assert point["subZone"] == "Brill"
    assert point["questsDone"] == 1


def test_addon_output_reports_everything_on_the_character(addon_output: Path) -> None:
    character = load_characters(addon_output)["Testchar-Testrealm"]

    status = format_status(character.snapshot, now=FAKE_NOW)

    for expected in (
        "**Faction:** Horde",
        "**Time played:** 2 h 0 min",
        "- Health: 150/180",
        "- Arcane Intellect (buff, 25 min left)",
        "  - Goal: Bring 10 Tirisfal Pumpkins to Farmer Solliden in Brill.",
        "Quests completed so far (all time): 3",
        "- Tailoring 23/75, 2 recipes",
        "- Main hand: Gnarled Staff (item level 9, green, +1 Intellect, +2 Stamina, "
        "durability 50/60)",
        "- Linen Cloth x8 (white, Tradeskill / Cloth, sells for 13c each)",
        "Gray (junk) items sell for 8c in total",
        "**Bank** (seen just now): Bank Tab 1 28 slots (27 free)",
        "- Tough Jerky x4",
        "**Mail** (seen just now): 1 letter",
        "- Frost: Frostbolt (Rank 1), Fireball",
        "- Main bar: 1 Frostbolt, 2 Fireball, 12 Hearthstone",
        "- Undercity: Friendly 500/6000",
        "**Currencies:** Legacy Token 3",
        "- Perks: Quick Learner (Adventure, 1/1)",
        "**Mounts:** Skeletal Horse",
    ):
        assert expected in status, f"{expected!r} missing from:\n{status}"
