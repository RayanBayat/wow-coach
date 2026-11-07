"""The coach's notebook: a plain Markdown file the AI reads and writes between sessions.

Some AI apps (like Claude Desktop) cannot write files themselves, so the MCP server
offers two tools that do it for them. Where the file lives:

* env ``WOW_COACH_NOTES_FILE`` if set, otherwise your per-user data folder:
* Windows: ``%LOCALAPPDATA%\\wow-coach\\coach-notes.md``
* macOS: ``~/Library/Application Support/wow-coach/coach-notes.md``
* Linux: ``$XDG_DATA_HOME/wow-coach/coach-notes.md`` (default ``~/.local/share/...``)

These rules are small, so we write them here instead of adding the ``platformdirs``
package as a dependency.
"""

import sys
from collections.abc import Mapping
from pathlib import Path

from wow_coach.errors import NotesTooLarge

NOTES_FILE_VARIABLE = "WOW_COACH_NOTES_FILE"
MAX_NOTES_BYTES = 100 * 1024
_FOLDER = "wow-coach"
_FILE = "coach-notes.md"


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
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else home
    if platform == "win32":
        base = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    return base / _FOLDER / _FILE


def read_notes(path: Path) -> str:
    """Return the saved notes, or a friendly message when there are none yet."""
    if not path.is_file():
        return (
            "There are no coach notes yet. After you coach the player, write what matters "
            "(goals, lessons, what to do next) with the save_coach_notes tool."
        )
    return path.read_text(encoding="utf-8")


def save_notes(path: Path, text: str) -> str:
    """Replace the notebook with ``text`` and return a confirmation naming the file.

    Raises:
        NotesTooLarge: If the text is bigger than 100 KB.
    """
    size = len(text.encode("utf-8"))
    if size > MAX_NOTES_BYTES:
        raise NotesTooLarge(
            f"The notes are {size} bytes, over the 100 KB limit ({MAX_NOTES_BYTES} bytes). "
            "Shorten them (keep what matters) and save again."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return f"Saved {size} bytes of coach notes to {path}."
