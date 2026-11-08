"""Automatic checks for the rules wow-coach must never break.

Blizzard's addon policy and EULA forbid automation, memory reading and other third-party
tricks, and Blizzard is closing every door to combat advantage (see
docs/plans/coach-panel.md, section 3). These tests scan our own source code for the
calls and imports that would break those rules. They can't prove the code is fine, but
they stop the obvious mistakes before they are released. If one fails, don't loosen the
list: change the code, or talk about the rule first.
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
ADDON_FILES = sorted((ROOT / "addon" / "HeroBridge").glob("*.lua"))
PYTHON_FILES = sorted((ROOT / "src" / "wow_coach").rglob("*.py"))

# Game functions the addon must never CALL, and why. Hooking one by name (hooksecurefunc
# with the name as a string) is fine: that only watches what the player does.
FORBIDDEN_LUA_CALLS = {
    "SendChatMessage": "talks in chat for the player",
    "SendAddonMessage": "sends hidden messages to other players",
    "RunMacro": "runs a macro (automation)",
    "RunMacroText": "runs a macro (automation)",
    "CastSpell": "casts for the player",
    "CastSpellByName": "casts for the player",
    "CastSpellByID": "casts for the player",
    "UseAction": "presses an action button for the player",
    "UseContainerItem": "uses an item for the player",
    "PickupContainerItem": "moves items for the player",
    "TargetUnit": "targets for the player",
    "AssistUnit": "targets for the player",
    "FocusUnit": "targets for the player",
    "AttackTarget": "attacks for the player",
    "MoveForwardStart": "moves the character (a bot)",
    "TurnLeftStart": "moves the character (a bot)",
    "JumpOrAscendStart": "moves the character (a bot)",
    "AcceptQuest": "accepts quests for the player",
    "CompleteQuest": "completes quests for the player",
    "GetQuestReward": "completes quests for the player (we only hook it)",
    "BuyMerchantItem": "buys for the player (we only hook it)",
    "TakeInboxItem": "takes mail for the player (we only hook it)",
    "AutoLootMailItem": "takes mail for the player (we only hook it)",
    "AcceptResurrect": "acts for the player",
    "RepopMe": "releases the spirit for the player",
    "Logout": "logs out for the player (we only hook it)",
    "Quit": "quits for the player (we only hook it)",
    "SetBinding": "changes the player's key bindings",
    "SetBindingClick": "changes the player's key bindings",
    "LoadAddOn": "loading addons on a timer is a way around the sandbox",
    "PlaySoundFile": "sound files can be used as a signal channel out of the sandbox",
    "LoggingCombat": "turns on the combat log file (combat data)",
    "LoggingChat": "turns on the chat log file (a side channel)",
    "CopyToClipboard": "restricted; the copy window lets the player copy instead",
}

# Python imports that would mean pressing keys, reading the screen or reading the game's
# memory. None of them belongs in wow-coach.
FORBIDDEN_IMPORTS = {
    "pyautogui",
    "pynput",
    "keyboard",
    "mouse",
    "mss",
    "pyscreeze",
    "pywinauto",
    "win32api",
    "win32gui",
    "win32con",
    "pymem",
    "PIL.ImageGrab",
    "Xlib",
}

# Text that would mean using an AI or a website in a way its owner forbids.
FORBIDDEN_TEXT = {
    "ReadProcessMemory": "reads another program's memory",
    "WriteProcessMemory": "writes another program's memory",
    "SendInput": "presses keys",
    "keybd_event": "presses keys",
    "chatgpt.com/backend-api": "ChatGPT's web-session API (only the official sign-in is allowed)",
    "claude.ai/oauth": "a Claude.ai consumer login (Anthropic forbids it in other apps)",
    "accounts.google.com/o/oauth2": "a consumer Google login (Gemini forbids it in other apps)",
    "wowhead.com/forever/": "Wowhead's terms forbid automated access",
}


def _lua_code(path: Path) -> str:
    """The file's Lua with comments and strings blanked out, so only real code is checked."""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"--\[\[.*?\]\]", " ", text, flags=re.DOTALL)  # block comments
    text = re.sub(r"--[^\n]*", " ", text)  # line comments
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', text)  # string literals


@pytest.mark.parametrize("path", ADDON_FILES, ids=lambda path: path.name)
def test_the_addon_never_acts_for_the_player(path: Path) -> None:
    code = _lua_code(path)
    found = [
        f"{name} ({why})"
        for name, why in FORBIDDEN_LUA_CALLS.items()
        if re.search(rf"(?<![\w]){re.escape(name)}\s*\(", code)
    ]
    assert not found, f"{path.name} calls: {', '.join(found)}"


@pytest.mark.parametrize("path", ADDON_FILES, ids=lambda path: path.name)
def test_the_addon_clicks_nothing_and_never_polls_every_frame(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert not re.search(r":Click\s*\(", _lua_code(path)), f"{path.name} clicks a button"
    # An OnUpdate script runs every frame: bad for performance, and never needed here.
    assert '"OnUpdate"' not in text, f"{path.name} uses OnUpdate"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


@pytest.mark.parametrize("path", PYTHON_FILES, ids=lambda path: path.name)
def test_the_program_never_presses_keys_or_reads_the_screen(path: Path) -> None:
    imported = _imports(path)
    bad = sorted(
        name
        for name in imported
        for forbidden in FORBIDDEN_IMPORTS
        if name == forbidden or name.startswith(forbidden + ".")
    )
    assert not bad, f"{path.name} imports {bad}"


@pytest.mark.parametrize("path", [*ADDON_FILES, *PYTHON_FILES], ids=lambda path: path.name)
def test_no_forbidden_tricks_or_logins(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if path.name == Path(__file__).name:
        return  # this file names them on purpose
    found = [f"{word} ({why})" for word, why in FORBIDDEN_TEXT.items() if word in text]
    assert not found, f"{path.name} mentions: {', '.join(found)}"


def test_the_scan_sees_the_files() -> None:
    # A wrong path would make every test above pass without checking anything.
    assert {path.name for path in ADDON_FILES} >= {"HeroBridge.lua", "HeroBridgePanel.lua"}
    assert len(PYTHON_FILES) > 10


def test_the_lua_scan_finds_a_forbidden_call(tmp_path: Path) -> None:
    sample = tmp_path / "sample.lua"
    lines = [
        '-- SendChatMessage("in a comment is fine")',
        'local t = "RunMacro(x)"',
        'CastSpellByName("x")',
    ]
    sample.write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = _lua_code(sample)
    assert re.search(r"(?<![\w])CastSpellByName\s*\(", code)
    assert not re.search(r"(?<![\w])SendChatMessage\s*\(", code)
    assert not re.search(r"(?<![\w])RunMacro\s*\(", code)


def _uses_a_shell(path: Path) -> list[int]:
    """Lines that call something with shell=True (text could then run as a command)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "shell"
        and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is False)
    ]


@pytest.mark.parametrize("path", PYTHON_FILES, ids=lambda path: path.name)
def test_no_program_is_ever_run_through_a_shell(path: Path) -> None:
    # Notifications pass AI text to system programs. As a list of
    # arguments that text is only text; through a shell it could become a command.
    lines = _uses_a_shell(path)
    assert not lines, f"{path.name} uses shell=True on line(s) {lines}"
    text = path.read_text(encoding="utf-8")
    assert "os.system(" not in text and "os.popen(" not in text, f"{path.name} runs a shell"
