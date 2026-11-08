"""Reads the coach's notebook files in the background, and only when they changed.

The notebook is two kinds of Markdown file (see ``wow_coach.notes``): the player notes and
one journal per character. A game hard disk or a synced folder can be slow, so the Notebook
page never reads them itself. It asks a ``NotesReader``, which:

* does the file work through a ``Runner`` (a background thread in the app, the same thread in
  tests), like ``CoreBridge`` does;
* delivers the result with the ``loaded`` Qt signal;
* remembers what the files looked like (change time and size) and stays silent when a later
  check finds the same, so the page is not redrawn for nothing.
"""

import logging
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PySide6.QtCore import QObject, Signal

from wow_coach.desktop.bridge import Runner, run_in_thread
from wow_coach.notes import journal_path, notes_path

_log = logging.getLogger(__name__)

type FileStamp = tuple[int, int] | None  # (change time in ns, size in bytes); None = no file
type Signature = tuple[str | None, FileStamp, FileStamp]

READ_ERROR: Final = "This file could not be read just now."


@dataclass(frozen=True, slots=True)
class NoteFile:
    """One notes file as read from disk.

    ``text`` is None when the file does not exist (or could not be read, see ``problem``).
    """

    path: Path
    text: str | None = None
    problem: str | None = None


@dataclass(frozen=True, slots=True)
class NotebookData:
    """Both files the Notebook page shows. ``character`` is None without a selected character."""

    character_key: str | None
    character: NoteFile | None
    player: NoteFile


def stamp_of(path: Path) -> FileStamp:
    """A cheap fingerprint of a file: when it changed and how big it is (None if missing)."""
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def read_note_file(path: Path) -> NoteFile:
    """Read one file. A missing file is normal (the coach may not have written it yet)."""
    try:
        return NoteFile(path, path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return NoteFile(path)
    except OSError, UnicodeDecodeError:
        _log.exception("Could not read the notebook file %s", path)
        return NoteFile(path, problem=READ_ERROR)


class NotesReader(QObject):
    """Reads the notebook files off the window's thread and announces changes."""

    # A NotebookData, emitted only when something is new (or a reload was forced).
    loaded = Signal(object)

    def __init__(
        self,
        *,
        runner: Runner = run_in_thread,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        """Create the reader.

        Args:
            runner: How the file work is started; tests pass one that runs it at once.
            environ: Environment variables that say where the notes live (default: the real
                ones). Tests rely on the variables ``conftest.py`` sets.
        """
        super().__init__()
        self._run = runner
        self._environ: Mapping[str, str] = os.environ if environ is None else environ
        # One background job at a time. A request that arrives meanwhile is remembered and
        # the running job simply checks once more.
        self._lock = threading.Lock()
        self._running = False
        self._again = False
        self._wanted_key: str | None = None
        self._force = False
        self._last: Signature | None = None

    def player_notes_path(self) -> Path:
        """Where the player notes live."""
        return notes_path(environ=self._environ)

    def journal_file(self, key: str) -> Path:
        """Where the journal of character ``key`` lives."""
        return journal_path(key, environ=self._environ)

    def request(self, character_key: str | None, *, force: bool = False) -> None:
        """Check the files for ``character_key`` and, if new, deliver them with ``loaded``.

        Args:
            character_key: ``Name-Realm`` of the shown character, or None.
            force: Read and deliver even when nothing seems to have changed (Reload button).
        """
        with self._lock:
            self._wanted_key = character_key
            self._force = self._force or force
            if self._running:
                self._again = True
                return
            self._running = True
        self._run(self._work_until_current)

    def _work_until_current(self) -> None:
        """Background job: check, maybe read and announce, until no new request came in."""
        while True:
            with self._lock:
                key, force = self._wanted_key, self._force
                self._force = False
            self._check_once(key, force)
            with self._lock:
                if not self._again:
                    self._running = False
                    return
                self._again = False

    def _check_once(self, key: str | None, force: bool) -> None:
        player_path = self.player_notes_path()
        journal = self.journal_file(key) if key else None
        signature: Signature = (
            key,
            stamp_of(journal) if journal else None,
            stamp_of(player_path),
        )
        if not force and signature == self._last:
            return  # nothing changed: stay quiet, so the page keeps what it shows
        data = NotebookData(
            character_key=key,
            character=read_note_file(journal) if journal else None,
            player=read_note_file(player_path),
        )
        self._last = signature
        self.loaded.emit(data)
