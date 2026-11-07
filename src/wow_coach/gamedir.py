"""Find the World of Warcraft: Forever folder (the one that contains ``WTF/``).

We look in three places, in this order, and the first hit wins:

1. the ``--wow-dir`` option (you typed it, so you meant it),
2. the ``WOW_COACH_WOW_DIR`` environment variable,
3. the places the game is normally installed on your operating system.

The list of "normal places" is a function argument, so tests never depend on the
computer they run on.
"""

import os
import string
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from wow_coach.errors import GameFolderNotFound

ENV_VARIABLE = "WOW_COACH_WOW_DIR"
FIX_HINT = (
    f"Fix: pass the folder with --wow-dir PATH, or set the {ENV_VARIABLE} environment "
    "variable. It is the folder that contains the WTF folder."
)

_PRODUCT_FOLDER = "World of Warcraft/_forever_"
_WINDOWS_PROGRAM_FOLDERS = ("Program Files (x86)", "Program Files")


@dataclass(frozen=True)
class GameFolder:
    """The game folder we settled on, and how we found it (shown by ``wow-coach check``)."""

    path: Path
    how_found: str


def _existing_windows_drives() -> set[str]:
    """Drive names like ``"C:"`` that exist right now (Windows only is meaningful)."""
    return {f"{letter}:" for letter in string.ascii_uppercase if Path(f"{letter}:/").exists()}


def default_candidates(
    *,
    platform: str | None = None,
    home: Path | None = None,
    existing_drives: Callable[[], set[str]] = _existing_windows_drives,
) -> list[Path]:
    """Where the game is usually installed, most likely first.

    Args:
        platform: ``sys.platform`` value to pretend to be on (default: the real one).
        home: The user's home folder (default: the real one).
        existing_drives: Returns the Windows drive letters that exist. Only called on Windows.
    """
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else home
    if platform == "win32":
        # C: is where Battle.net installs by default; other letters only if the drive exists.
        drives = ["C:", *sorted(drive for drive in existing_drives() if drive != "C:")]
        return [
            Path(f"{drive}/{program_folder}/{_PRODUCT_FOLDER}")
            for drive in drives
            if drive >= "C:"  # floppy drives A: and B: are never the game
            for program_folder in _WINDOWS_PROGRAM_FOLDERS
        ]
    if platform == "darwin":
        return [Path(f"/Applications/{_PRODUCT_FOLDER}")]
    # Linux: Battle.net under Lutris/Wine-style prefixes.
    wine_part = f"drive_c/Program Files (x86)/{_PRODUCT_FOLDER}"
    return [home / "Games/battlenet" / wine_part, home / ".wine" / wine_part]


def _must_be_a_folder(path: Path, where: str) -> Path:
    if not path.is_dir():
        raise GameFolderNotFound(
            f"{where} points to {str(path)!r}, but that folder does not exist."
        )
    return path


def resolve_game_folder(
    flag: Path | None,
    *,
    environ: Mapping[str, str] | None = None,
    candidates: Sequence[Path] | None = None,
) -> GameFolder:
    """Pick the game folder: flag, then environment variable, then auto-detect.

    Args:
        flag: The ``--wow-dir`` value, or None.
        environ: Environment variables (default: the real ones).
        candidates: Folders to auto-detect (default: ``default_candidates()``).

    Raises:
        GameFolderNotFound: If a given folder does not exist, or nothing was found.
    """
    environ = os.environ if environ is None else environ
    if flag is not None:
        return GameFolder(_must_be_a_folder(flag, "--wow-dir"), "the --wow-dir option")
    from_env = environ.get(ENV_VARIABLE, "").strip()
    if from_env:
        path = _must_be_a_folder(Path(from_env).expanduser(), f"The {ENV_VARIABLE} variable")
        return GameFolder(path, f"the {ENV_VARIABLE} environment variable")
    tried = list(default_candidates() if candidates is None else candidates)
    for candidate in tried:
        if (candidate / "WTF").is_dir():
            return GameFolder(candidate, "auto-detected in a common install location")
    tried_text = "\n".join(f"  - {candidate}" for candidate in tried) or "  (no places to try)"
    raise GameFolderNotFound(
        f"Could not find the World of Warcraft: Forever folder. I looked in:\n{tried_text}\n"
        f"{FIX_HINT}"
    )
