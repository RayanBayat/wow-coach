"""Import the player's Claude Code coach chats into wow-coach's chat history.

Claude Code keeps every session as a JSONL transcript in ``~/.claude/projects/<project>/``.
A session started with ``claude --agent wow-coach`` has a line
``{"type": "agent-setting", "agentSetting": "wow-coach"}``: only those sessions are imported,
and only what people said (the player's typed messages and the coach's text replies). Tool
calls, tool results, thinking, system notes and sub-agent chats are skipped.

The transcript format belongs to Claude Code and is not documented, so this code trusts
nothing: every line may be damaged or shaped differently than expected, and anything odd is
skipped instead of raising an error.

The import is incremental and safe to repeat:

* For every transcript, ``import-state.json`` (in wow-coach's data folder) remembers how many
  bytes were read, so each pass only reads what is new.
* Every imported message gets a stable id (``claude-code:<line uuid>``), and the chat store
  never keeps one id twice. Even if the state file is lost, nothing is imported twice.
"""

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from wow_coach.characters import pick_character
from wow_coach.engine.conversation import (
    ChatMessage,
    append_messages,
    conversation_file,
    parse_iso,
)
from wow_coach.filelock import locked
from wow_coach.savedvars import Character

IMPORT_STATE_FILE: Final = "import-state.json"
COACH_AGENT: Final = "wow-coach"
SETTLE_SECONDS: Final = 30.0  # a transcript changed this recently may hold an unfinished reply
MAX_CHUNK_BYTES: Final = 64_000_000  # most bytes read from one transcript in one pass
MAX_STATE_BYTES: Final = 4_000_000
# Text that Claude Code writes as "user" lines but that no person typed.
_WRAPPER_PREFIXES: Final = (
    "<command-",
    "<local-command",
    "<system-reminder>",
    "<task-notification",
    "<user-prompt-submit-hook",
    "[Request interrupted",
    "Caveat:",
)

type Json = dict[str, object]


@dataclass(frozen=True, slots=True)
class ImportResult:
    """What one pass did."""

    imported: int  # messages that were new
    character_keys: tuple[str, ...]  # characters whose chat got messages


@dataclass(slots=True)
class _FileState:
    """What is remembered about one transcript."""

    offset: int = 0  # bytes already dealt with
    coach: bool = False  # is it a wow-coach session?
    character: str | None = None  # the character name the session's tool calls used last


@dataclass(frozen=True, slots=True)
class _Record:
    """One complete, parsed line of a transcript and where it sits in the file."""

    data: Json
    start: int
    end: int


@dataclass(slots=True)
class _Reply:
    """An assistant reply being put together from its text blocks."""

    message_id: str
    first: Json
    texts: list[str] = field(default_factory=list)
    start: int = 0


def claude_projects_dir(environ: Mapping[str, str]) -> Path:
    """Claude Code's transcripts: ``$CLAUDE_CONFIG_DIR/projects``, else ``~/.claude/projects``."""
    configured = environ.get("CLAUDE_CONFIG_DIR", "").strip()
    base = Path(configured).expanduser() if configured else Path.home() / ".claude"
    return base / "projects"


# ---- reading one transcript -------------------------------------------------------------


def _read_records(path: Path, offset: int) -> tuple[list[_Record], int]:
    """The complete lines after ``offset``, parsed, and the offset just after the last of them.

    A last line without its newline is still being written, so it is left for the next pass.
    Lines that are not a JSON object are counted as read but give no record.
    """
    with path.open("rb") as file:
        file.seek(offset)
        chunk = file.read(MAX_CHUNK_BYTES)
    records: list[_Record] = []
    position = 0
    for raw in chunk.split(b"\n")[:-1]:  # the part after the last newline is not complete
        end = position + len(raw) + 1
        parsed = _parse_json_object(raw)
        if parsed is not None:
            records.append(_Record(parsed, offset + position, offset + end))
        position = end
    if position == 0 and len(chunk) >= MAX_CHUNK_BYTES:
        position = len(chunk)  # one enormous line: skip it rather than get stuck
    return records, offset + position


def _parse_json_object(raw: bytes) -> Json | None:
    try:
        value = json.loads(raw)
    except ValueError, RecursionError:
        return None
    return value if isinstance(value, dict) else None


def _dict(value: object) -> Json:
    return value if isinstance(value, dict) else {}


def _blocks(value: object) -> list[Json]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _is_coach_setting(data: Json) -> bool:
    return data.get("type") == "agent-setting" and data.get("agentSetting") == COACH_AGENT


