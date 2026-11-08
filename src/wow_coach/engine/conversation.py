"""The chat store: one shared chat history per character, for any AI.

One JSONL file per character (one JSON object per line) in wow-coach's data folder:
``conversations/<Name-Realm>.jsonl``. Every coach (ChatGPT today, others later), the
desktop app and the importer of the player's Claude Code chats read and write this same file.

Format v1, one message per line::

    {"v": 1, "id": "app:3f2a...", "at": "2026-11-07T22:14:07.767Z",
     "role": "user" | "assistant", "content": "plain text",
     "source": "app" | "game" | "claude-code" | "outside",
     "provider": "chatgpt" | "claude-code" | null, "model": "gpt-..." | null,
     "answer": {"title", "steps", "text", "warnings",
                "sources": [{"title", "url"}], "lookups": [{"kind", "text"}]} | null}

* ``content`` is always the plain-text form of the message: any AI can be given it as is.
  That is what makes the history provider-neutral.
* ``answer`` keeps the structured coach answer, only for nicer display in the window.
  ``sources`` and ``lookups`` are optional (left out when empty; old lines do not have them):
  ``sources`` are the web pages the answer came from (only ``http``/``https`` links are kept,
  also when reading), and ``lookups`` are plain sentences about what the coach looked up,
  with a ``kind`` of ``read`` (the player's own data), ``write`` (notes saved) or ``web``.
* A line from an older wow-coach (just ``role`` and ``content``) still reads fine, with safe
  defaults. Unknown fields are ignored, and a damaged line is skipped.
* The file holds no secrets, and never grows past ``MAX_STORED_MESSAGES`` messages.
"""

import hashlib
import json
import os
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from wow_coach.datafolder import data_folder
from wow_coach.engine.sources import MAX_SOURCES, MAX_TITLE_CHARS, SourceLink, is_web_url
from wow_coach.filelock import locked
from wow_coach.notes import safe_file_name

FOLDER_NAME: Final = "conversations"
FORMAT_VERSION: Final = 1
MAX_STORED_MESSAGES: Final = 2_000
MAX_MESSAGE_CHARS: Final = 6_000
MAX_FILE_BYTES: Final = 6_000_000
MAX_READ_BYTES: Final = 2 * MAX_FILE_BYTES  # a bigger file is not ours: do not read it
MAX_ANSWER_ITEMS: Final = 20
MAX_LOOKUPS: Final = 30
MAX_LOOKUP_CHARS: Final = 300

type Role = Literal["user", "assistant"]
type Source = Literal["app", "game", "claude-code", "outside"]
_ROLES: Final[tuple[Role, ...]] = ("user", "assistant")
_SOURCES: Final[tuple[Source, ...]] = ("app", "game", "claude-code", "outside")


@dataclass(frozen=True, slots=True)
class Lookup:
    """One thing the coach looked up or saved while answering, as a plain sentence."""

    kind: str  # "read", "write" or "web"
    text: str


