"""The coach's memory: plain Markdown files the AI reads and writes between sessions.

Some AI apps (like Claude Desktop) cannot write files themselves, so the MCP server
offers tools that do it for them. There are two kinds of file:

* **Player notes** (``coach-notes.md``): about the person, shared by all their characters.
  Preferences such as "wants exact click steps" or "does not use Questie".
* **Character journals** (``characters/<Name-Realm>.md``): one per character. Choices
  (spec, professions), goals and plans, a progress log and open advice.

Where the files live:

* Player notes: env ``WOW_COACH_NOTES_FILE`` if set, otherwise your per-user data folder:
  * Windows: ``%LOCALAPPDATA%\\wow-coach\\coach-notes.md``
  * macOS: ``~/Library/Application Support/wow-coach/coach-notes.md``
  * Linux: ``$XDG_DATA_HOME/wow-coach/coach-notes.md`` (default ``~/.local/share/...``)
* Journals: in a ``characters`` folder next to the player notes file.

These rules are small, so we write them here instead of adding the ``platformdirs``
package as a dependency.
"""

import re
from collections.abc import Mapping
from pathlib import Path

from wow_coach.datafolder import data_folder
from wow_coach.errors import NotesTooLarge

NOTES_FILE_VARIABLE = "WOW_COACH_NOTES_FILE"
MAX_NOTES_BYTES = 100 * 1024
_FILE = "coach-notes.md"
_JOURNAL_FOLDER = "characters"

PLAYER_NOTES_MISSING = (
    "There are no player notes yet. When you learn how the player likes to be coached "
    "(detail level, click-by-click steps, Questie, solo or group), write it down with the "
    "save_player_notes tool."
)

# Characters that Windows, macOS or Linux do not allow in a file name, plus control characters.
_UNSAFE_FILE_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def notes_path(
    *,
    environ: Mapping[str, str],
    platform: str | None = None,
    home: Path | None = None,
) -> Path:
    """Where the notebook file lives on this computer.

    Args:
        environ: Environment variables (pass ``os.environ``).
        platform: ``sys.platform`` value to pretend to be on (default: the real one).
        home: The user's home folder (default: the real one).
    """
    explicit = environ.get(NOTES_FILE_VARIABLE, "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return data_folder(environ=environ, platform=platform, home=home) / _FILE


def journals_folder(
    *,
    environ: Mapping[str, str],
    platform: str | None = None,
    home: Path | None = None,
) -> Path:
    """The folder that holds one journal per character."""
    return notes_path(environ=environ, platform=platform, home=home).parent / _JOURNAL_FOLDER


def safe_file_name(text: str) -> str:
    """Turn text into a file name that is allowed on Windows, macOS and Linux.

    Forbidden characters become ``_`` (spaces stay). Windows also refuses names that end
    in a dot or a space, so those are trimmed.
    """
    cleaned = _UNSAFE_FILE_CHARACTERS.sub("_", text).strip(" .")
    return cleaned or "character"


def journal_path(
    character_key: str,
    *,
    environ: Mapping[str, str],
    platform: str | None = None,
    home: Path | None = None,
) -> Path:
    """Where the journal of ``character_key`` (``Name-Realm``) lives."""
    folder = journals_folder(environ=environ, platform=platform, home=home)
    return folder / f"{safe_file_name(character_key)}.md"


def journal_missing_message(character_key: str) -> str:
    """What to tell the AI when a character has no journal yet."""
    return (
        f"There is no journal for {character_key} yet. Ask the player for this "
        "character's goal, then create the journal with save_coach_notes."
    )


def read_notes(path: Path, *, missing_message: str = PLAYER_NOTES_MISSING) -> str:
    """Return the saved text, or ``missing_message`` when the file does not exist yet."""
    if not path.is_file():
        return missing_message
    return path.read_text(encoding="utf-8")


def save_notes(path: Path, text: str, *, what: str = "player notes") -> str:
    """Replace the file with ``text`` and return a confirmation naming it.

    Args:
        path: The file to write (its folders are created).
        text: The complete new content.
        what: Words for the confirmation, for example ``"player notes"``.

    Raises:
        NotesTooLarge: If the text is bigger than 100 KB.
    """
    size = len(text.encode("utf-8"))
    if size > MAX_NOTES_BYTES:
        raise NotesTooLarge(
            f"The {what} are {size} bytes, over the 100 KB limit ({MAX_NOTES_BYTES} bytes). "
            "Shorten them (keep what matters) and save again."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return f"Saved {size} bytes of {what} to {path}."


def _is_filled_in(bullet_text: str) -> bool:
    """False for an empty bullet or one still holding the template's ``<placeholder>``."""
    return bool(bullet_text) and re.search(r"<[^<>]+>", bullet_text) is None


def journal_goal(path: Path) -> str | None:
    """The first goal bullet under ``## Goals`` in a journal, or None.

    Returns None when the file is missing or unreadable, has no Goals section, or the
    bullets are still the empty template.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    in_goals = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            in_goals = stripped.lstrip("#").strip().lower() == "goals"
        elif in_goals and stripped[:2] in ("- ", "* "):
            goal = stripped[2:].strip()
            if _is_filled_in(goal):
                return goal
    return None