def _tool_character(data: Json) -> str | None:
    """The character a wow-coach tool call asked about, if this line is such a call."""
    if data.get("type") != "assistant":
        return None
    found: str | None = None
    for block in _blocks(_dict(data.get("message")).get("content")):
        name = block.get("name")
        if block.get("type") != "tool_use" or not isinstance(name, str) or "wow-coach" not in name:
            continue
        who = _dict(block.get("input")).get("character")
        if isinstance(who, str) and who.strip():
            found = who.strip()
    return found


# ---- which lines are real chat ------------------------------------------------------------


def _user_text(data: Json) -> str | None:
    """What the player typed on this line, or None when it is not a typed message."""
    if data.get("isMeta") is True:
        return None
    origin = _dict(data.get("origin")).get("kind")
    if isinstance(origin, str) and origin != "human":
        return None  # a notification or another agent, not the player
    content = _dict(data.get("message")).get("content")
    if isinstance(content, str):
        text = content
    else:
        blocks = _blocks(content)
        if any(block.get("type") == "tool_result" for block in blocks):
            return None
        pieces = [
            b["text"] for b in blocks if b.get("type") == "text" and isinstance(b.get("text"), str)
        ]
        text = "\n\n".join(str(piece) for piece in pieces)
    text = text.strip()
    if not text or text.startswith(_WRAPPER_PREFIXES):
        return None
    return text


def _assistant_text(data: Json) -> str:
    """The text blocks of an assistant line joined; empty for thinking and tool calls."""
    blocks = _blocks(_dict(data.get("message")).get("content"))
    pieces = [
        str(b["text"]).strip()
        for b in blocks
        if b.get("type") == "text" and isinstance(b.get("text"), str)
    ]
    return "\n\n".join(piece for piece in pieces if piece)


def _stable_id(data: Json, text: str) -> str:
    """``claude-code:<line uuid>``; a hash of the line's details when it has no uuid."""
    uuid = data.get("uuid")
    if isinstance(uuid, str) and uuid:
        return f"claude-code:{uuid}"
    basis = f"{data.get('sessionId')}|{data.get('timestamp')}|{data.get('type')}|{text[:200]}"
    return "claude-code:h" + hashlib.sha1(basis.encode(), usedforsecurity=False).hexdigest()[:20]


def _time_of(data: Json) -> str | None:
    stamp = data.get("timestamp")
    return stamp if isinstance(stamp, str) and parse_iso(stamp) is not None else None


def _user_message(data: Json, text: str) -> ChatMessage | None:
    at = _time_of(data)
    if at is None:
        return None
    return ChatMessage("user", text, _stable_id(data, text), at, "claude-code")


def _reply_message(reply: _Reply) -> ChatMessage | None:
    at = _time_of(reply.first)
    if at is None:
        return None
    text = "\n\n".join(reply.texts)
    model = _dict(reply.first.get("message")).get("model")
    return ChatMessage(
        "assistant",
        text,
        _stable_id(reply.first, text),
        at,
        "claude-code",
        provider="claude-code",
        model=model if isinstance(model, str) and model else None,
    )


def _extract_messages(
    records: list[_Record], *, hold_back: bool
) -> tuple[list[ChatMessage], int | None]:
    """The chat messages in ``records`` and, when the last reply may be unfinished, where to
    start reading next time (the start of that reply). None means everything was dealt with."""
    messages: list[ChatMessage] = []
    pending: _Reply | None = None

    def flush() -> None:
        nonlocal pending
        if pending is not None:
            item = _reply_message(pending)
            if item is not None:
                messages.append(item)
        pending = None

    for record in records:
        data = record.data
        if data.get("isSidechain") is True:
            continue
        kind = data.get("type")
        if kind == "assistant":
            raw_id = _dict(data.get("message")).get("id")
            message_id = raw_id if isinstance(raw_id, str) else ""
            if pending is not None and (not message_id or message_id != pending.message_id):
                flush()
            text = _assistant_text(data)
            if text and pending is None:
                pending = _Reply(message_id, data, start=record.start)
            if text and pending is not None:
                pending.texts.append(text)
        elif kind == "system" and data.get("subtype") == "turn_duration":
            flush()  # Claude Code writes this when a turn is over: the reply is finished
        elif kind == "user":
            typed = _user_text(data)
            if typed is not None:
                flush()
                item = _user_message(data, typed)
                if item is not None:
                    messages.append(item)
    if pending is not None and hold_back:
        return messages, pending.start
    flush()
    return messages, None


