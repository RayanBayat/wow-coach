"""Is the game running right now? A best-effort answer, used before moving the save file.

WoW rewrites its save files when it exits. If we copied a save while the game was still
open, the game could overwrite our work (or the copy would miss the last minutes of
play). So we ask "is the game running?" first and refuse to move anything if it is.

How it looks, with no extra libraries (no ``psutil``):

* Linux: the names in ``/proc/<number>/comm``. Under Wine or Proton the game shows up as
  ``Wow.exe`` or similar, so the same list works.
* Windows: ``tasklist``, a program that ships with Windows.
* macOS: ``ps``.

It is a best effort. If the process list cannot be read, we answer "not running" instead of
blocking the player forever; the Setup page tells the player to close WoW first anyway.
"""

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path, PurePath

# Program names the game uses (lower case). Kept as an exact list so that unrelated programs
# whose name starts with "wow" (like ``wow-coach`` itself) are never mistaken for the game.
GAME_PROGRAM_NAMES = frozenset(
    {
        "wow",
        "wow.exe",
        "wow-64",
        "wow-64.exe",
        "wowb.exe",
        "wowt.exe",
        "wowclassic",
        "wowclassic.exe",
        "wowclassicb.exe",
        "wowclassict.exe",
    }
)

_COMMAND_TIMEOUT_SECONDS = 10

type ListProgramNames = Callable[[], list[str]]


def _names_from_proc() -> list[str]:
    """Linux: every running program's short name, from ``/proc/<pid>/comm``."""
    names: list[str] = []
    for comm in Path("/proc").glob("[0-9]*/comm"):
        try:
            names.append(comm.read_text(encoding="utf-8", errors="replace").strip())
        except OSError:
            continue  # the program ended while we looked; that is fine
    return names


def _run_and_get_lines(command: list[str]) -> list[str]:
    """Run a fixed command (never built from user text) and return its output lines."""
    done = subprocess.run(  # noqa: S603 - fixed argument list, no shell
        command,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=_COMMAND_TIMEOUT_SECONDS,
        check=False,
    )
    return done.stdout.splitlines()


def _names_from_tasklist() -> list[str]:
    """Windows: ``tasklist /FO CSV /NH`` prints ``"Wow.exe","1234",...`` per program."""
    lines = _run_and_get_lines(["tasklist", "/FO", "CSV", "/NH"])
    return [line.split('","')[0].strip('"') for line in lines if line.startswith('"')]


def _names_from_ps() -> list[str]:
    """macOS: ``ps -A -o comm=`` prints each program's path; keep the file name."""
    return [PurePath(line.strip()).name for line in _run_and_get_lines(["ps", "-A", "-o", "comm="])]


def running_program_names() -> list[str]:
    """The names of the programs running on this computer."""
    if sys.platform == "win32":
        return _names_from_tasklist()
    if sys.platform == "darwin":
        return _names_from_ps()
    return _names_from_proc()


def is_game_running(list_names: ListProgramNames = running_program_names) -> bool:
    """True when a WoW program is running. ``list_names`` is replaced by a fake in tests."""
    try:
        names = list_names()
    except OSError, subprocess.SubprocessError:
        return False  # best effort: do not block the player when we cannot tell
    return any(name.lower() in GAME_PROGRAM_NAMES for name in names)
