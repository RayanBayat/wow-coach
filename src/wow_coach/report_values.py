"""Small helpers shared by the report modules.

Two kinds:

* **Safe readers** (``as_number``, ``as_text``...). The data comes from a game addon,
  and a new game build can change or break any part of it, so we never trust its
  shape: each reader returns the value only if it has the expected type, else ``None``
  (or an empty list or table).
* **Formatters** for money, ages and durations, used in every report.
"""

from wow_coach.lua_table import LuaValue

type Table = dict[str | int, LuaValue]

MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------


def format_money(copper: int) -> str:
    """Format copper as ``1g 23s 45c`` (zero parts are left out, ``0c`` if all zero)."""
    gold, rest = divmod(copper, 10_000)
    silver, copper_left = divmod(rest, 100)
    parts = []
    if gold:
        parts.append(f"{gold}g")
    if silver:
        parts.append(f"{silver}s")
    if copper_left or not parts:
        parts.append(f"{copper_left}c")
    return " ".join(parts)


def format_age(seconds: float) -> str:
    """Describe an age in seconds: ``just now``, ``5 min ago``, ``2 h ago``, ``3 days ago``."""
    if seconds < MINUTE:
        return "just now"
    if seconds < HOUR:
        return f"{int(seconds // MINUTE)} min ago"
    if seconds < DAY:
        return f"{int(seconds // HOUR)} h ago"
    days = int(seconds // DAY)
    return f"{days} day ago" if days == 1 else f"{days} days ago"


def format_time_span(seconds: float) -> str:
    """Describe a length of time: ``2 d 3 h``, ``4 h 10 min``, ``25 min``, ``40 s``."""
    whole = max(int(seconds), 0)
    days, rest = divmod(whole, DAY)
    hours, rest = divmod(rest, HOUR)
    minutes, secs = divmod(rest, MINUTE)
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min"
    return f"{secs} s"


# ---------------------------------------------------------------------------
# Safe readers: the data comes from a game addon, so never trust its shape.
# ---------------------------------------------------------------------------


def as_number(value: LuaValue) -> int | float | None:
    """Return value if it is a real number (not a bool), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def as_text(value: LuaValue) -> str | None:
    """Return value if it is a non-empty string, else None."""
    return value if isinstance(value, str) and value else None


def as_texts(value: LuaValue) -> list[str]:
    """Return the non-empty strings of a list (ignoring anything else)."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def as_tables(value: LuaValue) -> list[Table]:
    """Return the dict items of a list (ignoring ``nil`` holes and junk)."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def as_table(value: LuaValue) -> Table:
    """Return value if it is a table with keys, else an empty one."""
    return value if isinstance(value, dict) else {}


# Forever's level cap. Below it, every level needs XP for the next one.
MAX_LEVEL = 60


def looks_unloaded(table: Table) -> bool:
    """True for a snapshot or progress point saved after the game unloaded the character.

    On a real logout (not ``/reload``) the game unloads most of the character before the
    addon's last chance to save. Addon 0.6.0 and older then saved an almost empty
    snapshot: no XP needed for the next level, no bag slots, a wrong level. A character
    in the world always has bag slots and, below the level cap, needs XP.
    """
    if as_number(as_table(table.get("bags")).get("total")) == 0:
        return True
    level = as_number(table.get("level"))
    return as_number(table.get("xpMax")) == 0 and level is not None and level < MAX_LEVEL


def number_text(value: float) -> str:
    """Show whole numbers without a trailing ``.0``."""
    return str(int(value)) if float(value).is_integer() else str(value)
