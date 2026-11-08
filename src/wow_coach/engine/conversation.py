"""Remember the last few messages with each character, for follow-up questions.

One JSONL file per character (one JSON object per line) in wow-coach's data folder:
``conversations/<Name-Realm>.jsonl``. It holds only the questions and the answers, no
secrets. A damaged line is skipped, and the file never grows past a fixed size.
"""

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from wow_coach.datafolder import data_folder
from wow_coach.notes import safe_file_name

FOLDER_NAME: Final = "conversations"
CONTEXT_MESSAGES: Final = 6  # how many past messages the AI sees (3 questions and answers)
MAX_STORED_MESSAGES: Final = 40
MAX_MESSAGE_CHARS: Final = 2000
MAX_FILE_BYTES: Final = 60_000
_ROLES: Final = ("user", "assistant")


@dataclass(frozen=True, slots=True)
class Turn:
    """One message of the conversation: the player's question or the coach's answer."""

    role: Literal["user", "assistant"]
    content: str


def conversation_path(character_key: str, *, environ: Mapping[str, str]) -> Path:
    """Where the conversation with ``character_key`` ("Name-Realm") is kept."""
    folder = data_folder(environ=environ) / FOLDER_NAME
    return folder / f"{safe_file_name(character_key)}.jsonl"


def _read_line(line: str) -> Turn | None:
    """One saved line as a Turn; None when it is damaged."""
    try:
        data = json.loads(line)
    except ValueError, RecursionError:
        return None
    if not isinstance(data, dict):
        return None
    role, content = data.get("role"), data.get("content")
    if role == "user" and isinstance(content, str) and content.strip():
        return Turn("user", content[:MAX_MESSAGE_CHARS])
    if role == "assistant" and isinstance(content, str) and content.strip():
        return Turn("assistant", content[:MAX_MESSAGE_CHARS])
    return None


def _read_all(path: Path) -> list[Turn]:
    try:
        if not path.is_file() or path.stat().st_size > 10 * MAX_FILE_BYTES:
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    turns = (_read_line(line) for line in text.splitlines() if line.strip())
    return [turn for turn in turns if turn is not None]


def load_turns(path: Path, *, limit: int = CONTEXT_MESSAGES) -> list[Turn]:
    """The newest ``limit`` messages, oldest first. A missing or damaged file gives fewer."""
    return _read_all(path)[-limit:] if limit > 0 else []


def _to_lines(turns: list[Turn]) -> list[str]:
    return [json.dumps({"role": t.role, "content": t.content}, ensure_ascii=False) for t in turns]


def _fit_size(turns: list[Turn]) -> list[Turn]:
    """Drop the oldest messages until the count and the file size are within the caps."""
    kept = turns[-MAX_STORED_MESSAGES:]
    while len(kept) > 1 and sum(len(line) + 1 for line in _to_lines(kept)) > MAX_FILE_BYTES:
        kept = kept[1:]
    return kept


def append_turns(path: Path, new_turns: list[Turn]) -> None:
    """Add messages to the conversation, then trim it. Written in one step (temp, rename)."""
    cleaned = [Turn(t.role, t.content[:MAX_MESSAGE_CHARS]) for t in new_turns if t.content.strip()]
    turns = _fit_size([*_read_all(path), *cleaned])
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".conv-", suffix=".part")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write("\n".join(_to_lines(turns)) + "\n")
        Path(temp_name).replace(path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
