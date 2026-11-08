"""Where wow-coach keeps its own files (the notebook and the saved settings).

* Windows: ``%LOCALAPPDATA%\\wow-coach``
* macOS: ``~/Library/Application Support/wow-coach``
* Linux: ``$XDG_DATA_HOME/wow-coach`` (default ``~/.local/share/wow-coach``)

These rules are small, so we write them here instead of adding the ``platformdirs``
package as a dependency.
"""

import sys
from collections.abc import Mapping
from pathlib import Path

_FOLDER = "wow-coach"
# Set this to use another folder (any system). Tests set it, so they never touch real files.
ENV_DATA_DIR = "WOW_COACH_DATA_DIR"


def data_folder(
    *,
    environ: Mapping[str, str],
    platform: str | None = None,
    home: Path | None = None,
) -> Path:
    """The per-user folder for wow-coach's own files on this computer.

    Args:
        environ: Environment variables (pass ``os.environ``).
        platform: ``sys.platform`` value to pretend to be on (default: the real one).
        home: The user's home folder (default: the real one).
    """
    override = environ.get(ENV_DATA_DIR, "").strip()
    if override:
        return Path(override).expanduser()
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else home
    if platform == "win32":
        base = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    return base / _FOLDER