@dataclass(frozen=True, slots=True)
class ChatAnswer:
    """The structured form of a coach answer (the same four parts the game's panel shows).

    ``sources`` and ``lookups`` are what the window shows under the answer.
    """

    title: str
    steps: tuple[str, ...]
    text: str
    warnings: tuple[str, ...]
    sources: tuple[SourceLink, ...] = ()
    lookups: tuple[Lookup, ...] = ()


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One message of the chat history."""

    role: Role
    content: str  # plain text, understood by any AI
    id: str  # unique and stable: the same message is never stored twice
    at: str = ""  # ISO 8601 UTC time; empty for old lines that had none
    source: Source = "app"
    provider: str | None = None  # who answered: "chatgpt", "claude-code"... (None for the player)
    model: str | None = None
    answer: ChatAnswer | None = None


def conversation_file(data_dir: Path, character_key: str) -> Path:
    """Where the conversation with ``character_key`` ("Name-Realm") is kept in ``data_dir``."""
    return data_dir / FOLDER_NAME / f"{safe_file_name(character_key)}.jsonl"


def conversation_path(character_key: str, *, environ: Mapping[str, str]) -> Path:
    """Like ``conversation_file``, in the data folder the environment points to."""
    return conversation_file(data_folder(environ=environ), character_key)


# ---- ids and times ------------------------------------------------------------------


def new_message_id(prefix: str = "app") -> str:
    """A fresh unique id such as ``app:3f2a9c...``."""
    return f"{prefix}:{uuid.uuid4().hex}"


def now_iso(seconds: float) -> str:
    """Unix time as an ISO 8601 UTC string with milliseconds, e.g. ``2026-11-07T22:14:07.767Z``."""
    moment = datetime.fromtimestamp(seconds, tz=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def parse_iso(text: str) -> datetime | None:
    """An ISO 8601 time as a timezone-aware datetime; None when it cannot be understood."""
    try:
        moment = datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


# ---- one message <-> one JSON object --------------------------------------------------


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))[:MAX_ANSWER_ITEMS]


def _sources_from(value: object) -> tuple[SourceLink, ...]:
    """The stored sources; anything that is not a plain web link is dropped."""
    if not isinstance(value, list):
        return ()
    found: list[SourceLink] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        url, title = item.get("url"), item.get("title")
        if isinstance(url, str) and is_web_url(url):
            found.append(SourceLink(title[:MAX_TITLE_CHARS] if isinstance(title, str) else "", url))
    return tuple(found[:MAX_SOURCES])


def _lookups_from(value: object) -> tuple[Lookup, ...]:
    if not isinstance(value, list):
        return ()
    found: list[Lookup] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        kind, text = item.get("kind"), item.get("text")
        if isinstance(kind, str) and isinstance(text, str) and text.strip():
            found.append(Lookup(kind, text[:MAX_LOOKUP_CHARS]))
    return tuple(found[:MAX_LOOKUPS])


def _answer_from(value: object) -> ChatAnswer | None:
    if not isinstance(value, dict):
        return None
    title, text = value.get("title"), value.get("text")
    return ChatAnswer(
        title=title if isinstance(title, str) else "",
        steps=_strings(value.get("steps")),
        text=text if isinstance(text, str) else "",
        warnings=_strings(value.get("warnings")),
        sources=_sources_from(value.get("sources")),
        lookups=_lookups_from(value.get("lookups")),
    )


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def message_from_dict(data: object, *, fallback_id: str = "") -> ChatMessage | None:
    """One saved JSON object as a message; None when it is damaged or has no text."""
    if not isinstance(data, dict):
        return None
    role, content = data.get("role"), data.get("content")
    if role not in _ROLES or not isinstance(content, str) or not content.strip():
        return None
    source = data.get("source")
    at = data.get("at")
    return ChatMessage(
        role="user" if role == "user" else "assistant",
        content=content[:MAX_MESSAGE_CHARS],
        id=_text_or_none(data.get("id")) or fallback_id,
        at=at if isinstance(at, str) else "",
        source=source if source in _SOURCES else "app",
        provider=_text_or_none(data.get("provider")),
        model=_text_or_none(data.get("model")),
        answer=_answer_from(data.get("answer")),
    )


def message_to_dict(message: ChatMessage) -> dict[str, object]:
    """A message as the JSON object stored on one line (format v1)."""
    answer = message.answer
    return {
        "v": FORMAT_VERSION,
        "id": message.id,
        "at": message.at,
        "role": message.role,
        "content": message.content,
        "source": message.source,
        "provider": message.provider,
        "model": message.model,
        "answer": None if answer is None else answer_to_dict(answer),
    }


def answer_to_dict(answer: ChatAnswer) -> dict[str, object]:
    """A structured answer as stored; ``sources`` and ``lookups`` only when there are some."""
    data: dict[str, object] = {
        "title": answer.title,
        "steps": list(answer.steps),
        "text": answer.text,
        "warnings": list(answer.warnings),
    }
    if answer.sources:
        data["sources"] = [{"title": item.title, "url": item.url} for item in answer.sources]
    if answer.lookups:
        data["lookups"] = [{"kind": item.kind, "text": item.text} for item in answer.lookups]
    return data


def _legacy_id(line: str, number: int) -> str:
    """An id for an old line that has none: from its text and place, so it stays the same."""
    digest = hashlib.sha1(f"{number}:{line}".encode(), usedforsecurity=False).hexdigest()
    return f"legacy:{digest[:16]}"


# ---- reading --------------------------------------------------------------------------


def _read_all(path: Path) -> list[ChatMessage]:
    """Every readable message, in time order (lines without a time keep their place)."""
    try:
        if not path.is_file() or path.stat().st_size > MAX_READ_BYTES:
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: list[ChatMessage] = []
    for number, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except ValueError, RecursionError:
            continue
        parsed = message_from_dict(data, fallback_id=_legacy_id(line, number))
        if parsed is not None:
            found.append(parsed)
    return _in_time_order(found)


def _in_time_order(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Sort by time. A message without a (readable) time counts as the one before it."""
    keyed: list[tuple[datetime, int, ChatMessage]] = []
    last = datetime.min.replace(tzinfo=UTC)
    for position, item in enumerate(messages):
        moment = parse_iso(item.at) if item.at else None
        last = moment or last
        keyed.append((last, position, item))
    keyed.sort(key=lambda entry: (entry[0], entry[1]))
    return [item for _, _, item in keyed]


