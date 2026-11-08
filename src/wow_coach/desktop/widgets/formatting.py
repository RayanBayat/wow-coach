"""Turns numbers into the short friendly words the Coach page shows.

No Qt in here, so every rule is easy to test: money, "how old is the game data", and
"5 min ago".
"""

from dataclasses import dataclass
from typing import Final, Literal

type Level = Literal["success", "warning", "muted"]

MINUTE: Final = 60
HOUR: Final = 3_600
DAY: Final = 86_400
YEAR: Final = 365 * DAY
FRESH_BELOW_SECONDS: Final = 10 * MINUTE  # green: the data is recent
STALE_BELOW_SECONDS: Final = HOUR  # orange: getting old; older than this is grey


def gold_text(copper: int) -> str:
    """Money the way the game shows it: ``12g 34s 5c`` (parts that are zero are left out)."""
    gold, rest = divmod(max(copper, 0), 10_000)
    silver, copper_left = divmod(rest, 100)
    parts: list[str] = []
    if gold:
        parts.append(f"{gold}g")
    if gold or silver:
        parts.append(f"{silver}s")
    parts.append(f"{copper_left}c")
    return " ".join(parts)


def age_words(seconds: float) -> str:
    """A length of time in a few words: ``just now``, ``12 min``, ``3 h``, ``2 days``."""
    seconds = max(seconds, 0)
    if seconds < MINUTE:
        return "just now"
    if seconds < HOUR:
        return f"{int(seconds // MINUTE)} min"
    if seconds < DAY:
        return f"{int(seconds // HOUR)} h"
    if seconds >= YEAR:
        return "over a year"  # also covers broken clocks and very old answers
    days = int(seconds // DAY)
    return f"{days} day" if days == 1 else f"{days} days"


def relative_time(seconds_ago: float) -> str:
    """``just now``, ``12 min ago``, ``3 h ago``..."""
    words = age_words(seconds_ago)
    return words if words == "just now" else f"{words} ago"


@dataclass(frozen=True, slots=True)
class Freshness:
    """How fresh the game data is: the words for the pill and its color name."""

    text: str
    level: Level


def freshness(last_save: int | None, now: float) -> Freshness:
    """The freshness pill for a save made at ``last_save`` (Unix time), seen at ``now``."""
    if last_save is None:
        return Freshness("No game data yet", "muted")
    age = max(now - last_save, 0)
    words = age_words(age)
    text = "Game data: just now" if words == "just now" else f"Game data: {words} old"
    if age < FRESH_BELOW_SECONDS:
        return Freshness(text, "success")
    if age < STALE_BELOW_SECONDS:
        return Freshness(text, "warning")
    return Freshness(text, "muted")
