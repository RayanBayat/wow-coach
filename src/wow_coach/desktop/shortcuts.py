"""App-menu entry and "start when I log in" for the desktop app.

* Linux: a ``.desktop`` file (the standard "launcher" file) in the applications folder, the
  same file in the autostart folder, and the icon in the icon folder.
* Windows: ``.lnk`` shortcuts in the Start Menu and Startup folders. Windows has no plain-text
  format for them, so PowerShell's ``WScript.Shell`` object makes them. As in ``alerts.py``, no
  text is ever glued into the script: the script is fixed, and the paths travel in environment
  variables.
* macOS: not supported yet.

A shortcut remembers the program's exact path. If wow-coach was started from a temporary
place (the cache of ``uvx``), that path vanishes later and the shortcut would break. So in
that case nothing is written; the player is shown the command that installs a stable program.

Every function takes the folders it writes to as arguments, so tests use temporary folders.
"""

import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from wow_coach.alerts import Runner, default_runner
from wow_coach.desktop.icons import APP_ICON_SVG, save_app_ico
from wow_coach.install_hint import install_command

_log = logging.getLogger(__name__)

# The program the shortcuts start: the app's own "GUI script" (see ``launcher.py``). Unlike
# ``wow-coach``, on Windows it opens no console window, so closing a console cannot kill the
# coach. Linux uses the same program, so both systems behave the same.
PROGRAM_NAME: Final = "wow-coach-app"
DISPLAY_NAME: Final = "WoW Coach"
INSTALL_COMMAND: Final = install_command()  # pinned to the version that is running
UNSTABLE_SENTENCE: Final = (
    "WoW Coach was started from a temporary place, so a shortcut would stop working later. "
    "Install it once with this command, then open it again:"
)
UNSUPPORTED_SENTENCE: Final = "Shortcuts are not available on this system yet."

# The command that shows or hides the overlay in the running app (see ``single_instance.py``).
TOGGLE_OVERLAY_ARGUMENT: Final = "--toggle-overlay"

# Arguments added after the program's path (the menu entry needs none).
MENU_ARGUMENTS: Final[tuple[str, ...]] = ()
# At login the window stays in the tray, so it does not jump in front of the game.
AUTOSTART_ARGUMENTS: Final = ("--hidden",)

# Parts of a path that show a temporary program (the uv / uvx cache and similar), lowercase,
# written with "/" (paths are changed to that form before the check).
_TEMPORARY_MARKERS: Final = (
    "/.cache/uv/",
    "/appdata/local/uv/cache/",
    "/library/caches/uv/",
    "/archive-v0/",
    "/builds-v0/",
)

# Fixed PowerShell script: it only reads paths from these environment variables.
LINK_VARIABLE: Final = "WOW_COACH_LINK"
TARGET_VARIABLE: Final = "WOW_COACH_TARGET"
ARGUMENTS_VARIABLE: Final = "WOW_COACH_ARGUMENTS"
ICON_VARIABLE: Final = "WOW_COACH_ICON"
DESCRIPTION_VARIABLE: Final = "WOW_COACH_DESCRIPTION"
WINDOWS_LINK_SCRIPT: Final = (
    "$shell = New-Object -ComObject WScript.Shell; "
    f"$link = $shell.CreateShortcut($env:{LINK_VARIABLE}); "
    f"$link.TargetPath = $env:{TARGET_VARIABLE}; "
    f"$link.Arguments = $env:{ARGUMENTS_VARIABLE}; "
    f"$link.IconLocation = $env:{ICON_VARIABLE}; "
    f"$link.Description = $env:{DESCRIPTION_VARIABLE}; "
    "$link.Save()"
)
POWERSHELL_TIMEOUT_SECONDS: Final = 20


class ShortcutError(Exception):
    """A shortcut could not be made or removed. The message is a sentence for the player."""


@dataclass(frozen=True, slots=True)
class ShortcutFolders:
    """Where this computer keeps launchers. ``icon_file`` is where the app icon is written."""

    menu_dir: Path
    autostart_dir: Path
    icon_file: Path


@dataclass(frozen=True, slots=True)
class ShortcutState:
    """Which shortcuts exist right now."""

    in_menu: bool
    at_login: bool


# ---- where things go ----------------------------------------------------------------------


def is_supported(platform: str = sys.platform) -> bool:
    """True on Linux and Windows. macOS is not supported yet."""
    return platform.startswith("linux") or platform == "win32"


