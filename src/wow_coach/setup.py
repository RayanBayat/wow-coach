"""``wow-coach setup``: get everything ready in a few guided steps.

The steps, each ending in a clear OK or PROBLEM line:

1. Find the game folder (and remember it).
2. Install or update the CoachLink addon.
3. Create the coach's notebook.
4. Optionally install the Claude Code agent and skill.
5. Run the same checks as ``wow-coach check``.

It is safe to run again: it only changes what is missing or out of date.

Everything that touches the network, the keyboard or the home folder is passed in as an
argument, so the tests can use fake ones. We only ever write to the game's
``Interface/AddOns/CoachLink`` folder, wow-coach's own data folder, and (only when you ask)
``~/.claude``.
"""

import io
import re
import shutil
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TextIO

from wow_coach.assets import AGENT_PATH, SKILL_PATH, notebook_template, read_asset
from wow_coach.check import run_check
from wow_coach.config import config_path, save_wow_dir
from wow_coach.errors import (
    ConfigUnreadable,
    GameFolderNotFound,
    LookupFailed,
    SetupFailed,
)
from wow_coach.gamedir import resolve_game_folder
from wow_coach.notes import notes_path
from wow_coach.web import FetchBytes

RELEASE_URL = "https://github.com/RayanBayat/wow-coach/releases/download/v{v}/CoachLink-{v}.zip"
ADDON_FOLDER = "CoachLink"
_STAGING = ".CoachLink-new"
_OLD_COPY = ".CoachLink-old"
_PASTE_TRIES = 3
_VERSION_LINE = re.compile(r"^##\s*Version:\s*(\S+)", re.MULTILINE)

type Say = Callable[[str], None]
type Ask = Callable[[str], str]


@dataclass(frozen=True)
class SetupChoices:
    """What the player asked for on the command line."""

    wow_dir_flag: Path | None
    assume_yes: bool  # --yes: ask nothing, take the defaults
    claude_code: bool  # --claude-code: install the agent and skill
    skip_addon: bool  # --skip-addon: leave the addon alone


@dataclass(frozen=True)
class SetupWorld:
    """The outside world, replaced by fakes in tests."""

    environ: Mapping[str, str]
    candidates: Sequence[Path] | None
    home: Path
    package_version: str
    download: FetchBytes
    ask: Ask
    interactive: bool  # False when there is nobody to answer questions
    now: float
    out: TextIO


# ---------------------------------------------------------------------------
# Step 1: the game folder
# ---------------------------------------------------------------------------


def _clean_pasted_path(text: str) -> Path:
    """Turn what the player pasted into a path (Windows "Copy as path" adds quotes)."""
    return Path(text.strip().strip("\"'")).expanduser()


def _has_wtf(folder: Path) -> bool:
    return (folder / "WTF").is_dir()


def _ask_for_folder(ask: Ask, say: Say) -> Path | None:
    say("  I could not find the game by myself. I need the folder called _forever_.")
    say("  It is inside your World of Warcraft folder, for example:")
    say("    Windows: C:\\Program Files (x86)\\World of Warcraft\\_forever_")
    say("    macOS:   /Applications/World of Warcraft/_forever_")
    say("  Tip: in the Battle.net app, click the gear next to Play, then Show in Explorer.")
    for _ in range(_PASTE_TRIES):
        answer = ask("  Paste the path of the _forever_ folder here (or press Enter to stop): ")
        if not answer.strip():
            return None
        folder = _clean_pasted_path(answer)
        if _has_wtf(folder):
            return folder
        say(f"  That folder has no WTF folder inside it: {folder}")
        say("  Make sure it is _forever_ itself, and that you started the game at least once.")
    return None


def _find_game_folder(choices: SetupChoices, world: SetupWorld, say: Say) -> Path | None:
    settings = config_path(environ=world.environ)
    try:
        found = resolve_game_folder(
            choices.wow_dir_flag,
            environ=world.environ,
            candidates=world.candidates,
            config_file=settings,
        )
    except GameFolderNotFound as error:
        if choices.wow_dir_flag is not None or not world.interactive or choices.assume_yes:
            say(f"  PROBLEM: {error}")
            return None
        folder = _ask_for_folder(world.ask, say)
        if folder is None:
            say("  PROBLEM: no game folder chosen. Run `wow-coach setup` again when you have it.")
            return None
        how = "the path you pasted"
    except ConfigUnreadable as error:
        say(f"  PROBLEM: {error}")
        return None
    else:
        folder, how = found.path, found.how_found
        if not _has_wtf(folder):
            say(f"  PROBLEM: {folder} has no WTF folder. Start the game once, then run setup.")
            return None
    save_wow_dir(settings, folder)
    say(f"  OK: game folder {folder} (found via {how}).")
    say(f"  OK: remembered it in {settings}, so you will not need to type it again.")
    return folder


