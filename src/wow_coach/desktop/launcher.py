"""``wow-coach-app``: starts the desktop app directly (the program that shortcuts point to).

Why a second program: ``wow-coach.exe`` is a console program. When a Windows shortcut starts
it, a black console window stays open for as long as the coach runs, and closing that window
kills the coach. ``wow-coach-app`` is declared as a "GUI script" in ``pyproject.toml``, which
Windows starts without a console. On Linux it does the same job as ``wow-coach app``.

A Windows GUI program has no console at all, so ``sys.stdout`` and ``sys.stderr`` can be
``None``. Every message goes through ``_say``, and the streams are replaced before
``argparse`` can try to print to them.

It also works as ``python -m wow_coach.desktop.launcher``, which is how the app restarts itself.
"""

import argparse
import importlib.util
import io
import sys
from collections.abc import Sequence
from pathlib import Path

from wow_coach.errors import WowCoachError
from wow_coach.install_hint import install_command

DESKTOP_MISSING = f"WoW Coach needs its desktop extra. Install it with: {install_command()}"


def desktop_installed() -> bool:
    """True when PySide6 (Qt for Python, the desktop app's toolkit) can be imported."""
    return importlib.util.find_spec("PySide6") is not None


def _make_streams_safe() -> None:
    """Give a missing stdout or stderr a harmless stand-in, so nothing can crash on printing."""
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()


def _say(text: str) -> None:
    """Print a message to the error stream, if there is one."""
    if sys.stderr is not None:
        sys.stderr.write(text + "\n")


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="wow-coach-app", description="Open the WoW Coach desktop app."
    )
    parser.add_argument(
        "--wow-dir", type=Path, metavar="PATH", help="the game folder that contains WTF"
    )
    parser.add_argument(
        "--hidden",
        action="store_true",
        help="start in the tray without showing the window (the login shortcut uses it)",
    )
    parser.add_argument(
        "--toggle-overlay",
        action="store_true",
        help="show or hide the coach overlay on top of the game (starts the app if it is not "
        "running). Bind this command to a key in your system's keyboard settings.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Open the desktop app. Returns the exit code (0 means success)."""
    _make_streams_safe()
    try:
        arguments = _parse(argv)
    except SystemExit as stop:  # argparse exits by itself on --help or a wrong option
        return stop.code if isinstance(stop.code, int) else 1
    if not desktop_installed():
        _say(DESKTOP_MISSING)
        return 1
    # Imported only here: Qt is an optional extra, and this module must load without it so
    # that the missing-extra message above can be shown.
    from wow_coach.desktop import run  # noqa: PLC0415 - optional extra, see above

    try:
        return run.run_desktop(
            wow_dir_flag=arguments.wow_dir,
            start_hidden=arguments.hidden,
            toggle_overlay=arguments.toggle_overlay,
        )
    except (WowCoachError, OSError) as error:
        _say(f"wow-coach-app: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