def default_folders(
    environ: Mapping[str, str] | None = None,
    platform: str = sys.platform,
    home: Path | None = None,
) -> ShortcutFolders | None:
    """The real launcher folders of this computer, or None where unsupported."""
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else home
    if platform.startswith("linux"):
        data_home = Path(environ.get("XDG_DATA_HOME") or home / ".local" / "share")
        config_home = Path(environ.get("XDG_CONFIG_HOME") or home / ".config")
        return ShortcutFolders(
            menu_dir=data_home / "applications",
            autostart_dir=config_home / "autostart",
            icon_file=data_home / "icons" / "hicolor" / "scalable" / "apps" / "wow-coach.svg",
        )
    if platform == "win32":
        roaming = Path(environ.get("APPDATA") or home / "AppData" / "Roaming")
        local = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        programs = roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        return ShortcutFolders(
            menu_dir=programs,
            autostart_dir=programs / "Startup",
            icon_file=local / "wow-coach" / "wow-coach.ico",
        )
    return None


def _entry_name(platform: str) -> str:
    """The file name of a launcher: ``wow-coach.desktop`` or ``WoW Coach.lnk``."""
    return "WoW Coach.lnk" if platform == "win32" else "wow-coach.desktop"


def current_state(folders: ShortcutFolders, platform: str = sys.platform) -> ShortcutState:
    """Which launchers exist (a quick disk look; call it from a background thread)."""
    name = _entry_name(platform)
    return ShortcutState(
        in_menu=(folders.menu_dir / name).is_file(),
        at_login=(folders.autostart_dir / name).is_file(),
    )


# ---- finding a stable program -------------------------------------------------------------


def is_temporary_program(path: Path, temp_roots: Sequence[Path] = ()) -> bool:
    """True when ``path`` is inside a cache or temporary folder, so it may vanish later."""
    for form in (path, path.resolve()):
        text = "/" + form.as_posix().lower().strip("/") + "/"
        if any(marker in text for marker in _TEMPORARY_MARKERS):
            return True
        if any(form.is_relative_to(root) for root in temp_roots):
            return True
    return False


def _program_file(folder: Path, platform: str) -> Path:
    """Where the app's program would be inside ``folder`` (Windows adds ``.exe``)."""
    return folder / (PROGRAM_NAME + (".exe" if platform == "win32" else ""))


def find_stable_program(
    *,
    which: Callable[[str], str | None] = shutil.which,
    executable: str | None = None,
    platform: str = sys.platform,
    temp_roots: Sequence[Path] | None = None,
) -> Path | None:
    """The absolute path of the app's program, or None when it is not stable.

    The program that belongs to the RUNNING environment wins: the script that sits next to
    ``sys.executable``. A ``wow-coach-app`` further along the PATH may be another install (an
    older one, or one without the ``desktop`` extra), so the PATH is only used when what it
    finds resolves to a script in this same environment. A path inside a cache or temporary
    folder gives None, because it may vanish later.
    """
    roots = [Path(tempfile.gettempdir())] if temp_roots is None else list(temp_roots)
    environment_folder = Path(sys.executable if executable is None else executable).parent
    own_script = _program_file(environment_folder, platform)
    candidates = [own_script]
    found = which(PROGRAM_NAME)
    if found and Path(found).resolve().parent == environment_folder.resolve():
        candidates.append(Path(found))
    for candidate in candidates:
        path = candidate.absolute()
        if path.is_file() and not is_temporary_program(path, roots):
            return path
    return None


def overlay_command(program: Path | None, platform: str = sys.platform) -> str:
    """The command a keyboard shortcut should run to show or hide the overlay.

    It uses the same stable program the shortcuts use. When there is none (the app was
    started from a temporary place) the bare program name is shown instead, which works once
    the player has installed the program (the Setup page says so).
    """
    parts = [PROGRAM_NAME if program is None else str(program), TOGGLE_OVERLAY_ARGUMENT]
    return subprocess.list2cmdline(parts) if platform == "win32" else shlex.join(parts)


# ---- Linux: .desktop files ----------------------------------------------------------------


def quote_exec_argument(argument: str) -> str:
    """Quote one program argument for a ``.desktop`` file's ``Exec=`` line.

    The Desktop Entry specification: an argument with spaces or special characters goes in
    double quotes, and inside them ``"`` ``` ` ``` ``$`` and ``\\`` get a backslash. A
    percent sign is written ``%%`` (``%f`` and friends are placeholders).
    """
    if any(ord(char) < 32 for char in argument):
        raise ValueError("a program argument cannot contain line breaks or control characters")
    argument = argument.replace("%", "%%")
    if not re.search(r"[\s\"'\\><~|&;$*?#()`]", argument):
        return argument
    return '"' + re.sub(r'(["`$\\])', r"\\\1", argument) + '"'


def _desktop_value(text: str) -> str:
    """Escape a value the way .desktop files want: every backslash is doubled."""
    return text.replace("\\", "\\\\")


def desktop_entry_text(program: Path, arguments: Sequence[str], icon_file: Path) -> str:
    """The content of a ``.desktop`` launcher for ``program`` with ``arguments``."""
    command = " ".join(quote_exec_argument(part) for part in (str(program), *arguments))
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={DISPLAY_NAME}",
        "Comment=Your coach for World of Warcraft: Forever",
        f"Exec={_desktop_value(command)}",
        f"Icon={_desktop_value(str(icon_file))}",
        "Terminal=false",
        "Categories=Game;Utility;",
        "StartupWMClass=wow-coach",
    ]
    return "\n".join(lines) + "\n"


