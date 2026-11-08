"""End to end: the coach's answer travels from the MCP tool to the in-game Coach panel.

The Python side writes ``CoachLink_Advice/Advice.lua`` with ``answer_send_advice_to_game``,
then the panel's Lua test harness loads that very file with LuaJIT (the language the game
uses) and checks what the panel shows. This proves the two halves agree on the format, and
that AI text can't turn into WoW color codes or links: the panel must show them as plain
text (doubled ``||``, which WoW draws as a single ``|``).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from wow_coach.advice.tools import answer_send_advice_to_game

ROOT = Path(__file__).parent.parent
HARNESS = ROOT / "addon" / "tests" / "run_panel_test.lua"
SAVE = """
CoachLinkDB = {
["formatVersion"] = 1,
["characters"] = {
["Testchar-Testrealm"] = {
["snapshot"] = {
["name"] = "Testchar",
["savedAt"] = 1793994600,
},
},
},
}
"""

pytestmark = pytest.mark.skipif(shutil.which("luajit") is None, reason="needs luajit")


def make_game(tmp_path: Path) -> Path:
    saved = tmp_path / "WTF" / "Account" / "ACC" / "SavedVariables"
    saved.mkdir(parents=True)
    (saved / "CoachLink.lua").write_text(SAVE, encoding="utf-8")
    (tmp_path / "Interface" / "AddOns").mkdir(parents=True)
    return tmp_path


def run_panel(advice_file: Path, step: str, body: str) -> str:
    result = subprocess.run(  # noqa: S603  (our own harness, fixed arguments)
        ["luajit", str(HARNESS), "--advice-file", str(advice_file), step, body],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return result.stdout + result.stderr


def test_an_answer_written_by_the_tool_shows_in_the_panel(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    reply = answer_send_advice_to_game(
        wow_dir=game,
        character_key="Testchar-Testrealm",
        based_on_save=1793994600,
        title="Next steps",
        steps=['Talk to "Farmer Solliden" in Brill.', "Then sell your gray items."],
        text="It's close.\nTake the road east.",
        warnings=[],
        question_id=None,
        source="Test coach",
        now=1793995000,
    )
    assert "/reload" in reply
    advice_file = game / "Interface" / "AddOns" / "CoachLink_Advice" / "Advice.lua"
    output = run_panel(advice_file, 'Talk to "Farmer Solliden" in Brill.', "Take the road east.")
    assert "ALL PASSED" in output, output


def test_color_codes_from_the_ai_stay_plain_text_in_the_panel(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    answer_send_advice_to_game(
        wow_dir=game,
        character_key="Testchar-Testrealm",
        based_on_save=None,
        title="Tricky",
        steps=["|cffff0000Red|r |Hitem:6948|h[Hearthstone]|h"],
        text="|TInterface\\Icons\\INV_Misc_QuestionMark:0|t picture",
        warnings=[],
        question_id=None,
        source="Test coach",
        now=1793995000,
    )
    advice_file = game / "Interface" / "AddOns" / "CoachLink_Advice" / "Advice.lua"
    # Doubled pipes reach the panel: WoW draws "||" as a plain "|", so nothing is colored,
    # linked or turned into a picture.
    output = run_panel(
        advice_file,
        "||cffff0000Red||r ||Hitem:6948||h",
        "||TInterface\\Icons\\INV_Misc_QuestionMark",
    )
    assert "ALL PASSED" in output, output
