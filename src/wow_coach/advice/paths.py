"""Where the Coach panel's files are inside the game folder."""

from pathlib import Path

from wow_coach.advice.contract import ADVICE_ADDON_NAME, ADVICE_FILE_NAME


def addons_folder(wow_dir: Path) -> Path:
    """The game's ``Interface/AddOns`` folder."""
    return wow_dir / "Interface" / "AddOns"


def advice_file_path(wow_dir: Path) -> Path:
    """Where wow-coach writes the Coach panel's answers (the CoachLink_Advice addon)."""
    return addons_folder(wow_dir) / ADVICE_ADDON_NAME / ADVICE_FILE_NAME
