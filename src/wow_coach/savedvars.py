"""Find and load the HeroBridge data file that the in-game addon saves.

WoW writes the file to ``<wow_dir>/WTF/Account/<account>/SavedVariables/HeroBridge.lua``.
There is one folder per game account, so we look in all of them and use the file that
was changed most recently.

HeroBridge was called CoachLink before 0.11.0. A player who has not switched yet only has
the old ``CoachLink.lua`` (variable ``CoachLinkDB``, same layout). We keep reading it, so
nothing stops working before the switch. When both files sit side by side, each character
comes from whichever file saved it last.
"""

from dataclasses import dataclass, field
from pathlib import Path

from wow_coach.errors import CoachDataMissing, UnsupportedFormat, WowCoachError
from wow_coach.lua_table import LuaValue, parse_saved_variables

SUPPORTED_FORMAT_VERSION = 1
_FILE_NAME = "HeroBridge.lua"
_VARIABLE_NAME = "HeroBridgeDB"
# The names before 0.11.0. Only read, never written (see setup.py for the move).
LEGACY_FILE_NAME = "CoachLink.lua"
LEGACY_VARIABLE_NAME = "CoachLinkDB"
_VARIABLE_BY_FILE = {_FILE_NAME: _VARIABLE_NAME, LEGACY_FILE_NAME: LEGACY_VARIABLE_NAME}


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
    """Return the newest save file (``HeroBridge.lua`` or the old ``CoachLink.lua``).

    Raises:
        CoachDataMissing: If no such file exists yet.
    """
    candidates: list[Path] = []
    for file_name in _VARIABLE_BY_FILE:
        candidates.extend(wow_dir.glob(f"WTF/Account/*/SavedVariables/{file_name}"))
    if not candidates:
        raise CoachDataMissing(
            f"No {_FILE_NAME} found under {wow_dir}. Install the HeroBridge addon, "
            "restart WoW completely, then type /coach in game (or log out) so it saves."
        )
    # On a tie the new name wins (False sorts before True, and max keeps the first of equals).
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name == _FILE_NAME))


def load_characters(path: Path) -> dict[str, Character]:
    """Parse the file and return its characters keyed by ``"Name-Realm"``.

    If the other-named save file (HeroBridge.lua / CoachLink.lua) is in the same folder,
    its characters are merged in, the newer ``savedAt`` winning for each character.

    Raises:
        LuaParseError: If the file is not valid Lua data.
        UnsupportedFormat: If ``formatVersion`` is not one we understand.
    """
    characters = _load_one_file(path)
    sibling = _sibling_save_file(path)
    if sibling is not None:
        try:
            other = _load_one_file(sibling)
        except (WowCoachError, OSError):
            return characters  # a damaged second file must not hide the one that works
        characters = _newer_per_character(characters, other, prefer_first_on_tie=_is_new_name(path))
    return characters


def _is_new_name(path: Path) -> bool:
    return path.name != LEGACY_FILE_NAME


def _sibling_save_file(path: Path) -> Path | None:
    """The save file with the other name, in the same folder, if it exists."""
    if path.name == _FILE_NAME:
        other = path.with_name(LEGACY_FILE_NAME)
    elif path.name == LEGACY_FILE_NAME:
        other = path.with_name(_FILE_NAME)
    else:
        return None
    return other if other.is_file() else None


def _saved_at(character: Character) -> float:
    value = character.snapshot.get("savedAt")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _newer_per_character(
    first: dict[str, Character], second: dict[str, Character], prefer_first_on_tie: bool
) -> dict[str, Character]:
    """Merge two character maps; for a character in both, keep the later ``savedAt``.

    On equal times the HeroBridge file wins. ``prefer_first_on_tie`` says whether ``first``
    is the HeroBridge one.
    """
    merged = dict(second)
    for key, mine in first.items():
        theirs = second.get(key)
        if theirs is None or _saved_at(mine) > _saved_at(theirs):
            merged[key] = mine
        elif _saved_at(mine) == _saved_at(theirs) and prefer_first_on_tie:
            merged[key] = mine
    return merged


def _load_one_file(path: Path) -> dict[str, Character]:
    """Read one save file; the variable name inside depends on which addon wrote it."""
    variable = _VARIABLE_BY_FILE.get(path.name, _VARIABLE_NAME)
    text = path.read_text(encoding="utf-8")
    database = parse_saved_variables(text).get(variable)
    if not isinstance(database, dict):
        raise UnsupportedFormat(f"{path} does not contain a {variable} table.")
    version = database.get("formatVersion")
    if version != SUPPORTED_FORMAT_VERSION:
        raise UnsupportedFormat(
            f"HeroBridge data has formatVersion {version!r}, but this reader only "
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
