"""Notices when ``Advice.lua`` was changed by someone else (for example the Claude Code coach).

When wow-coach's own engine writes an answer, the file changes too, and that must not look
like an outside change. So after every engine call the program calls ``refresh()``, which
adopts the file as it is now. Later, ``outside_changes()`` only reports answers that were not
in the file at the last refresh.

Polling is a single ``stat`` call (answered from memory, so it never wakes a slow hard disk);
the file is only read after its change time moved.
"""

import threading
from pathlib import Path

from wow_coach.advice.contract import AdviceAnswer
from wow_coach.advice.paths import advice_file_path
from wow_coach.advice.reader import read_advice_file

type AnswerId = tuple[str, int, str]  # (character key, answered_at, title)


class AdviceBaseline:
    """Remembers what ``Advice.lua`` looked like the last time we knew about it."""

    def __init__(self, wow_dir: Path) -> None:
        self._path = advice_file_path(wow_dir)
        self._lock = threading.Lock()
        self._stamp: int | None = None
        self._known: set[AnswerId] = set()
        self.refresh()

    def refresh(self) -> None:
        """Adopt the file as it is now: nothing in it counts as new."""
        with self._lock:
            self._stamp = self._file_stamp()
            self._known = {item for item, _ in self._read_answers()}

    def outside_changes(self) -> list[tuple[str, AdviceAnswer]]:
        """Answers that appeared since the last refresh, oldest first (empty if unchanged)."""
        with self._lock:
            stamp = self._file_stamp()
            if stamp == self._stamp:
                return []
            self._stamp = stamp
            found = self._read_answers()
            new = [(item[0], answer) for item, answer in found if item not in self._known]
            self._known = {item for item, _ in found}
        return sorted(new, key=lambda pair: pair[1].answered_at)

    def _file_stamp(self) -> int | None:
        try:
            return self._path.stat().st_mtime_ns
        except OSError:
            return None  # the file is missing (or the disk is busy): treat as "no file"

    def _read_answers(self) -> list[tuple[AnswerId, AdviceAnswer]]:
        advice = read_advice_file(self._path)
        if advice is None:
            return []
        return [
            ((key, answer.answered_at, answer.title), answer)
            for key, character in advice.characters.items()
            for answer in character.answers
        ]
