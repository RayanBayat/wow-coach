"""The Setup page's checks and actions, as plain functions with no Qt in them.

Each check looks at the game folder and answers with a ``Check``: a status (all good, needs
attention, or a problem) and one friendly sentence. Each action (install the addon, create the
answers folder, change the game folder) does one job and answers with an ``ActionResult``.

Everything here reads or writes the disk, and the game may live on a slow hard disk. So the
page calls these from a background thread, never from the window's thread.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from wow_coach.advice.contract import ADVICE_ADDON_NAME
from wow_coach.config import save_wow_dir
from wow_coach.errors import WowCoachError
from wow_coach.setup import (
    ADDON_FOLDER,
    create_advice_folder,
    has_wtf,
    install_addon,
    installed_addon_version,
    is_link,
)
from wow_coach.web import FetchBytes

# The sentence shown after the addon was installed or updated.
RESTART_WOW_HINT: Final = "Done. Restart WoW (or /reload) to use the new version."


class Status(Enum):
    """How a checked item is doing."""

    OK = "ok"
    ATTENTION = "attention"  # works, but could be better (for example an old version)
    PROBLEM = "problem"  # does not work yet


@dataclass(frozen=True, slots=True)
class Check:
    """The result of one check: a status and one sentence for the player."""

    status: Status
    sentence: str


@dataclass(frozen=True, slots=True)
class ActionResult:
    """The result of one action: did it work, and what to tell the player."""

    ok: bool
    sentence: str


@dataclass(frozen=True, slots=True)
class SetupReport:
    """All checks together, taken at one moment."""

    game_folder: Check
    addon: Check
    answers_folder: Check
    addon_installed: str | None  # the installed version, None when not installed
    addon_is_link: bool  # a developer's linked copy: never replaced


def addons_folder(game_dir: Path) -> Path:
    """The game's ``Interface/AddOns`` folder."""
    return game_dir / "Interface" / "AddOns"


# ---- the checks --------------------------------------------------------------------------


def check_game_folder(game_dir: Path | None) -> Check:
    """Is there a game folder, and does it look like the real one?"""
    if game_dir is None:
        return Check(
            Status.PROBLEM,
            "I could not find your game. Choose the folder called _forever_ "
            "(it is inside your World of Warcraft folder).",
        )
    if not has_wtf(game_dir):
        return Check(
            Status.ATTENTION,
            f"{game_dir} has no WTF folder yet. Start the game once, "
            "or choose the folder called _forever_.",
        )
    return Check(Status.OK, str(game_dir))


def check_addon(game_dir: Path, app_version: str) -> tuple[Check, str | None, bool]:
    """Is CoachLink installed, and is it the version that matches this app?

    Returns the check, the installed version (None when missing) and whether the addon
    folder is a link (a developer's copy, which the app never replaces).
    """
    addon = addons_folder(game_dir) / ADDON_FOLDER
    if is_link(addon):
        return Check(Status.OK, "CoachLink is linked from a development copy."), None, True
    installed = installed_addon_version(addon)
    if installed is None:
        return (
            Check(Status.PROBLEM, "CoachLink is not installed yet. It lets the game talk to me."),
            None,
            False,
        )
    if installed != app_version:
        sentence = f"CoachLink {installed} is installed, and this app is {app_version}."
        return Check(Status.ATTENTION, sentence + " An update is ready."), installed, False
    return Check(Status.OK, f"CoachLink {installed} is installed and up to date."), installed, False


def check_answers_folder(game_dir: Path) -> Check:
    """Does the folder for the coach's answers (``CoachLink_Advice``) exist?"""
    folder = addons_folder(game_dir) / ADVICE_ADDON_NAME
    if folder.is_dir():
        return Check(Status.OK, "The answers folder is ready.")
    return Check(
        Status.PROBLEM,
        "The folder where I put my answers for the game does not exist yet.",
    )


def make_report(game_dir: Path | None, app_version: str) -> SetupReport:
    """Run every check. Call it from a background thread (it reads the game folder)."""
    folder_check = check_game_folder(game_dir)
    if game_dir is None or folder_check.status is not Status.OK:
        needs_folder = Check(Status.PROBLEM, "I need the game folder first.")
        return SetupReport(folder_check, needs_folder, needs_folder, None, False)
    addon, installed, is_link = check_addon(game_dir, app_version)
    return SetupReport(folder_check, addon, check_answers_folder(game_dir), installed, is_link)


# ---- the actions --------------------------------------------------------------------------


def change_game_folder(chosen: Path, config_file: Path) -> ActionResult:
    """Remember ``chosen`` as the game folder, the same way ``wow-coach setup`` does.

    The folder must hold a ``WTF`` folder, otherwise it is not the game.
    """
    if not has_wtf(chosen):
        return ActionResult(
            False,
            f"{chosen} does not look like the game folder (it has no WTF folder). "
            "Please choose the folder called _forever_.",
        )
    try:
        save_wow_dir(config_file, chosen)
    except OSError as error:
        return ActionResult(False, f"I could not save the folder: {error}. Please try again.")
    return ActionResult(True, "Saved. Restart WoW Coach so it watches this folder.")


def install_or_update_addon(game_dir: Path, app_version: str, download: FetchBytes) -> ActionResult:
    """Download CoachLink (the version that matches this app) and put it in the game.

    Installing while the game runs is fine: the game reads addon files only when it loads.
    The answers folder is created too, because the addon needs it.
    """
    addons = addons_folder(game_dir)
    if is_link(addons / ADDON_FOLDER):
        return ActionResult(True, "CoachLink is a linked development copy, so I left it alone.")
    try:
        install_addon(addons, app_version, download)
        create_advice_folder(addons)
    except (WowCoachError, ValueError) as error:
        return ActionResult(False, f"I could not install CoachLink: {error}. Please try again.")
    except OSError as error:
        return ActionResult(
            False, f"I could not write to the game folder: {error}. Is the folder choice right?"
        )
    return ActionResult(True, RESTART_WOW_HINT)


def create_answers_folder(game_dir: Path) -> ActionResult:
    """Create the folder for the coach's answers."""
    try:
        create_advice_folder(addons_folder(game_dir))
    except (WowCoachError, OSError, ValueError) as error:
        return ActionResult(False, f"I could not create it: {error}. Please try again.")
    return ActionResult(True, "Done. Restart WoW the first time so the game notices the folder.")
