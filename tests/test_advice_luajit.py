"""Cross-check with the real Lua engine: can the game load what Python writes?

Skipped when ``luajit`` is not installed. WoW uses Lua 5.1, which LuaJIT matches.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from wow_coach.advice.contract import AdviceAnswer, AdviceFile, CharacterAdvice, CoachPlan
from wow_coach.advice.limits import limit_advice
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
local advice = HeroBridgeAdvice
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

# For the hypothesis test: print the bytes of the text fields as hex, so anything can be
# compared exactly. A missing field prints "-".
HEX_SCRIPT = """
dofile(arg[1])
local answer = HeroBridgeAdvice.characters["Testchar-Testrealm"].answers[1]
local function hex(value)
  if value == nil then return "-" end
  return (value:gsub(".", function(c) return string.format("%02x", c:byte()) end))
end
print(hex(answer.title))
print(hex(answer.text))
print(hex(answer.steps and answer.steps[1]))
print(hex(answer.warnings and answer.warnings[1]))
print(hex(answer.question))
print(answer.answeredAt)
"""


def run_luajit(script_text: str, lua_file: Path, tmp_path: Path) -> list[str]:
    script = tmp_path / "check.lua"
    script.write_text(script_text, encoding="utf-8")
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

    lines = run_luajit(SCRIPT, lua_file, tmp_path)

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
    """Load a rich real file (answers, plan, nasty text) and look for new globals."""
    answer = AdviceAnswer(
        1, "Coach", "Title", steps=(NASTY,), text=NASTY, warnings=(NASTY,), question_id="1-1"
    )
    plan = CoachPlan(goal=NASTY, steps=(NASTY,), updated_at=3)
    advice = AdviceFile(5, {KEY: CharacterAdvice(1, (answer,), plan, ("1-1",))})
    lua_file = tmp_path / "Advice.lua"
    lua_file.write_text(advice_to_lua(advice), encoding="utf-8")
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
    assert done.stdout.split() == ["HeroBridgeAdvice"]


def hex_of(text: str | None) -> str:
    """What the HEX_SCRIPT prints for a text field (the file holds ``||`` for every ``|``)."""
    return "-" if text is None else text.replace("|", "||").encode("utf-8").hex()


# Any text, with the awkward characters made likely.
tricky_text = st.text(
    alphabet=st.one_of(
        st.sampled_from(
            ['"', "\\", "\n", "\r", "|", "\x00", "\x1f", "\x7f", "'", "]", "\U0001f600"]
        ),
        st.characters(blacklist_categories=("Cs",)),
    ),
    min_size=1,
    max_size=60,
)


@settings(max_examples=60, deadline=None)
@given(
    title=tricky_text,
    text=tricky_text,
    step=tricky_text,
    warning=tricky_text,
    question=tricky_text,
)
def test_luajit_reads_back_exactly_what_python_wrote(
    tmp_path_factory: pytest.TempPathFactory,
    title: str,
    text: str,
    step: str,
    warning: str,
    question: str,
) -> None:
    folder = tmp_path_factory.mktemp("luajit")
    answer = AdviceAnswer(
        7, "S", title, (step,), text, (warning,), question_id="1-1", question=question, asked_at=1
    )
    advice = AdviceFile(9, {KEY: CharacterAdvice(1, (answer,))})
    lua_file = folder / "Advice.lua"
    lua_file.write_text(advice_to_lua(advice), encoding="utf-8")

    cut = limit_advice(advice).characters[KEY].answers[0]
    lines = run_luajit(HEX_SCRIPT, lua_file, folder)

    assert lines == [
        hex_of(cut.title),
        hex_of(cut.text or None),
        hex_of(cut.steps[0] if cut.steps else None),
        hex_of(cut.warnings[0] if cut.warnings else None),
        hex_of(cut.question),
        "7",
    ]