def read_messages(path: Path, limit: int | None = None) -> list[ChatMessage]:
    """The newest ``limit`` messages (all when None), oldest first.

    A missing or damaged file gives fewer messages, never an error.
    """
    messages = _read_all(path)
    if limit is None:
        return messages
    return messages[-limit:] if limit > 0 else []


# ---- writing --------------------------------------------------------------------------


def _fit_size(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Drop the oldest messages until the count and the file size are within the caps."""
    kept = messages[-MAX_STORED_MESSAGES:]
    sizes = [len(json.dumps(message_to_dict(m), ensure_ascii=False)) + 1 for m in kept]
    total, start = sum(sizes), 0
    while total > MAX_FILE_BYTES and start < len(kept) - 1:
        total -= sizes[start]
        start += 1
    return kept[start:]


def _cleaned(message: ChatMessage) -> ChatMessage | None:
    if not message.content.strip():
        return None
    content = message.content[:MAX_MESSAGE_CHARS]
    return ChatMessage(
        role=message.role,
        content=content,
        id=message.id or new_message_id(),
        at=message.at,
        source=message.source,
        provider=message.provider,
        model=message.model,
        answer=message.answer,
    )


def append_messages(path: Path, new_messages: list[ChatMessage]) -> int:
    """Add messages to the history. Returns how many were really new.

    The file is locked while it is changed, a message whose ``id`` is already stored is
    skipped, the result is in time order and trimmed to the newest ``MAX_STORED_MESSAGES``.
    It is written in one step (temp file, then rename), so a reader never sees half a file.
    """
    cleaned = [item for item in map(_cleaned, new_messages) if item is not None]
    if not cleaned:
        return 0
    with locked(path):
        old = _read_all(path)
        known = {item.id for item in old}
        fresh: list[ChatMessage] = []
        for item in cleaned:
            if item.id not in known:
                known.add(item.id)
                fresh.append(item)
        if not fresh:
            return 0
        kept = _fit_size(_in_time_order([*old, *fresh]))
        _write(path, kept)
    return len(fresh)


def _write(path: Path, messages: list[ChatMessage]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(message_to_dict(m), ensure_ascii=False) for m in messages) + "\n"
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".conv-", suffix=".part")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
        Path(temp_name).replace(path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
