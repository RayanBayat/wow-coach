"""Small local lists the engine keeps between runs, per character, in the data folder.

* ``answered-questions.json``: ids of game questions already answered. Without it, an
  answer that could not be written to ``Advice.lua`` (disk full, antivirus...) would leave
  the question looking open, and every new question would pay for all the old ones again.
* ``hidden-names.json``: other players' names seen in any earlier save. A name can drop out
  of the save (the player left the group) but still sit in the conversation, the journal or
  the notes, so it must keep being hidden.

Both files hold no secrets. A damaged file counts as empty, and writes are atomic.
"""

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from wow_coach.datafolder import data_folder

ANSWERED_FILE: Final = "answered-questions.json"
NAMES_FILE: Final = "hidden-names.json"
MAX_IDS_PER_CHARACTER: Final = 100
MAX_NAMES_PER_CHARACTER: Final = 200
MAX_CHARACTERS: Final = 50
MAX_FILE_BYTES: Final = 200_000
MAX_ITEM_CHARS: Final = 100


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


def _save(path: Path, data: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".mem-", suffix=".part")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False)
        Path(temp_name).replace(path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _add(path: Path, key: str, items: set[str] | list[str], cap: int) -> None:
    """Add items to a character's list (newest last), keeping the newest ``cap``."""
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
