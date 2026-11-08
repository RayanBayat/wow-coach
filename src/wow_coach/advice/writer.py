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
import tempfile
from pathlib import Path

from wow_coach.advice.contract import (
    ADVICE_ADDON_NAME,
    ADVICE_FILE_NAME,
    ADVICE_TOC_NAME,
    AdviceFile,
)
from wow_coach.advice.serialize import advice_to_lua
from wow_coach.errors import WowCoachError

DEFAULT_INTERFACE = "16001"
_INTERFACE_LINE = re.compile(r"^\s*##\s*Interface\s*:\s*([0-9][0-9, ]*?)\s*$", re.MULTILINE)
_INTERFACE_OK = re.compile(r"[0-9]+(, ?[0-9]+)*")


class UnsafeAdvicePath(WowCoachError):  # noqa: N818
    """A path was refused because writing there could leave the data addon's folder."""


def interface_from_coachlink(addons_dir: Path) -> str:
    """Read ``## Interface:`` from ``CoachLink.toc`` so our .toc is never "out of date"."""
    toc = addons_dir / "CoachLink" / "CoachLink.toc"
    try:
        match = _INTERFACE_LINE.search(toc.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return DEFAULT_INTERFACE
    return match.group(1) if match else DEFAULT_INTERFACE


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


def _write_atomically(target: Path, text: str) -> None:
    """Write ``text`` to ``target`` so readers see the old file or the new one, never half."""
    handle, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(handle, "wb") as temp_file:
            temp_file.write(text.encode("utf-8"))
            temp_file.flush()
            os.fsync(temp_file.fileno())
        Path(temp_name).replace(target)  # os.replace: atomic on Linux, macOS and Windows
    except BaseException:
        with contextlib.suppress(OSError):
            Path(temp_name).unlink()
        raise


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
    if not toc.is_file() or toc.read_text(encoding="utf-8", errors="replace") != text:
        _write_atomically(toc, text)
    return folder


def write_advice(addons_dir: Path, advice: AdviceFile, *, interface: str) -> Path:
    """Write ``advice`` as ``Advice.lua`` (installing the folder if needed); return its path.

    The text is built and checked first, so a refused or too-large advice changes nothing.
    """
    text = advice_to_lua(advice)
    folder = install_advice_addon(addons_dir, interface=interface)
    target = _safe_file(folder, ADVICE_FILE_NAME)
    _write_atomically(target, text)
    return target
