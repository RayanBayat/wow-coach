"""``wow-coach check``: answer "why isn't it working?" in plain language.

It walks through the same steps the coach needs (game folder, save file, characters)
and, at the first thing that is wrong, says what to do about it.
"""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TextIO

from wow_coach.config import config_path
from wow_coach.errors import CoachDataMissing, ConfigUnreadable, GameFolderNotFound, WowCoachError
from wow_coach.gamedir import resolve_game_folder
from wow_coach.notes import journals_folder, notes_path
from wow_coach.report import format_age
from wow_coach.savedvars import Character, find_saved_variables, load_characters

type Say = Callable[[str], None]

NO_SAVE_HELP = (
    "No save file yet: start WoW with the HeroBridge addon enabled and type /coach "
    "(the game writes the file when you type /coach, type /reload, or log out)."
)
ADDON_MISSING_HELP = (
    "The HeroBridge addon is not installed in {addons}. Download HeroBridge-<version>.zip "
    "from https://github.com/RayanBayat/wow-coach/releases/latest, unzip it into that "
    "folder (so it holds HeroBridge/HeroBridge.toc), then restart WoW completely."
)


def _character_line(character: Character, now: float) -> str:
    snap = character.snapshot
    saved_at = snap.get("savedAt")
    age = format_age(now - saved_at) if isinstance(saved_at, (int, float)) else "at an unknown time"
    return (
        f"  - {character.key}: level {snap.get('level', '?')} {snap.get('class', '?')}, "
        f"{snap.get('zone', 'unknown zone')}, saved {age}"
    )


def _check_save_file(game_folder: Path, now: float, say: Say) -> bool:
    """Look at the save file and its characters. Returns True when all is well."""
    try:
        save_file = find_saved_variables(game_folder)
    except CoachDataMissing:
        say(NO_SAVE_HELP)
        addons = game_folder / "Interface" / "AddOns"
        if not (addons / "HeroBridge").is_dir():
            say(ADDON_MISSING_HELP.format(addons=addons))
        return False
    say(f"Save file: {save_file}")
    try:
        characters = load_characters(save_file)
        saved_ago = format_age(now - save_file.stat().st_mtime)
    except (WowCoachError, OSError) as error:
        say(f"The save file could not be read: {error}")
        say("Type /reload in game to write it again; if it keeps failing, update wow-coach.")
        return False
    say(f"  last changed {saved_ago}")
    if not characters:
        say("The save file has no characters yet. Type /coach in game while playing.")
        return False
    say("Characters:")
    for character in characters.values():
        say(_character_line(character, now))
    return True


def _say_journals(folder: Path, say: Say) -> None:
    """List the character journals that exist (one file per character)."""
    try:
        names = sorted(path.stem for path in folder.glob("*.md"))
    except OSError:
        names = []
    if names:
        say(f"Character journals in {folder}: {', '.join(names)}")
    else:
        say(f"Character journals: none yet (the coach creates one per character in {folder})")


def run_check(
    wow_dir_flag: Path | None,
    *,
    environ: Mapping[str, str],
    candidates: Sequence[Path] | None,
    now: float,
    out: TextIO,
    closing_line: bool = True,
) -> int:
    """Print the troubleshooting report and return the exit code (0 fine, 1 a problem).

    ``closing_line=False`` leaves out the final "Everything looks good" / "Fix the problem"
    line, for callers (like ``wow-coach setup``) that explain the result in their own words.
    """

    def say(text: str = "") -> None:
        print(text, file=out)

    try:
        found = resolve_game_folder(
            wow_dir_flag,
            environ=environ,
            candidates=candidates,
            config_file=config_path(environ=environ),
        )
    except (GameFolderNotFound, ConfigUnreadable) as error:
        say(str(error))
        return 1
    say(f"Game folder: {found.path}")
    say(f"  found via {found.how_found}")
    all_well = _check_save_file(found.path, now, say)
    notes = notes_path(environ=environ)
    say(f"Player notes file: {notes} ({'exists' if notes.is_file() else 'not created yet'})")
    _say_journals(journals_folder(environ=environ), say)
    if closing_line:
        say()
        say("Everything looks good." if all_well else "Fix the problem above, then run this again.")
    return 0 if all_well else 1
