"""Telling the player outside the game that an answer is ready.

A desktop notification, shown with a program that already comes with the computer.

The text comes from an AI that may have read text other players wrote, so it is treated as
untrusted. It must never become part of a command or a script. It only travels as:

- a separate item in the argument list (never glued into a string),
- the standard input of a program, or
- an environment variable that a FIXED script reads.

No program is ever run through a shell.
"""

import html
import logging
import os
import shutil
import subprocess
import sys
import unicodedata
from collections.abc import Callable, Mapping
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "wow-coach"
NOTIFY_TIMEOUT_SECONDS = 5
MAX_TITLE = 60
MAX_BODY = 240

TEXT_VARIABLE = "WOW_COACH_TEXT"
TITLE_VARIABLE = "WOW_COACH_TITLE"

# macOS: a fixed script. The text arrives as arguments (argv), never inside the script.
MAC_SCRIPT = (
    "on run argv",
    "display notification (item 2 of argv) with title (item 1 of argv)",
    "end run",
)

# Windows: a fixed script. It reads the text from environment variables.
# The text is escaped for XML first, so it can only ever be plain text inside the toast.
# The id below is Windows PowerShell's own app id: toasts need some registered app id.
WINDOWS_NOTIFY_SCRIPT = (
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
    "ContentType = WindowsRuntime] | Out-Null; "
    "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
    "ContentType = WindowsRuntime] | Out-Null; "
    f"$title = [Security.SecurityElement]::Escape($env:{TITLE_VARIABLE}); "
    f"$body = [Security.SecurityElement]::Escape($env:{TEXT_VARIABLE}); "
    "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument; "
    '$xml.LoadXml(\'<toast><visual><binding template="ToastText02">'
    '<text id="1">\' + $title + \'</text><text id="2">\' + $body + '
    "'</text></binding></visual></toast>'); "
    "$toast = New-Object Windows.UI.Notifications.ToastNotification $xml; "
    "$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'; "
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app)"
    ".Show($toast)"
)


# runner(argv, env_extra, timeout) -> exit code. May raise OSError or TimeoutExpired.
Runner = Callable[[list[str], Mapping[str, str], float], int]


def clean_text(text: str, limit: int) -> str:
    """Remove control characters (keeping spaces) and cut the text to `limit` characters."""
    kept = []
    for char in text:
        if char.isspace():
            kept.append(" ")  # newlines and tabs become plain spaces
        elif unicodedata.category(char).startswith("C"):
            continue  # control, format and other invisible characters
        else:
            kept.append(char)
    return "".join(kept).strip()[:limit].strip()


def escape_markup(text: str, limit: int) -> str:
    """Escape `<`, `>` and `&` so a notification shows the text as plain text, not markup.

    Some desktops (KDE) read notification text as HTML-like markup, so an AI-written
    `<a href=...>` would become a clickable link. The cut counts escaped characters and
    is made between characters, so it never splits an entity such as `&amp;`.
    """
    result = ""
    for char in clean_text(text, len(text)):
        piece = html.escape(char, quote=False)
        if len(result) + len(piece) > limit:
            break
        result += piece
    return result.strip()


def default_runner(argv: list[str], env_extra: Mapping[str, str], timeout: float) -> int:
    """Run a program (no shell), wait for it, and return its exit code."""
    done = subprocess.run(  # noqa: S603 - argument list, no shell; text is never a command
        argv,
        env={**os.environ, **env_extra},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return done.returncode


def _not_an_option(text: str) -> str:
    """For programs that may still read a leading '-' as an option: add a space first."""
    return " " + text if text.startswith("-") else text


def _powershell(program: str, script: str) -> list[str]:
    return [program, "-NoProfile", "-NonInteractive", "-Command", script]


class SystemAlerts:
    """Notifications through the programs this computer has."""

    def __init__(
        self,
        *,
        platform: str = sys.platform,
        which: Callable[[str], str | None] = shutil.which,
        runner: Runner = default_runner,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._platform = platform
        # Only used to find Windows' own PowerShell (SYSTEMROOT); tests pass their own.
        self._environ = os.environ if environ is None else environ
        self._which = which
        self._runner = runner

    # --- public API ---

    def available(self) -> dict[str, bool]:
        """Whether this computer can show notifications."""
        return {"notify": self._notify_command("t", "b") is not None}

    def notify(self, title: str, body: str) -> bool:
        """Show a desktop notification and wait briefly. Never raises."""
        try:
            if self._platform.startswith("linux"):
                title = escape_markup(title, MAX_TITLE)
                body = escape_markup(body, MAX_BODY)
            else:
                title = clean_text(title, MAX_TITLE)
                body = clean_text(body, MAX_BODY)
            command = self._notify_command(title, body)
            if command is None or not (title or body):
                return False
            argv, env = command
            code = self._runner(argv, env, NOTIFY_TIMEOUT_SECONDS)
        except Exception as error:
            log.warning("notify failed: %s", type(error).__name__)
            return False
        if code != 0:
            log.warning("notify failed: nonzero exit")
        return code == 0

    # --- building the commands (one place per platform) ---

    def _notify_command(self, title: str, body: str) -> tuple[list[str], dict[str, str]] | None:
        if self._platform.startswith("linux"):
            program = self._find("notify-send")
            if program is None:
                return None
            return [program, f"--app-name={APP_NAME}", "--", title, body], {}
        if self._platform == "darwin":
            program = self._find("osascript")
            if program is None:
                return None
            script = [part for line in MAC_SCRIPT for part in ("-e", line)]
            args = ["--", _not_an_option(title), _not_an_option(body)]
            return [program, *script, *args], {}
        if self._platform == "win32":
            program = self._find_powershell()
            if program is None:
                return None
            env = {TITLE_VARIABLE: title, TEXT_VARIABLE: body}
            return _powershell(program, WINDOWS_NOTIFY_SCRIPT), env
        return None

    def _find(self, name: str) -> str | None:
        """The full path of a program. Running the full path (not the bare name) stops a
        look-alike program in the current folder from being picked instead."""
        return self._which(name) or None

    def _find_powershell(self) -> str | None:
        """Windows PowerShell: the copy in System32 if it exists, else whatever `which` finds."""
        root = self._environ.get("SYSTEMROOT")
        if root and self._platform == "win32":
            system_copy = Path(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
            if system_copy.exists():
                return str(system_copy)
        return self._find("powershell")
