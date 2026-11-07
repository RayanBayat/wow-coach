"""The player's saved settings: today just the game folder, remembered by ``wow-coach setup``.

The settings live in ``config.json`` inside the data folder (next to the coach notes), for
example ``{"wow_dir": "C:/Program Files (x86)/World of Warcraft/_forever_"}``. Set the
environment variable ``WOW_COACH_CONFIG_FILE`` to use another file (tests do).
"""

import json
from collections.abc import Mapping
from pathlib import Path

from wow_coach.datafolder import data_folder
from wow_coach.errors import ConfigUnreadable

CONFIG_FILE_VARIABLE = "WOW_COACH_CONFIG_FILE"
_FILE = "config.json"
_WOW_DIR_KEY = "wow_dir"


def config_path(
    *,
    environ: Mapping[str, str],
    platform: str | None = None,
    home: Path | None = None,
) -> Path:
    """Where ``config.json`` lives (see ``data_folder`` for the arguments)."""
    explicit = environ.get(CONFIG_FILE_VARIABLE, "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return data_folder(environ=environ, platform=platform, home=home) / _FILE


def _read_settings(path: Path) -> dict[str, object]:
    """All saved settings, or an empty dict when nothing was saved yet."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ConfigUnreadable(
            f"The settings file {path} is damaged ({error}). "
            "Run `wow-coach setup` again to rewrite it."
        ) from error
    if not isinstance(data, dict):
        raise ConfigUnreadable(
            f"The settings file {path} does not hold settings. "
            "Run `wow-coach setup` again to rewrite it."
        )
    return data


def load_saved_wow_dir(path: Path) -> Path | None:
    """The game folder saved earlier, or None if there is none.

    Raises:
        ConfigUnreadable: If the settings file exists but is damaged.
    """
    value = _read_settings(path).get(_WOW_DIR_KEY)
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser()
    return None


def save_wow_dir(path: Path, folder: Path) -> None:
    """Remember ``folder`` as the game folder, keeping any other saved settings."""
    settings = _read_settings(path)
    settings[_WOW_DIR_KEY] = str(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
