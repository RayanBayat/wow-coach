"""Move a player from the old CoachLink addon to HeroBridge without losing anything.

HeroBridge was called CoachLink before 0.11.0. A player who updates gets:

1. HeroBridge installed (done by ``setup.install_addon``, as always).
2. Their saved characters copied: ``CoachLink.lua`` becomes ``HeroBridge.lua``, with only
   the name of the one top-level variable changed (``CoachLinkDB`` -> ``HeroBridgeDB``).
   The old file is kept as it is.
3. Their old answers copied from ``CoachLink_Advice`` to ``HeroBridge_Advice``.
4. The old ``CoachLink`` and ``CoachLink_Advice`` folders removed (never a link: a
   developer's linked copy is left alone and we say so).

The game rewrites its save files when it exits, so nothing here runs while the game is
running (see ``game_running.py``).
"""

import contextlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from wow_coach.advice.contract import ADVICE_FILE_NAME
from wow_coach.advice.reader import read_advice_file
from wow_coach.advice.writer import interface_from_herobridge, write_advice
from wow_coach.errors import WowCoachError
from wow_coach.lua_table import parse_saved_variables
from wow_coach.savedvars import LEGACY_FILE_NAME, LEGACY_VARIABLE_NAME

OLD_ADDON_FOLDERS = ("CoachLink", "CoachLink_Advice")
NEW_FILE_NAME = "HeroBridge.lua"
NEW_VARIABLE_NAME = "HeroBridgeDB"

GAME_RUNNING_SENTENCE = (
    "WoW is still running. Close WoW completely (use the game menu: Exit Game), "
    "then try again. The game saves your character when it closes, and I must not "
    "move the save while it does."
)

# Only the very first assignment at the start of a line is renamed, nothing else in the file.
_ASSIGNMENT = re.compile(rf"^{LEGACY_VARIABLE_NAME}(?=\s*=)", re.MULTILINE)


@dataclass
class MoveReport:
    """What the move did, as plain sentences for the player."""

    notes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def old_save_files(game_dir: Path) -> list[Path]:
    """Every account's ``CoachLink.lua`` that has no ``HeroBridge.lua`` next to it yet."""
    found = game_dir.glob(f"WTF/Account/*/SavedVariables/{LEGACY_FILE_NAME}")
    return sorted(path for path in found if not os.path.lexists(path.with_name(NEW_FILE_NAME)))


def old_folders_to_remove(addons: Path) -> list[Path]:
    """The old addon folders that exist and may be removed (links are never touched)."""
    return [
        addons / name
        for name in OLD_ADDON_FOLDERS
        if (addons / name).is_dir() and not _is_link(addons / name)
    ]


def upgrade_pending(game_dir: Path) -> bool:
    """True when there is something to move or remove (the Setup card says "Update")."""
    addons = game_dir / "Interface" / "AddOns"
    return bool(old_save_files(game_dir) or old_folders_to_remove(addons))


# ---- step 2: the saved characters ---------------------------------------------------------


def renamed_save_text(old_text: str) -> str:
    """The old file's text with ``CoachLinkDB =`` changed to ``HeroBridgeDB =``.

    Raises:
        WowCoachError: If the result does not hold exactly the same data under the new
            name. Checked by reading both texts with the Lua-table reader.
    """
    new_text, count = _ASSIGNMENT.subn(NEW_VARIABLE_NAME, old_text, count=1)
    if count != 1:
        raise WowCoachError(f"the file has no top-level {LEGACY_VARIABLE_NAME} assignment")
    old_data = parse_saved_variables(old_text)
    if parse_saved_variables(new_text) != {
        **{k: v for k, v in old_data.items() if k != LEGACY_VARIABLE_NAME},
        NEW_VARIABLE_NAME: old_data.get(LEGACY_VARIABLE_NAME),
    }:
        raise WowCoachError("the renamed save did not read back the same")
    return new_text


def _write_new_file_atomically(target: Path, text: str) -> None:
    """Write next to the target, then swap in, so the game never sees half a file."""
    handle, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(handle, "wb") as temp_file:
            temp_file.write(text.encode("utf-8"))  # bytes: keeps the file's own line endings
            temp_file.flush()
            os.fsync(temp_file.fileno())
        Path(temp_name).replace(target)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(temp_name).unlink()
        raise


def copy_saves_to_herobridge(game_dir: Path, is_running: bool) -> MoveReport:
    """For each account, copy ``CoachLink.lua`` to ``HeroBridge.lua`` (if that is missing).

    The old file is left exactly as it is. Refuses, changing nothing, while the game runs.
    """
    report = MoveReport()
    if is_running:
        report.problems.append(GAME_RUNNING_SENTENCE)
        return report
    for old_file in old_save_files(game_dir):
        account = old_file.parent.parent.name
        try:
            text = old_file.read_bytes().decode("utf-8")
            _write_new_file_atomically(old_file.with_name(NEW_FILE_NAME), renamed_save_text(text))
        except (WowCoachError, OSError, UnicodeDecodeError, RecursionError) as error:
            report.problems.append(
                f"Could not copy your saved character for account {account}: {error}"
            )
        else:
            report.notes.append(f"Copied your saved characters for account {account}.")
    return report


# ---- step 3 and 4: the answers, and the old folders ---------------------------------------


def _copy_old_answers(addons: Path) -> None:
    """Carry the old answers over, unless the new addon already has an answers file."""
    old_file = addons / "CoachLink_Advice" / ADVICE_FILE_NAME
    if (
        _is_link(addons / "CoachLink_Advice")
        or (addons / "HeroBridge_Advice" / ADVICE_FILE_NAME).exists()
    ):
        return
    advice = read_advice_file(old_file)
    if advice is not None:
        write_advice(addons, advice, interface=interface_from_herobridge(addons))


def remove_old_addon_folders(addons: Path) -> MoveReport:
    """Delete ``CoachLink`` and ``CoachLink_Advice``, except links (those are left alone)."""
    report = MoveReport()
    try:
        _copy_old_answers(addons)
    except (WowCoachError, OSError) as error:
        report.notes.append(f"Your old answers could not be carried over ({error}); that is fine.")
    for name in OLD_ADDON_FOLDERS:
        folder = addons / name
        if _is_link(folder):
            report.notes.append(f"{folder} is a link (a developer's copy), so I left it alone.")
        elif folder.is_dir():
            try:
                shutil.rmtree(folder)
            except OSError as error:
                report.problems.append(f"Could not remove the old folder {folder}: {error}")
            else:
                report.notes.append(f"Removed the old folder {folder}.")
    return report


def finish_upgrade(game_dir: Path, is_running: bool) -> MoveReport:
    """After HeroBridge is installed: copy the saves, then remove the old addon folders.

    The old folders stay if the save copy failed, so the player never ends up with less.
    """
    report = copy_saves_to_herobridge(game_dir, is_running)
    if not report.ok:
        return report
    removal = remove_old_addon_folders(game_dir / "Interface" / "AddOns")
    report.notes.extend(removal.notes)
    report.problems.extend(removal.problems)
    return report
