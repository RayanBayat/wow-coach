"""Turn saved character data into Markdown text that a coach can read at a glance.

Everything here is a *pure function*: text and numbers in, text out. No files, no
clock. The current time is passed in as ``now`` so tests can control it.

The addon may fail to read any section (a new game build can break an API), so every
section quietly disappears when its data is missing or empty.
"""

from typing import NamedTuple

from wow_coach.lua_table import LuaValue

type Table = dict[str | int, LuaValue]

STALE_AFTER_SECONDS = 30 * 60
QUALITY_NAMES = {0: "gray", 1: "white", 2: "green", 3: "blue", 4: "purple", 5: "orange"}
# Skills-tab headers, as the English game client names them. With another client
# language they don't match, and those lines simply show under Professions.
WEAPON_SKILLS_CATEGORY = "Weapon Skills"
LANGUAGES_CATEGORY = "Languages"

_MINUTE = 60
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR


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
    if seconds < _MINUTE:
        return "just now"
    if seconds < _HOUR:
        return f"{int(seconds // _MINUTE)} min ago"
    if seconds < _DAY:
        return f"{int(seconds // _HOUR)} h ago"
    days = int(seconds // _DAY)
    return f"{days} day ago" if days == 1 else f"{days} days ago"


# ---------------------------------------------------------------------------
# Safe readers: the data comes from a game addon, so never trust its shape.
# ---------------------------------------------------------------------------


def _number(value: LuaValue) -> int | float | None:
    """Return value if it is a real number (not a bool), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _text(value: LuaValue) -> str | None:
    return value if isinstance(value, str) and value else None


def _tables(value: LuaValue) -> list[Table]:
    """Return the dict items of a list (ignoring ``nil`` holes and junk)."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _table(value: LuaValue) -> Table:
    return value if isinstance(value, dict) else {}


def _number_text(value: float) -> str:
    """Show whole numbers without a trailing ``.0``."""
    return str(int(value)) if float(value).is_integer() else str(value)


# ---------------------------------------------------------------------------
# format_status: one function per section
# ---------------------------------------------------------------------------


def format_status(snapshot: Table, *, now: float) -> str:
    """Build the full Markdown status report for one character snapshot."""
    sections = [
        _header_section(snapshot, now),
        _xp_section(snapshot),
        _gold_section(snapshot),
        _location_section(snapshot),
        _bags_section(snapshot),
        _quests_section(snapshot),
        _talents_section(snapshot),
        _professions_section(snapshot),
        _weapon_skills_section(snapshot),
        _gear_section(snapshot),
        _spells_section(snapshot),
        _errors_section(snapshot),
    ]
    return "\n\n".join(section for section in sections if section)


def _header_section(snapshot: Table, now: float) -> str:
    name = _text(snapshot.get("name")) or "Unknown character"
    level = _number(snapshot.get("level"))
    description = [
        f"level {_number_text(level)}" if level is not None else None,
        _text(snapshot.get("race")),
        _text(snapshot.get("class")),
    ]
    line = f"# {name}"
    described = " ".join(part for part in description if part)
    if described:
        line += f": {described}"
    realm = _text(snapshot.get("realm"))
    if realm:
        line += f" ({realm})"

    lines = [line]
    saved_at = _number(snapshot.get("savedAt"))
    if saved_at is not None:
        reason = _text(snapshot.get("reason"))
        suffix = f" ({reason})" if reason else ""
        lines.append(f"Saved {format_age(now - saved_at)}{suffix}")
        if now - saved_at > STALE_AFTER_SECONDS:
            lines.append("WARNING: this data may be stale; type /coach in game to refresh.")
    return "\n".join(lines)


def _xp_section(snapshot: Table) -> str:
    xp = _number(snapshot.get("xp"))
    xp_max = _number(snapshot.get("xpMax"))
    if xp is None or not xp_max:
        return ""
    percent = round(100 * xp / xp_max)
    line = f"**XP:** {_number_text(xp)}/{_number_text(xp_max)} ({percent}%)"
    rested = _number(snapshot.get("restedXP"))
    if rested:
        line += f", rested XP {_number_text(rested)}"
    return line


def _gold_section(snapshot: Table) -> str:
    money = _number(snapshot.get("money"))
    return "" if money is None else f"**Gold:** {format_money(int(money))}"


def _location_section(snapshot: Table) -> str:
    place = ", ".join(
        part for part in (_text(snapshot.get("zone")), _text(snapshot.get("subZone"))) if part
    )
    x, y = _number(snapshot.get("x")), _number(snapshot.get("y"))
    if place and x is not None and y is not None:
        place += f" ({x:.1f}, {y:.1f})"
    elif x is not None and y is not None:
        place = f"({x:.1f}, {y:.1f})"
    hearth = _text(snapshot.get("hearth"))
    parts = [f"**Location:** {place}" if place else "", f"Hearth: {hearth}" if hearth else ""]
    return "\n".join(part for part in parts if part)


def _bags_section(snapshot: Table) -> str:
    bags = _table(snapshot.get("bags"))
    free, total = _number(bags.get("free")), _number(bags.get("total"))
    if free is None or total is None:
        return ""
    return f"**Bags:** {_number_text(free)}/{_number_text(total)} slots free"


def _quest_line(quest: Table) -> str:
    level = _number(quest.get("level"))
    prefix = f"[{_number_text(level)}] " if level is not None else ""
    title = _text(quest.get("title")) or "Untitled quest"
    if quest.get("complete") is True:
        return f"- {prefix}{title}, DONE (turn in)"
    objectives = [_text(o.get("text")) for o in _tables(quest.get("objectives"))]
    shown = ", ".join(text for text in objectives if text)
    return f"- {prefix}{title}, {shown}" if shown else f"- {prefix}{title}"


def _quests_section(snapshot: Table) -> str:
    quests = _tables(snapshot.get("quests"))
    if not quests:
        return ""
    return "\n".join(["**Quests:**", *(_quest_line(quest) for quest in quests)])


def _talents_section(snapshot: Table) -> str:
    talents = _table(snapshot.get("talents"))
    lines: list[str] = []
    unspent = _number(talents.get("unspent"))
    if unspent is not None:
        lines.append(f"Unspent points: {_number_text(unspent)}")
    trees = []
    for tree in _tables(talents.get("trees")):
        name, spent = _text(tree.get("name")), _number(tree.get("spent"))
        if name and spent is not None:
            trees.append(f"{name} {_number_text(spent)}")
    if trees:
        lines.append("Points per tree: " + ", ".join(trees))
    picked = []
    for talent in _tables(talents.get("picked")):
        name, rank = _text(talent.get("name")), _number(talent.get("rank"))
        max_rank = _number(talent.get("maxRank"))
        if name and rank is not None:
            ranks = _number_text(rank) + (f"/{_number_text(max_rank)}" if max_rank else "")
            picked.append(f"{name} {ranks}")
    if picked:
        lines.append("Picked: " + ", ".join(picked))
    return "\n".join(["**Talents:**", *(f"- {line}" for line in lines)]) if lines else ""


class _Skill(NamedTuple):
    name: str
    ranks: str  # e.g. "3/75"
    category: str | None  # the Skills-tab header it sat under; None in old snapshots


def _ranked_skills(snapshot: Table) -> list[_Skill]:
    """Return the saved skill lines worth showing, each name only once.

    Lines with maxRank 1 (armor types, magic schools) are left out: you either
    have them or not, there is nothing to level. The name check is for snapshots
    saved before the addon stopped saving each profession twice.
    """
    skills: list[_Skill] = []
    seen: set[str] = set()
    for skill in _tables(snapshot.get("professions")):
        name, rank = _text(skill.get("name")), _number(skill.get("rank"))
        max_rank = _number(skill.get("maxRank"))
        if not name or name in seen or rank is None or max_rank is None or max_rank <= 1:
            continue
        seen.add(name)
        ranks = f"{_number_text(rank)}/{_number_text(max_rank)}"
        skills.append(_Skill(name, ranks, _text(skill.get("category"))))
    return skills


def _professions_section(snapshot: Table) -> str:
    # Everything except weapon skills and languages. A skill without a category
    # (an old snapshot) lands here too, like it always did.
    lines = [
        f"- {skill.name}: {skill.ranks}"
        for skill in _ranked_skills(snapshot)
        if skill.category not in (WEAPON_SKILLS_CATEGORY, LANGUAGES_CATEGORY)
    ]
    return "\n".join(["**Professions:**", *lines]) if lines else ""


def _weapon_skills_section(snapshot: Table) -> str:
    weapons = [
        f"{skill.name} {skill.ranks}"
        for skill in _ranked_skills(snapshot)
        if skill.category == WEAPON_SKILLS_CATEGORY
    ]
    return f"**Weapon skills:** {', '.join(weapons)}" if weapons else ""


def _gear_line(item: Table) -> str:
    slot = _text(item.get("slot")) or "?"
    name = _text(item.get("name")) or "(unknown item)"
    details = []
    item_level = _number(item.get("itemLevel"))
    if item_level is not None:
        details.append(f"item level {_number_text(item_level)}")
    quality = _number(item.get("quality"))
    if quality is not None:
        details.append(QUALITY_NAMES.get(int(quality), f"quality {int(quality)}"))
    suffix = f" ({', '.join(details)})" if details else ""
    return f"- {slot}: {name}{suffix}"


def _gear_section(snapshot: Table) -> str:
    gear = _tables(snapshot.get("gear"))
    return "\n".join(["**Gear:**", *(_gear_line(item) for item in gear)]) if gear else ""


def _spells_section(snapshot: Table) -> str:
    spells = snapshot.get("spells")
    names = (
        [spell for spell in spells if isinstance(spell, str)] if isinstance(spells, list) else []
    )
    return f"**Spells:** {', '.join(names)}" if names else ""


def _errors_section(snapshot: Table) -> str:
    errors = snapshot.get("errors")
    messages = (
        [error for error in errors if isinstance(error, str)] if isinstance(errors, list) else []
    )
    if not messages:
        return ""
    return "\n".join(["**Addon read errors:**", *(f"- {message}" for message in messages)])


# ---------------------------------------------------------------------------
# format_history
# ---------------------------------------------------------------------------


def format_history(events: list[LuaValue], *, limit: int, now: float) -> str:
    """List the newest ``limit`` events first as ``- <age>: <text>``."""
    lines: list[str] = []
    for event in reversed(_tables(events)):
        if len(lines) >= limit:
            break
        text = _text(event.get("text")) or _text(event.get("kind")) or "(no description)"
        time = _number(event.get("time"))
        age = format_age(now - time) if time is not None else "unknown time"
        lines.append(f"- {age}: {text}")
    return "\n".join(lines) if lines else "No history recorded yet."
