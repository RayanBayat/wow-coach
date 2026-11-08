"""Find and load the CoachLink data file that the in-game addon saves.

WoW writes the file to ``<wow_dir>/WTF/Account/<account>/SavedVariables/CoachLink.lua``.
There is one folder per game account, so we look in all of them and use the file that
was changed most recently.
"""

from dataclasses import dataclass, field
from pathlib import Path

from wow_coach.errors import CoachDataMissing, UnsupportedFormat
from wow_coach.lua_table import LuaValue, parse_saved_variables

SUPPORTED_FORMAT_VERSION = 1
_FILE_NAME = "CoachLink.lua"


@dataclass(frozen=True)
class Character:
    """Everything the addon saved for one character."""

    key: str  # "Name-Realm"
    snapshot: dict[str | int, LuaValue]
    history: list[LuaValue]  # oldest first, as the addon writes it
    # Progress points, oldest first. Empty for saves made before addon 0.5.0.
    progress: list[LuaValue] = field(default_factory=list)
    # Questions typed in the Coach panel, oldest first (addon 0.8.0+). See advice/contract.py.
    questions: list[LuaValue] = field(default_factory=list)


def find_saved_variables(wow_dir: Path) -> Path:
    """Return the newest ``CoachLink.lua`` under ``wow_dir``.

    Raises:
        CoachDataMissing: If no such file exists yet.
    """
    pattern = f"WTF/Account/*/SavedVariables/{_FILE_NAME}"
    candidates = list(wow_dir.glob(pattern))
    if not candidates:
        raise CoachDataMissing(
            f"No {_FILE_NAME} found under {wow_dir}. Install the CoachLink addon, "
            "restart WoW completely, then type /coach in game (or log out) so it saves."
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_characters(path: Path) -> dict[str, Character]:
    """Parse the file and return its characters keyed by ``"Name-Realm"``.

    Raises:
        LuaParseError: If the file is not valid Lua data.
        UnsupportedFormat: If ``formatVersion`` is not one we understand.
    """
    text = path.read_text(encoding="utf-8")
    database = parse_saved_variables(text).get("CoachLinkDB")
    if not isinstance(database, dict):
        raise UnsupportedFormat(f"{path} does not contain a CoachLinkDB table.")
    version = database.get("formatVersion")
    if version != SUPPORTED_FORMAT_VERSION:
        raise UnsupportedFormat(
            f"CoachLink data has formatVersion {version!r}, but this reader only "
            f"understands version {SUPPORTED_FORMAT_VERSION}. Update wow-coach or the addon."
        )
    raw_characters = database.get("characters")
    if not isinstance(raw_characters, dict):
        return {}
    return {str(key): _build_character(str(key), value) for key, value in raw_characters.items()}


def _build_character(key: str, raw: LuaValue) -> Character:
    """Turn one raw table into a Character, tolerating missing pieces."""
    table = raw if isinstance(raw, dict) else {}
    snapshot = table.get("snapshot")
    history = table.get("history")
    progress = table.get("progress")
    questions = table.get("questions")
    return Character(
        key=key,
        snapshot=snapshot if isinstance(snapshot, dict) else {},
        history=history if isinstance(history, list) else [],
        progress=progress if isinstance(progress, list) else [],
        questions=questions if isinstance(questions, list) else [],
    )
