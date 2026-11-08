"""Cross-check with the real Lua engine: can the game load what Python writes?

Skipped when ``luajit`` is not installed. WoW uses Lua 5.1, which LuaJIT matches.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from wow_coach.advice.contract import AdviceAnswer, AdviceFile, CharacterAdvice, CoachPlan
from wow_coach.advice.serialize import advice_to_lua

LUAJIT = shutil.which("luajit")
pytestmark = pytest.mark.skipif(LUAJIT is None, reason="luajit is not installed")

KEY = "Testchar-Testrealm"
NASTY = (
    'quote " backslash \\ newline \n tab \t nul \x00 pipe |cffff0000red|r emoji \U0001f600 \u00e5'
)

# Prints the fields we want to compare, one per line, with newlines in text shown as "\n".
SCRIPT = """
dofile(arg[1])
local advice = CoachLinkAdvice
local character = advice.characters["Testchar-Testrealm"]
local answer = character.answers[1]
local function show(value) return (tostring(value):gsub("\\n", "\\\\n"):gsub("%z", "<nul>")) end
print(advice.formatVersion)
print(advice.writtenAt)
print(character.basedOnSave)
print(#character.answers)
print(show(answer.title))
print(show(answer.text))
print(#answer.steps)
print(show(answer.steps[1]))
print(character.plan.goal)
"""


def run_luajit(lua_file: Path, tmp_path: Path) -> list[str]:
    script = tmp_path / "check.lua"
    script.write_text(SCRIPT, encoding="utf-8")
    assert LUAJIT is not None
    done = subprocess.run(  # noqa: S603  (fixed program, our own files)
        [LUAJIT, str(script), str(lua_file)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=30,
    )
    return done.stdout.splitlines()


def test_the_game_engine_loads_what_python_writes(tmp_path: Path) -> None:
    answer = AdviceAnswer(
        answered_at=1794100090,
        source="Coach",
        title='Title \u00e5"|',
        steps=(NASTY, "second"),
        text=NASTY,
        warnings=("w",),
    )
    plan = CoachPlan(goal="Level 20", steps=("a",), updated_at=3)
    advice = AdviceFile(1794100100, {KEY: CharacterAdvice(1794100050, (answer,), plan)})
    lua_file = tmp_path / "Advice.lua"
    lua_file.write_text(advice_to_lua(advice), encoding="utf-8")

    lines = run_luajit(lua_file, tmp_path)

    def shown(text: str) -> str:
        return text.replace("\n", "\\n").replace("\x00", "<nul>").replace("|", "||")

    assert lines == [
        "1",
        "1794100100",
        "1794100050",
        "1",
        shown('Title \u00e5"|'),
        shown(NASTY),
        "2",
        shown(NASTY),
        "Level 20",
    ]


def test_the_engine_sees_no_other_global_or_side_effect(tmp_path: Path) -> None:
    lua_file = tmp_path / "Advice.lua"
    lua_file.write_text(advice_to_lua(AdviceFile(5)), encoding="utf-8")
    script = tmp_path / "globals.lua"
    script.write_text(
        "local before = {}\nfor k in pairs(_G) do before[k] = true end\n"
        "dofile(arg[1])\nfor k in pairs(_G) do if not before[k] then print(k) end end\n",
        encoding="utf-8",
    )
    assert LUAJIT is not None
    done = subprocess.run(  # noqa: S603
        [LUAJIT, str(script), str(lua_file)], capture_output=True, text=True, check=True, timeout=30
    )
    assert done.stdout.split() == ["CoachLinkAdvice"]
