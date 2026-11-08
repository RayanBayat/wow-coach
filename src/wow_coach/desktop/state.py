"""The window's state as small typed objects, read from the core's plain dict.

``AppCore.state()`` returns a JSON-friendly dict (the browser window sends it as JSON). The Qt
pages would have to guess types from it, so ``read_state`` turns it into the objects below
once, in one place. Anything missing or of the wrong type gets a safe default, so a page can
always draw itself.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field


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
class QuestionView:
    """A question typed in the game's Coach panel that has no answer yet."""

    id: str
    text: str
    asked_at: int


@dataclass(frozen=True, slots=True)
class UsageView:
    """How many AI calls were made recently, and the player's own limits (0 = no limit)."""

    last_hour: int = 0
    last_day: int = 0
    hour_cap: int = 0
    day_cap: int = 0


@dataclass(frozen=True, slots=True)
class StateView:
    """Everything the window needs to draw itself."""

    signed_in: bool = False
    welcome_pending: bool = False
    settings: Mapping[str, object] = field(default_factory=dict)
    characters: tuple[str, ...] = ()
    selected: str | None = None
    answers: tuple[AnswerView, ...] = ()  # newest first
    open_questions: tuple[QuestionView, ...] = ()
    usage: UsageView = UsageView()
    last_save: int | None = None  # when the game last saved this character (Unix time)
    notify_available: bool = True
    speak_available: bool = True
    problem: str | None = None  # a plain sentence to show, or None


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
        open_questions=tuple(_question(q) for q in _mappings(raw.get("open_questions"))),
        usage=_usage(raw.get("usage")),
        last_save=_int_or_none(raw.get("last_save")),
        notify_available=alerts.get("notify") is not False,
        speak_available=alerts.get("speak") is not False,
        problem=problem if isinstance(problem, str) and problem else None,
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


def _question(raw: Mapping[str, object]) -> QuestionView:
    return QuestionView(
        id=_text(raw.get("id")),
        text=_text(raw.get("text")),
        asked_at=_int_or_none(raw.get("asked_at")) or 0,
    )


def _usage(raw: object) -> UsageView:
    if not isinstance(raw, Mapping):
        return UsageView()
    return UsageView(
        last_hour=_int_or_none(raw.get("last_hour")) or 0,
        last_day=_int_or_none(raw.get("last_day")) or 0,
        hour_cap=_int_or_none(raw.get("hour_cap")) or 0,
        day_cap=_int_or_none(raw.get("day_cap")) or 0,
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
