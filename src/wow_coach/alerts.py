"""Telling the player outside the game that an answer is ready.

Two things: a desktop notification, and reading the answer aloud. Both use programs that
already come with the computer.

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
import threading
import unicodedata
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

APP_NAME = "wow-coach"
NOTIFY_TIMEOUT_SECONDS = 5
MAX_TITLE = 60
MAX_BODY = 240
MAX_SPEECH = 600

TEXT_VARIABLE = "WOW_COACH_TEXT"
TITLE_VARIABLE = "WOW_COACH_TITLE"

# macOS: a fixed script. The text arrives as arguments (argv), never inside the script.
MAC_SCRIPT = (
    "on run argv",
    "display notification (item 2 of argv) with title (item 1 of argv)",
    "end run",
)

# Windows: fixed scripts. They read the text from environment variables.
WINDOWS_SPEAK_SCRIPT = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    f"$s.Speak($env:{TEXT_VARIABLE})"
)

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


class SpeechProcess(Protocol):
    """The part of a running program that we need: is it still going, and stop it."""

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...


# runner(argv, env_extra, timeout) -> exit code. May raise OSError or TimeoutExpired.
Runner = Callable[[list[str], Mapping[str, str], float], int]
# popen(argv, env_extra, stdin_text) -> the started program. Returns at once.
Popen = Callable[[list[str], Mapping[str, str], str | None], SpeechProcess]


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


def default_popen(
    argv: list[str], env_extra: Mapping[str, str], stdin_text: str | None
) -> SpeechProcess:
    """Start a program in the background. If given, `stdin_text` is sent to its input."""
    process = subprocess.Popen(  # noqa: S603 - argument list, no shell
        argv,
        env={**os.environ, **env_extra},
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    if stdin_text is not None and process.stdin is not None:
        process.stdin.write(stdin_text)  # at most ~600 characters: fits the pipe
        process.stdin.close()
    return process


def _not_an_option(text: str) -> str:
    """For programs that may still read a leading '-' as an option: add a space first."""
    return " " + text if text.startswith("-") else text


def _powershell(program: str, script: str) -> list[str]:
    return [program, "-NoProfile", "-NonInteractive", "-Command", script]


class SystemAlerts:
    """Notifications and read-aloud through the programs this computer has."""

    def __init__(
        self,
        *,
        platform: str = sys.platform,
        which: Callable[[str], str | None] = shutil.which,
        runner: Runner = default_runner,
        popen: Popen = default_popen,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._platform = platform
        # Only used to find Windows' own PowerShell (SYSTEMROOT); tests pass their own.
        self._environ = os.environ if environ is None else environ
        self._which = which
        self._runner = runner
        self._popen = popen
        self._speaking: SpeechProcess | None = None
        self._lock = threading.Lock()

    # --- public API ---

    def available(self) -> dict[str, bool]:
        """Whether this computer can show notifications and read aloud."""
        return {
            "notify": self._notify_command("t", "b") is not None,
            "speak": self._speak_command("t") is not None,
        }

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

    def speak(self, text: str) -> bool:
        """Read the text aloud in the background, replacing any earlier speech. Never raises."""
        try:
            text = clean_text(text, MAX_SPEECH)
            command = self._speak_command(text)
            if command is None or not text:
                return False
            argv, env, stdin_text = command
            with self._lock:
                self._stop_current()
                self._speaking = self._popen(argv, env, stdin_text)
        except Exception as error:
            log.warning("speak failed: %s", type(error).__name__)
            return False
        return True

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

    def _speak_command(self, text: str) -> tuple[list[str], dict[str, str], str | None] | None:
        if self._platform.startswith("linux"):
            spd_say = self._find("spd-say")
            if spd_say:
                return [spd_say, "--", text], {}, None
            espeak = self._find("espeak-ng")
            if espeak:
                return [espeak, "--stdin"], {}, text
            return None
        if self._platform == "darwin":
            program = self._find("say")
            if program is None:
                return None
            return [program, "-f", "-"], {}, text
        if self._platform == "win32":
            program = self._find_powershell()
            if program is None:
                return None
            return _powershell(program, WINDOWS_SPEAK_SCRIPT), {TEXT_VARIABLE: text}, None
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

    def _stop_current(self) -> None:
        """Stop the previous speech if it is still talking (one voice at a time)."""
        previous = self._speaking
        self._speaking = None
        if previous is not None and previous.poll() is None:
            previous.terminate()
