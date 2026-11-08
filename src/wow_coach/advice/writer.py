"""Write the ``CoachLink_Advice`` data addon into the game's AddOns folder, safely.

Safety rules (tested):

* Everything is written inside ``<AddOns>/CoachLink_Advice/`` and nowhere else.
* That folder and the files in it must not be symbolic links (or Windows junctions), so a
  link can never send our write somewhere else. ``<AddOns>`` itself may hold linked addons.
* ``Advice.lua`` is replaced atomically: the new text goes to a temporary file in the same
  folder, then ``os.replace`` swaps it in. The game never sees half a file, and a failure
  leaves the old file as it was.
"""

import contextlib
import importlib.metadata
import os
import re
import stat
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from wow_coach.advice.contract import (
    ADVICE_ADDON_NAME,
    ADVICE_FILE_NAME,
    ADVICE_TOC_NAME,
    AdviceFile,
)
from wow_coach.advice.reader import read_advice_file
from wow_coach.advice.safefile import read_plain_text
from wow_coach.advice.serialize import advice_to_lua
from wow_coach.errors import WowCoachError

DEFAULT_INTERFACE = "16001"
_INTERFACE_LINE = re.compile(r"^\s*##\s*Interface\s*:(.*)$", re.MULTILINE)
# One or more build numbers such as 16001 or "11507,50503". Anything odder is not trusted.
_INTERFACE_OK = re.compile(r"[0-9]{4,7}(,[0-9]{4,7})*")
MAX_TOC_BYTES = 64_000

# Retrying os.replace: on Windows, a virus scanner or the game may hold the file for a moment.
REPLACE_TRIES = 5
REPLACE_PAUSE_SECONDS = 0.1

# The lock file keeps two wow-coach programs from reading and rewriting at the same time.
LOCK_NAME = ".lock"
LOCK_WAIT_SECONDS = 2.0
LOCK_STALE_SECONDS = 30.0
LOCK_POLL_SECONDS = 0.05


class UnsafeAdvicePath(WowCoachError):  # noqa: N818
    """A path was refused because writing there could leave the data addon's folder."""


def interface_from_coachlink(addons_dir: Path) -> str:
    """Read ``## Interface:`` from ``CoachLink.toc`` so our .toc is never "out of date"."""
    text = read_plain_text(addons_dir / "CoachLink" / "CoachLink.toc", MAX_TOC_BYTES)
    match = None if text is None else _INTERFACE_LINE.search(text)
    value = match.group(1).strip() if match else ""
    return value if _INTERFACE_OK.fullmatch(value) else DEFAULT_INTERFACE


def _toc_text(interface: str) -> str:
    try:
        version = importlib.metadata.version("wow-coach")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    return (
        f"## Interface: {interface}\n"
        "## Title: CoachLink Advice\n"
        "## Notes: Answers from the wow-coach program for the CoachLink Coach panel. "
        "Data only, no code.\n"
        f"## Version: {version}\n"
        "\n"
        f"{ADVICE_FILE_NAME}\n"
    )


# ---- path safety ---------------------------------------------------------------------


def _refuse_link(path: Path) -> None:
    if path.is_symlink() or path.is_junction():
        raise UnsafeAdvicePath(f"Refusing to write through a link: {path}")


def _safe_folder(addons_dir: Path) -> Path:
    """Return the data addon's folder, making it if needed, after the safety checks."""
    if not addons_dir.is_dir():
        raise UnsafeAdvicePath(f"The AddOns folder does not exist: {addons_dir}")
    folder = addons_dir / ADVICE_ADDON_NAME
    _refuse_link(folder)
    if folder.exists() and not folder.is_dir():
        raise UnsafeAdvicePath(f"{folder} is not a folder.")
    folder.mkdir(exist_ok=True)
    if folder.resolve().parent != addons_dir.resolve():
        raise UnsafeAdvicePath(f"{folder} does not sit directly inside {addons_dir}.")
    return folder


def _safe_file(folder: Path, name: str) -> Path:
    """Return ``folder/name`` after checking that it is a plain file path inside ``folder``."""
    path = folder / name
    _refuse_link(path)
    if path.exists() and not path.is_file():
        raise UnsafeAdvicePath(f"{path} is not a plain file.")
    if path.resolve().parent != folder.resolve():
        raise UnsafeAdvicePath(f"{path} leaves the {ADVICE_ADDON_NAME} folder.")
    return path


# ---- atomic write ----------------------------------------------------------------------


