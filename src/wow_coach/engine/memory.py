"""Small local lists the engine keeps between runs, per character, in the data folder.

* ``answered-questions.json``: ids of game questions already answered. Without it, an
  answer that could not be written to ``Advice.lua`` (disk full, antivirus...) would leave
  the question looking open, and every new question would pay for all the old ones again.
* ``hidden-names.json``: other players' names seen in any earlier save. A name can drop out
  of the save (the player left the group) but still sit in the conversation, the journal or
  the notes, so it must keep being hidden.

Both files hold no secrets. A damaged file counts as empty, and writes are atomic.
"""

import contextlib
import json
import os
import tempfile
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Final

from wow_coach.datafolder import data_folder

ANSWERED_FILE: Final = "answered-questions.json"
NAMES_FILE: Final = "hidden-names-v2.json"
# The first version wrongly stored monster killers as player names ("Hogger"). Remembered
# names last for good, so the old file is deleted instead of read.
OLD_NAMES_FILE: Final = "hidden-names.json"
MAX_IDS_PER_CHARACTER: Final = 100
MAX_NAMES_PER_CHARACTER: Final = 200
MAX_CHARACTERS: Final = 50
MAX_FILE_BYTES: Final = 1_200_000  # 50 characters x 200 names x 100 characters, at most
MAX_ITEM_CHARS: Final = 100
LOCK_WAIT_SECONDS: Final = 2.0
LOCK_STALE_SECONDS: Final = 30.0
LOCK_POLL_SECONDS: Final = 0.05


def _load(path: Path) -> dict[str, list[str]]:
    """The saved lists by character key; anything damaged is dropped."""
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return {}
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except OSError, ValueError, RecursionError:
        return {}
    if not isinstance(data, dict):
        return {}
    clean: dict[str, list[str]] = {}
    for key, items in data.items():
        if isinstance(key, str) and isinstance(items, list):
            clean[key] = [i[:MAX_ITEM_CHARS] for i in items if isinstance(i, str) and i]
    return clean


def _fit(data: dict[str, list[str]]) -> str:
    """The JSON text for ``data``, dropping the oldest characters until it fits the limit."""
    text = json.dumps(data, ensure_ascii=False)
    while len(text.encode("utf-8")) > MAX_FILE_BYTES and len(data) > 1:
        del data[next(iter(data))]
        text = json.dumps(data, ensure_ascii=False)
    return text


def _save(path: Path, data: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _fit(data)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".mem-", suffix=".part")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
        Path(temp_name).replace(path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _lock_is_stale(lock: Path) -> bool:
    try:
        return time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS
    except OSError:
        return False


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[None]:
    """Hold ``<file>.lock`` (made with O_EXCL, so only one program gets it) while running.

    Waits about 2 seconds, takes over a lock older than 30 seconds (a crashed program), and
    always removes its own lock. If the lock can't be had in time we go on without it: a
    rare lost update of a small list is better than blocking the coach.
    """
    lock = path.with_name(path.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    held = False
    while not held:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
            held = True
        except FileExistsError:
            if _lock_is_stale(lock):
                with contextlib.suppress(OSError):
                    lock.unlink()
            elif time.monotonic() > deadline:
                break
            else:
                time.sleep(LOCK_POLL_SECONDS)
    try:
        yield
    finally:
        if held:
            with contextlib.suppress(OSError):
                lock.unlink()


def _add(path: Path, key: str, items: set[str] | list[str], cap: int) -> None:
    """Add items to a character's list (newest last), keeping the newest ``cap``."""
    with _locked(path):
        _add_locked(path, key, items, cap)


def _add_locked(path: Path, key: str, items: set[str] | list[str], cap: int) -> None:
    data = _load(path)
    old = data.pop(key, [])  # popped and re-added, so this character moves to the end
    fresh = [i[:MAX_ITEM_CHARS] for i in sorted(items) if i] if isinstance(items, set) else items
    merged = [*(i for i in old if i not in fresh), *fresh]
    data[key] = merged[-cap:]
    for stale in list(data)[:-MAX_CHARACTERS]:
        del data[stale]
    _save(path, data)


class LocalMemory:
    """The two lists, for one data folder."""

    def __init__(self, *, environ: Mapping[str, str]) -> None:
        folder = data_folder(environ=environ)
        self._answered = folder / ANSWERED_FILE
        self._names = folder / NAMES_FILE
        with contextlib.suppress(OSError):
            (folder / OLD_NAMES_FILE).unlink(missing_ok=True)

    def answered_ids(self, character_key: str) -> set[str]:
        """Question ids this program has already answered for the character."""
        return set(_load(self._answered).get(character_key, []))

    def add_answered(self, character_key: str, question_id: str) -> None:
        """Remember an answered question (even when writing it to the game failed)."""
        _add(self._answered, character_key, [question_id], MAX_IDS_PER_CHARACTER)

    def seen_names(self, character_key: str) -> set[str]:
        """Other players' names seen in earlier saves of the character."""
        return set(_load(self._names).get(character_key, []))

    def add_seen_names(self, character_key: str, names: set[str]) -> None:
        """Remember names for good (the oldest go when there are more than 200)."""
        if names - self.seen_names(character_key):
            _add(self._names, character_key, names, MAX_NAMES_PER_CHARACTER)
