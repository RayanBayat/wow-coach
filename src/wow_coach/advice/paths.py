"""Where the Coach panel's files are inside the game folder."""

from dataclasses import dataclass
from pathlib import Path

from wow_coach.advice.contract import (
    ADVICE_ADDON_NAME,
    ADVICE_FILE_NAME,
    ADVICE_GLOBAL,
    LEGACY_ADVICE_ADDON_NAME,
    LEGACY_ADVICE_GLOBAL,
)


@dataclass(frozen=True)
class AdviceAddon:
    """The names of the small data addon that carries answers into the game."""

    folder_name: str  # inside Interface/AddOns
    global_name: str  # the one variable Advice.lua sets
    title: str  # shown in the game's addon list


CURRENT_ADVICE_ADDON = AdviceAddon(ADVICE_ADDON_NAME, ADVICE_GLOBAL, "HeroBridge Advice")
LEGACY_ADVICE_ADDON = AdviceAddon(
    LEGACY_ADVICE_ADDON_NAME, LEGACY_ADVICE_GLOBAL, "CoachLink Advice"
)


def addons_folder(wow_dir: Path) -> Path:
    """The game's ``Interface/AddOns`` folder."""
    return wow_dir / "Interface" / "AddOns"


def advice_addon_for(addons_dir: Path) -> AdviceAddon:
    """Which answers addon to use: the old one only if just the old CoachLink is installed.

    Whoever has HeroBridge (or nothing yet) gets HeroBridge_Advice. This keeps answers
    working for a player who has not switched to HeroBridge yet.
    """
    old_addon_only = (addons_dir / "CoachLink").is_dir() and not (
        addons_dir / "HeroBridge"
    ).is_dir()
    return LEGACY_ADVICE_ADDON if old_addon_only else CURRENT_ADVICE_ADDON


def advice_file_path(wow_dir: Path) -> Path:
    """Where wow-coach writes the Coach panel's answers (``Advice.lua``)."""
    addons = addons_folder(wow_dir)
    return addons / advice_addon_for(addons).folder_name / ADVICE_FILE_NAME
