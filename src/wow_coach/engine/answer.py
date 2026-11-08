"""The AI's reply: the JSON shape we ask for, and reading it safely.

The AI should answer with ``title``, ``steps``, ``text`` and ``warnings``. A model can
still return plain prose or broken JSON, so reading never raises: it falls back to showing
the reply as text.
"""

import json
from typing import Final

from wow_coach.advice.contract import (
    MAX_STEP_CHARS,
    MAX_STEPS,
    MAX_TEXT_CHARS,
    MAX_TITLE_CHARS,
    MAX_WARNINGS,
    AdviceAnswer,
)
from wow_coach.advice.limits import limit_answer

FALLBACK_TITLE: Final = "Coach"

ANSWER_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": f"Short heading, at most {MAX_TITLE_CHARS}"},
        "steps": {
            "type": "array",
            "items": {"type": "string"},
            "description": f"The next 1 to 3 actions, in order (at most {MAX_STEPS})",
        },
        "text": {"type": "string", "description": "A short explanation; may be empty"},
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
            "description": f"Things to watch out for (at most {MAX_WARNINGS}); may be empty",
        },
    },
    "required": ["title", "steps", "text", "warnings"],
    "additionalProperties": False,
}

FENCE = "```"


def _unfenced(reply: str) -> str:
    """Remove a ```json fence some models add. Plain string checks: a regex was slow."""
    text = reply.strip()
    if len(text) < 2 * len(FENCE) or not (text.startswith(FENCE) and text.endswith(FENCE)):
        return text
    inner = text[len(FENCE) : -len(FENCE)]
    start = 0  # skip the language word after the opening fence ("json")
    while start < len(inner) and inner[start].isascii() and inner[start].isalpha():
        start += 1
    return inner[start:].strip()


def _strings(value: object) -> tuple[str, ...] | None:
    """The list as a tuple of non-empty strings, or None if it is not a list of strings."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return tuple(item.strip() for item in value if item.strip())


def _fallback(reply: str, *, answered_at: int, source: str) -> AdviceAnswer:
    """Show the reply as plain text under the title "Coach"."""
    return limit_answer(
        AdviceAnswer(
            answered_at=answered_at,
            source=source,
            title=FALLBACK_TITLE,
            text=reply.strip()[:MAX_TEXT_CHARS],
        )
    )


def _read_fields(data: object) -> tuple[str, tuple[str, ...], str, tuple[str, ...]] | None:
    """(title, steps, text, warnings) when ``data`` follows the schema, else None."""
    if not isinstance(data, dict):
        return None
    title, text = data.get("title"), data.get("text", "")
    steps, warnings = _strings(data.get("steps")), _strings(data.get("warnings", []))
    if not isinstance(title, str) or not isinstance(text, str):
        return None
    if steps is None or warnings is None or not title.strip():
        return None
    if not steps and not text.strip():
        return None  # nothing to show
    return title.strip(), steps, text.strip(), warnings


def parse_answer(reply: str, *, answered_at: int, source: str) -> AdviceAnswer:
    """Turn the AI's reply into an answer cut to the panel's limits. Never raises."""
    try:
        data = json.loads(_unfenced(reply))
    except ValueError, RecursionError:
        return _fallback(reply, answered_at=answered_at, source=source)
    fields = _read_fields(data)
    if fields is None:
        return _fallback(reply, answered_at=answered_at, source=source)
    title, steps, text, warnings = fields
    return limit_answer(
        AdviceAnswer(
            answered_at=answered_at,
            source=source,
            title=title,
            steps=tuple(step[:MAX_STEP_CHARS] for step in steps[:MAX_STEPS]),
            text=text,
            warnings=warnings[:MAX_WARNINGS],
        )
    )