def _write_text_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---- Windows: .lnk files through PowerShell -----------------------------------------------


def find_powershell(
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> str | None:
    """Windows PowerShell: the copy in System32 if it exists, else whatever ``which`` finds."""
    environ = os.environ if environ is None else environ
    root = environ.get("SYSTEMROOT")
    if root:
        system_copy = Path(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        if system_copy.exists():
            return str(system_copy)
    return which("powershell") or None


def windows_link_command(
    powershell: str,
    link_file: Path,
    program: Path,
    arguments: Sequence[str],
    icon_file: Path,
) -> tuple[list[str], dict[str, str]]:
    """The PowerShell command (and its environment variables) that makes one ``.lnk``.

    Nothing is run here. Only fixed text is in the command; every path is in the variables.
    """
    command = [powershell, "-NoProfile", "-NonInteractive", "-Command", WINDOWS_LINK_SCRIPT]
    env = {
        LINK_VARIABLE: str(link_file),
        TARGET_VARIABLE: str(program),
        ARGUMENTS_VARIABLE: " ".join(arguments),
        ICON_VARIABLE: str(icon_file),
        DESCRIPTION_VARIABLE: "Your coach for World of Warcraft: Forever",
    }
    return command, env


# ---- the one object the Setup page talks to -----------------------------------------------


class ShortcutMaker:
    """Adds and removes the menu entry and the login entry, on Linux or Windows."""

    def __init__(
        self,
        folders: ShortcutFolders,
        *,
        program: Path | None,
        platform: str = sys.platform,
        environ: Mapping[str, str] | None = None,
        runner: Runner = default_runner,
        write_ico: Callable[[Path], bool] = save_app_ico,
    ) -> None:
        """Create the maker.

        Args:
            folders: Where the launchers and the icon are written.
            program: The stable ``wow-coach`` program, or None when there is none.
            platform: ``sys.platform`` value to act for (tests pass their own).
            environ: Environment variables (only used to find PowerShell).
            runner: Runs a program and returns its exit code (tests pass a fake).
            write_ico: Writes the app icon as a Windows ``.ico`` file; True on success.
        """
        self._folders = folders
        self._program = program
        self._platform = platform
        self._environ = os.environ if environ is None else environ
        self._runner = runner
        self._write_ico = write_ico

    @property
    def needs_stable_program(self) -> bool:
        """True when no stable program was found, so no shortcut can be made."""
        return self._program is None

    def state(self) -> ShortcutState:
        """Which shortcuts exist now."""
        return current_state(self._folders, self._platform)

    def set_in_menu(self, wanted: bool) -> None:
        """Add or remove the app-menu entry."""
        self._set(self._folders.menu_dir, MENU_ARGUMENTS, wanted)

    def set_at_login(self, wanted: bool) -> None:
        """Add or remove the "start when I log in" entry."""
        self._set(self._folders.autostart_dir, AUTOSTART_ARGUMENTS, wanted)

    def _set(self, folder: Path, arguments: Sequence[str], wanted: bool) -> None:
        target = folder / _entry_name(self._platform)
        try:
            if not wanted:
                target.unlink(missing_ok=True)
            elif self._program is None:
                raise ShortcutError(f"{UNSTABLE_SENTENCE} {INSTALL_COMMAND}")
            elif self._platform == "win32":
                self._make_windows_link(target, self._program, arguments)
            else:
                self._make_desktop_file(target, self._program, arguments)
        except OSError as error:
            raise ShortcutError(f"I could not change the shortcut: {error}.") from error

    def _make_desktop_file(self, target: Path, program: Path, arguments: Sequence[str]) -> None:
        _write_text_file(self._folders.icon_file, APP_ICON_SVG)
        text = desktop_entry_text(program, arguments, self._folders.icon_file)
        _write_text_file(target, text)

    def _make_windows_link(self, target: Path, program: Path, arguments: Sequence[str]) -> None:
        powershell = find_powershell(self._environ)
        if powershell is None:
            raise ShortcutError("I could not find PowerShell, which Windows needs for shortcuts.")
        self._folders.icon_file.parent.mkdir(parents=True, exist_ok=True)
        if not self._write_ico(self._folders.icon_file):
            _log.warning("Could not write the shortcut icon; the shortcut gets a plain icon")
        target.parent.mkdir(parents=True, exist_ok=True)
        command, env = windows_link_command(
            powershell, target, program, arguments, self._folders.icon_file
        )
        code = self._runner(command, env, POWERSHELL_TIMEOUT_SECONDS)
        if code != 0:
            raise ShortcutError("Windows would not make the shortcut. Please try again.")