# ---------------------------------------------------------------------------
# Step 2: the addon
# ---------------------------------------------------------------------------


def _installed_addon_version(addon: Path) -> str | None:
    toc = addon / f"{ADDON_FOLDER}.toc"
    if not toc.is_file():
        return None
    match = _VERSION_LINE.search(toc.read_text(encoding="utf-8", errors="replace"))
    return match.group(1) if match else None


def _is_safe_member(name: str) -> bool:
    """True when a zip entry stays inside ``CoachLink/`` (the zip-slip guard).

    A zip slip is a zip whose entry names like ``../../x`` write outside the folder
    you extract into.
    """
    portable = name.replace("\\", "/")
    path = PurePosixPath(portable)
    if portable.startswith("/") or re.match(r"^[A-Za-z]:", portable):
        return False
    if ".." in path.parts:
        return False
    return path.parts[:1] == (ADDON_FOLDER,)


def _extract_zip(data: bytes, staging: Path) -> None:
    """Unpack the addon zip into ``staging``, refusing anything unsafe.

    Raises:
        SetupFailed: If the file is not a zip, an entry is unsafe or the addon is missing.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise SetupFailed("the downloaded file is not a valid zip") from error
    with archive:
        names = archive.namelist()
        unsafe = [name for name in names if not _is_safe_member(name)]
        if unsafe:
            raise SetupFailed(f"the zip has an unsafe entry ({unsafe[0]!r}), so I did not use it")
        if f"{ADDON_FOLDER}/{ADDON_FOLDER}.toc" not in names:
            raise SetupFailed("the zip does not contain CoachLink/CoachLink.toc")
        for member in archive.infolist():
            target = staging / PurePosixPath(member.filename.replace("\\", "/"))
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))


def _swap_in(staged_addon: Path, addon: Path) -> None:
    """Put the new copy in place. The old copy is deleted only after the new one is there."""
    old_copy = addon.with_name(_OLD_COPY)
    if old_copy.exists():
        shutil.rmtree(old_copy)
    had_old = addon.exists()
    if had_old:
        addon.rename(old_copy)
    try:
        staged_addon.rename(addon)
    except OSError:
        if had_old:
            old_copy.rename(addon)  # put the working copy back
        raise
    if had_old:
        shutil.rmtree(old_copy)


def _install_addon(addons: Path, version: str, download: FetchBytes) -> None:
    addons.mkdir(parents=True, exist_ok=True)
    staging = addons / _STAGING
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        _extract_zip(download(RELEASE_URL.format(v=version)), staging)
        _swap_in(staging / ADDON_FOLDER, addons / ADDON_FOLDER)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _setup_addon(game: Path, world: SetupWorld, say: Say) -> bool:
    addons = game / "Interface" / "AddOns"
    addon = addons / ADDON_FOLDER
    if addon.is_symlink():
        say(f"  OK: {addon} is a link (a developer's copy). I left it alone.")
        return True
    version = world.package_version
    installed = _installed_addon_version(addon)
    if installed == version:
        say(f"  OK: CoachLink {version} is already installed in {addon}.")
        return True
    say(f"  Installing CoachLink {version} (installed now: {installed or 'nothing'}) ...")
    try:
        _install_addon(addons, version, world.download)
    except (LookupFailed, SetupFailed, OSError) as error:
        say(f"  PROBLEM: could not install the addon: {error}")
        say("  You can install it by hand: download the zip from")
        say("  https://github.com/RayanBayat/wow-coach/releases/latest and follow")
        say("  docs/install-the-addon.md (https://github.com/RayanBayat/wow-coach).")
        return False
    say(f"  OK: CoachLink {version} installed in {addon}.")
    say("  Now quit WoW completely (use the game menu: Exit Game), then start it again.")
    say("  The game only notices a new or updated addon after a full restart.")
    return True


# ---------------------------------------------------------------------------
# Step 3: the notebook
# ---------------------------------------------------------------------------


def _setup_notebook(world: SetupWorld, say: Say) -> bool:
    notebook = notes_path(environ=world.environ)
    if notebook.is_file():
        say(f"  OK: your notebook already exists ({notebook}). I did not touch it.")
        return True
    try:
        notebook.parent.mkdir(parents=True, exist_ok=True)
        notebook.write_text(notebook_template(), encoding="utf-8")
    except OSError as error:
        say(f"  PROBLEM: could not create the notebook {notebook}: {error}")
        return False
    say(f"  OK: created an empty notebook at {notebook}.")
    return True


# ---------------------------------------------------------------------------
# Step 4: the Claude Code agent and skill
# ---------------------------------------------------------------------------


def _wants_claude_code(choices: SetupChoices, world: SetupWorld, say: Say) -> bool:
    if choices.claude_code:
        return True
    claude_folder = world.home / ".claude"
    if choices.assume_yes or not world.interactive or not claude_folder.is_dir():
        say("  Skipped (add --claude-code to install the Claude Code agent and skill).")
        return False
    answer = world.ask("  Claude Code found. Install the wow-coach agent and skill? [Y/n] ")
    return answer.strip().lower() in ("", "y", "yes")


def _copy_claude_file(content: bytes, target: Path, say: Say) -> bool:
    """Copy one packaged file to ``target``; links are left alone, other files get a backup."""
    if target.is_symlink() or target.parent.is_symlink():
        say(f"  OK: {target} is a link (a developer's copy). I left it alone.")
        return True
    try:
        if target.is_file():
            if target.read_bytes() == content:
                say(f"  OK: {target} is already up to date.")
                return True
            backup = target.with_name(target.name + ".bak")
            shutil.copy2(target, backup)
            say(f"  A different file was there. Kept a copy as {backup}.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    except OSError as error:
        say(f"  PROBLEM: could not write {target}: {error}")
        return False
    say(f"  OK: installed {target}.")
    return True


def _setup_claude_code(choices: SetupChoices, world: SetupWorld, say: Say) -> bool | None:
    """Install the agent and skill. Returns None when skipped, else whether it worked."""
    if not _wants_claude_code(choices, world, say):
        return None
    claude_folder = world.home / ".claude"
    agent_ok = _copy_claude_file(
        read_asset(AGENT_PATH), claude_folder / "agents" / "wow-coach.md", say
    )
    skill_ok = _copy_claude_file(
        read_asset(SKILL_PATH), claude_folder / "skills" / "wow-coach" / "SKILL.md", say
    )
    return agent_ok and skill_ok


# ---------------------------------------------------------------------------
# The whole setup
# ---------------------------------------------------------------------------


def run_setup(choices: SetupChoices, world: SetupWorld) -> int:
    """Run all steps and return the exit code (0 when no step had a problem)."""

    def say(text: str = "") -> None:
        print(text, file=world.out)

    say("wow-coach setup: getting everything ready. Safe to run again at any time.")
    say()
    say("Step 1 of 5: find the game folder")
    game = _find_game_folder(choices, world, say)
    if game is None:
        say()
        say("Stopped: nothing else can be set up without the game folder.")
        return 1
    problems = 0

    say()
    say("Step 2 of 5: the CoachLink addon")
    if choices.skip_addon:
        say("  Skipped (--skip-addon).")
    elif not _setup_addon(game, world, say):
        problems += 1

    say()
    say("Step 3 of 5: your coach notebook")
    if not _setup_notebook(world, say):
        problems += 1

    say()
    say("Step 4 of 5: Claude Code agent and skill")
    claude_result = _setup_claude_code(choices, world, say)
    if claude_result is False:
        problems += 1

    say()
    say("Step 5 of 5: checking that the coach can see your game")
    check_code = run_check(
        choices.wow_dir_flag,
        environ=world.environ,
        candidates=world.candidates,
        now=world.now,
        out=world.out,
        closing_line=False,
    )
    if check_code != 0:
        # On a fresh install this is expected: the game writes the save file only after
        # the player logs in and types /coach. Say so, so it doesn't read like a failure.
        say("  The coach can't see your character yet. That is normal on a new install:")
        say("  start WoW, log in, and type /coach in the chat box.")

    say()
    if problems:
        say(f"Setup finished with {problems} problem(s). Read the PROBLEM lines above.")
    else:
        say("Setup finished. No problems.")
    say("Next step:")
    if claude_result is True:
        say("  Start your coach:  claude --agent wow-coach")
    else:
        say(
            "  Pick how to talk to your coach: https://github.com/RayanBayat/wow-coach#pick-your-way"
        )
        say("  (Claude Code: `wow-coach setup --claude-code`, then `claude --agent wow-coach`.)")
    return 1 if problems else 0