def _replace_with_retry(source: str, target: Path) -> None:
    """``os.replace`` that tries again a few times if the system says "permission denied"."""
    for attempt in range(1, REPLACE_TRIES + 1):
        try:
            Path(source).replace(target)  # os.replace: atomic on Linux, macOS and Windows
            return
        except PermissionError:
            if attempt == REPLACE_TRIES:
                raise
            time.sleep(REPLACE_PAUSE_SECONDS)


def _write_atomically(target: Path, text: str) -> None:
    """Write ``text`` to ``target`` so readers see the old file or the new one, never half."""
    handle, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(handle, "wb") as temp_file:
            temp_file.write(text.encode("utf-8"))
            temp_file.flush()
            os.fsync(temp_file.fileno())
        _replace_with_retry(temp_name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(temp_name).unlink()
        raise


# ---- lock ----------------------------------------------------------------------------------


class AdviceBusy(WowCoachError):  # noqa: N818
    """Another wow-coach program was writing the advice file for too long."""


def _lock_is_stale(lock: Path) -> bool:
    """A lock older than ``LOCK_STALE_SECONDS`` was left behind by a program that crashed."""
    try:
        return time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS
    except OSError:
        return False


@contextlib.contextmanager
def _locked(folder: Path) -> Iterator[None]:
    """Hold ``folder/.lock`` while the block runs.

    The lock is a file made with O_CREAT | O_EXCL, which succeeds for only one program at
    a time on every operating system. We retry for a couple of seconds, take over a stale
    lock, and always remove our lock at the end.
    """
    lock = folder / LOCK_NAME
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
            break
        except FileExistsError:
            if _lock_is_stale(lock):
                with contextlib.suppress(OSError):
                    lock.unlink()
            elif time.monotonic() > deadline:
                raise AdviceBusy(
                    "Another wow-coach is writing the Coach panel file; try again."
                ) from None
            else:
                time.sleep(LOCK_POLL_SECONDS)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


# ---- public -------------------------------------------------------------------------------


def install_advice_addon(addons_dir: Path, *, interface: str) -> Path:
    """Create or refresh ``CoachLink_Advice/CoachLink_Advice.toc``; return the folder.

    The .toc has no ``SavedVariables`` line: this addon is data only.

    Raises:
        UnsafeAdvicePath: If the AddOns folder is missing or a path is a link.
        ValueError: If ``interface`` is not a number such as ``16001``.
    """
    if not _INTERFACE_OK.fullmatch(interface):
        raise ValueError(f"Not a valid Interface number: {interface!r}")
    folder = _safe_folder(addons_dir)
    toc = _safe_file(folder, ADVICE_TOC_NAME)
    text = _toc_text(interface)
    if read_plain_text(toc, MAX_TOC_BYTES) != text:
        _write_atomically(toc, text)
    return folder


def _write_checked(folder: Path, text: str) -> Path:
    """Write ``Advice.lua`` and make sure the result is still a plain file in our folder.

    Threat model: whoever can swap our folder for a link while we write is the same user
    who owns the game folder, and could simply write ``Advice.lua`` themselves. So we do not
    guard against that with directory handles; we check before and after, which catches
    mistakes and accidents.
    """
    target = _safe_file(folder, ADVICE_FILE_NAME)
    _write_atomically(target, text)
    target = _safe_file(folder, ADVICE_FILE_NAME)
    if not stat.S_ISREG(target.lstat().st_mode):
        raise UnsafeAdvicePath(f"{target} is not a plain file after writing.")
    return target


def write_advice(addons_dir: Path, advice: AdviceFile, *, interface: str) -> Path:
    """Write ``advice`` as ``Advice.lua`` (installing the folder if needed); return its path.

    The text is built and checked first, so a refused or too-large advice changes nothing.
    """
    text = advice_to_lua(advice)
    folder = install_advice_addon(addons_dir, interface=interface)
    return _write_checked(folder, text)


def update_advice(
    addons_dir: Path,
    change: Callable[[AdviceFile], AdviceFile],
    *,
    interface: str,
    now: int,
) -> Path:
    """Read the current file, apply ``change`` and write the result, all under the lock.

    A missing or damaged ``Advice.lua`` counts as an empty file, so it never blocks an
    update: the damaged one is simply replaced.
    """
    folder = install_advice_addon(addons_dir, interface=interface)
    with _locked(folder):
        current = read_advice_file(folder / ADVICE_FILE_NAME) or AdviceFile(written_at=now)
        text = advice_to_lua(change(current))
        return _write_checked(folder, text)
