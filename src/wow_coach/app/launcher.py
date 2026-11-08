"""Opens the browser WITHOUT putting the one-time start token on a command line.

A program's command line can be read by every user of the computer (on Linux through
``/proc/<pid>/cmdline``). The start link holds the secret token, so we do not hand it to
the browser as an argument. Instead we write a tiny private HTML page that redirects to the
link, and open that FILE. The folder is private (mode 0700), the file too (0600), and both
are deleted after a minute. The terminal still prints the link, because the terminal is private.
"""

import html
import os
import shutil
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Final

KEEP_SECONDS: Final = 60.0
FILE_NAME: Final = "open-wow-coach.html"


def _private_parent(environ: dict[str, str] | os._Environ[str]) -> str | None:
    """``$XDG_RUNTIME_DIR`` (a private, in-memory folder) when it exists, else the default."""
    runtime = environ.get("XDG_RUNTIME_DIR")
    return runtime if runtime and Path(runtime).is_dir() else None


def write_launcher(url: str, environ: dict[str, str] | os._Environ[str] | None = None) -> Path:
    """Write the redirect page into a new private folder and return the file's path."""
    folder = Path(tempfile.mkdtemp(prefix="wow-coach-", dir=_private_parent(environ or os.environ)))
    folder.chmod(0o700)
    page = folder / FILE_NAME
    safe = html.escape(url, quote=True)
    text = (
        '<!doctype html><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0; url={safe}">'
        f'<title>wow-coach</title><p>Opening wow-coach... <a href="{safe}">Click here</a> '
        "if nothing happens.</p>"
    )
    descriptor = os.open(page, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(text)
    return page


def remove_launcher(page: Path) -> None:
    """Delete the page and its private folder (fine if already gone)."""
    shutil.rmtree(page.parent, ignore_errors=True)


def open_start_page(
    url: str,
    opener: Callable[[str], object],
    *,
    keep_seconds: float = KEEP_SECONDS,
) -> Callable[[], None]:
    """Open the start link through a private file. Returns a function that cleans up now.

    The file is also removed by itself after ``keep_seconds``.
    """
    page = write_launcher(url)
    timer = threading.Timer(keep_seconds, remove_launcher, args=(page,))
    timer.daemon = True
    timer.start()
    opener(page.as_uri())

    def clean_up() -> None:
        timer.cancel()
        remove_launcher(page)

    return clean_up