# ---- one transcript, and all of them ------------------------------------------------------


def _import_file(
    path: Path,
    state: _FileState,
    *,
    characters: Mapping[str, Character],
    data_dir: Path,
    hold_back: bool,
) -> tuple[int, set[str]]:
    """Read what is new in one transcript and store its chat. Updates ``state``."""
    records, end = _read_records(path, state.offset)
    if not state.coach:
        state.coach = any(_is_coach_setting(r.data) for r in records)
    if not state.coach:
        state.offset = end  # not a coach session (so far): do not read it again
        return 0, set()
    for record in records:
        state.character = _tool_character(record.data) or state.character
    chosen = pick_character(dict(characters), state.character) or pick_character(
        dict(characters), None
    )
    if chosen is None:
        return 0, set()
    messages, restart = _extract_messages(records, hold_back=hold_back)
    added = 0
    if messages:
        added = append_messages(conversation_file(data_dir, chosen.key), messages)
    state.offset = end if restart is None else restart
    return added, {chosen.key} if added else set()


def import_claude_chats(
    *,
    projects_dir: Path,
    data_dir: Path,
    characters: Mapping[str, Character],
    settle_seconds: float = SETTLE_SECONDS,
    now: float | None = None,
) -> ImportResult:
    """Import every new coach message from Claude Code's transcripts. Never raises on odd data.

    Args:
        projects_dir: Claude Code's ``projects`` folder (``claude_projects_dir``).
        data_dir: wow-coach's data folder.
        characters: The saved characters; a session's messages go to the one its tool calls
            asked about, else to the most recently saved one.
        settle_seconds: A transcript changed more recently than this keeps its last reply for
            the next pass, so a reply that is still being written is imported whole.
        now: The current time (Unix seconds); tests pass a fixed one.
    """
    if not characters:
        return ImportResult(0, ())  # nowhere to put the chats yet: try again later
    clock = time.time() if now is None else now
    state_path = data_dir / IMPORT_STATE_FILE
    states = _load_state(state_path)
    seen: dict[str, _FileState] = {}
    total = 0
    touched: set[str] = set()
    for path in _transcripts(projects_dir):
        name = str(path.relative_to(projects_dir))
        state = states.get(name, _FileState())
        try:
            size, modified = path.stat().st_size, path.stat().st_mtime
            if size < state.offset:
                state = _FileState()  # the file was replaced: start again
            if size > state.offset:
                added, keys = _import_file(
                    path,
                    state,
                    characters=characters,
                    data_dir=data_dir,
                    hold_back=clock - modified < settle_seconds,
                )
                total += added
                touched |= keys
        except OSError, ValueError, RecursionError:
            pass  # unreadable right now: leave its state as it was and try next time
        seen[name] = state
    _save_state(state_path, seen)
    return ImportResult(total, tuple(sorted(touched)))


def _transcripts(projects_dir: Path) -> list[Path]:
    try:
        return sorted(p for p in projects_dir.glob("*/*.jsonl") if p.is_file())
    except OSError:
        return []


# ---- the import state file ----------------------------------------------------------------


def _load_state(path: Path) -> dict[str, _FileState]:
    """What was remembered; a missing or damaged file means "nothing yet"."""
    try:
        if not path.is_file() or path.stat().st_size > MAX_STATE_BYTES:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError, RecursionError:
        return {}
    files = _dict(_dict(data).get("claude-code"))
    found: dict[str, _FileState] = {}
    for name, entry in files.items():
        info = _dict(entry)
        offset, who = info.get("offset"), info.get("character")
        found[name] = _FileState(
            offset=offset if isinstance(offset, int) and offset >= 0 else 0,
            coach=info.get("coach") is True,
            character=who if isinstance(who, str) else None,
        )
    return found


def _save_state(path: Path, states: dict[str, _FileState]) -> None:
    """Write the state in one step (temp file, rename). A failure only means a repeat read."""
    files = {
        name: {"offset": s.offset, "coach": s.coach, "character": s.character}
        for name, s in sorted(states.items())
    }
    text = json.dumps({"v": 1, "claude-code": files}, indent=1) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with locked(path):
            handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".import-", suffix=".part")
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as file:
                    file.write(text)
                Path(temp_name).replace(path)
            except BaseException:
                Path(temp_name).unlink(missing_ok=True)
                raise
    except OSError:
        return
