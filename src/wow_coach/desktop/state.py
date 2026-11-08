"""The window's state as small typed objects, read from the core's plain dict.

``AppCore.state()`` returns a JSON-friendly dict (the browser window sends it as JSON). The Qt
pages would have to guess types from it, so ``read_state`` turns it into the objects below
once, in one place. Anything missing or of the wrong type gets a safe default, so a page can
always draw itself.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

# How the chat names the AI behind an answer (ids are the ``provider`` field of a message).
PROVIDER_LABELS: Final = {"chatgpt": "ChatGPT", "claude-code": "your Claude coach"}


@dataclass(frozen=True, slots=True)
class AnswerView:
    """One answer from the coach, as the chat shows it."""

    title: str
    steps: tuple[str, ...]
    text: str
    warnings: tuple[str, ...]
    source: str
    answered_at: int
    question: str | None
    question_id: str | None


@dataclass(frozen=True, slots=True)
class MessageView:
    """One message of the chat history (see ``engine/conversation.py`` for the file format)."""

    id: str
    role: str  # "user" (the player) or "assistant" (a coach)
    content: str  # plain text, always present
    source: str  # "app", "game", "claude-code" or "outside"
    provider: str | None  # who answered: "chatgpt", "claude-code"... (None for the player)
    model: str | None
    seconds: float | None  # when it was said (Unix time), None when the line had no time
    answer: AnswerView | None  # the structured coach answer, when there is one


@dataclass(frozen=True, slots=True)
class QuestionView:
    """A question typed in the game's Coach panel that has no answer yet."""

    id: str
    text: str
    asked_at: int


@dataclass(frozen=True, slots=True)
class UsageView:
    """How many AI calls were made recently."""

    last_hour: int = 0
    last_day: int = 0


@dataclass(frozen=True, slots=True)
class CharacterView:
    """A short description of the shown character, for the Coach page's header."""

    name: str
    level: int | None = None
    race: str | None = None
    class_name: str | None = None
    zone: str | None = None
    money: int | None = None  # in copper


@dataclass(frozen=True, slots=True)
class StateView:
    """Everything the window needs to draw itself."""

    signed_in: bool = False
    welcome_pending: bool = False
    settings: Mapping[str, object] = field(default_factory=dict)
    characters: tuple[str, ...] = ()
    selected: str | None = None
    answers: tuple[AnswerView, ...] = ()  # newest first
    conversation: tuple[MessageView, ...] = ()  # the chat history, oldest first
    open_questions: tuple[QuestionView, ...] = ()
    usage: UsageView = UsageView()
    last_save: int | None = None  # when the game last saved this character (Unix time)
    notify_available: bool = True
    problem: str | None = None  # a plain sentence to show, or None
    character: CharacterView | None = None  # None when no character was saved yet


def read_state(raw: Mapping[str, object]) -> StateView:
    """Turn ``AppCore.state()``'s dict into a ``StateView``."""
    settings = raw.get("settings")
    alerts = raw.get("alerts")
    alerts = alerts if isinstance(alerts, Mapping) else {}
    problem = raw.get("problem")
    return StateView(
        signed_in=raw.get("signed_in") is True,
        welcome_pending=raw.get("welcome_pending") is True,
        settings=dict(settings) if isinstance(settings, Mapping) else {},
        characters=tuple(_strings(raw.get("characters"))),
        selected=_text_or_none(raw.get("selected")),
        answers=tuple(read_answer(a) for a in _mappings(raw.get("answers"))),
        conversation=tuple(
            message
            for message in (read_message(m) for m in _mappings(raw.get("conversation")))
            if message is not None
        ),
        open_questions=tuple(_question(q) for q in _mappings(raw.get("open_questions"))),
        usage=_usage(raw.get("usage")),
        last_save=_int_or_none(raw.get("last_save")),
        notify_available=alerts.get("notify") is not False,
        problem=problem if isinstance(problem, str) and problem else None,
        character=_character(raw.get("character")),
    )


def read_answer(raw: Mapping[str, object]) -> AnswerView:
    """One answer dict (``views.answer_to_json``) as an ``AnswerView``."""
    return AnswerView(
        title=_text(raw.get("title")),
        steps=tuple(_strings(raw.get("steps"))),
        text=_text(raw.get("text")),
        warnings=tuple(_strings(raw.get("warnings"))),
        source=_text(raw.get("source")),
        answered_at=_int_or_none(raw.get("answered_at")) or 0,
        question=_text_or_none(raw.get("question")),
        question_id=_text_or_none(raw.get("question_id")),
    )


def read_message(raw: Mapping[str, object]) -> MessageView | None:
    """One message dict (``views.message_to_json``) as a ``MessageView``; None if unusable."""
    role, content = raw.get("role"), raw.get("content")
    if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
        return None
    seconds = _seconds(raw.get("at"))
    provider = _text_or_none(raw.get("provider"))
    saved = raw.get("answer")
    answer = None
    if isinstance(saved, Mapping):
        answer = AnswerView(
            title=_text(saved.get("title")),
            steps=tuple(_strings(saved.get("steps"))),
            text=_text(saved.get("text")),
            warnings=tuple(_strings(saved.get("warnings"))),
            source=PROVIDER_LABELS.get(provider or "", provider or ""),
            answered_at=int(seconds or 0),
            question=None,
            question_id=None,
        )
    return MessageView(
        id=_text(raw.get("id")),
        role=str(role),
        content=content,
        source=_text(raw.get("source")) or "app",
        provider=provider,
        model=_text_or_none(raw.get("model")),
        seconds=seconds,
        answer=answer,
    )


def _seconds(value: object) -> float | None:
    """An ISO 8601 time as Unix seconds; None when it is missing or unreadable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp()


def _question(raw: Mapping[str, object]) -> QuestionView:
    return QuestionView(
        id=_text(raw.get("id")),
        text=_text(raw.get("text")),
        asked_at=_int_or_none(raw.get("asked_at")) or 0,
    )


def _character(raw: object) -> CharacterView | None:
    if not isinstance(raw, Mapping):
        return None
    return CharacterView(
        name=_text(raw.get("name")),
        level=_int_or_none(raw.get("level")),
        race=_text_or_none(raw.get("race")),
        class_name=_text_or_none(raw.get("class_name")),
        zone=_text_or_none(raw.get("zone")),
        money=_int_or_none(raw.get("money")),
    )


def _usage(raw: object) -> UsageView:
    if not isinstance(raw, Mapping):
        return UsageView()
    return UsageView(
        last_hour=_int_or_none(raw.get("last_hour")) or 0,
        last_day=_int_or_none(raw.get("last_day")) or 0,
    )


# ---- small readers: the right type, or a safe default ---------------------------------


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _strings(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str)]


def _mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, Mapping)]
