"""Turn saved character data into Markdown text that a coach can read at a glance.

Everything here is a *pure function*: text and numbers in, text out. No files, no
clock. The current time is passed in as ``now`` so tests can control it.

The addon may fail to read any section (a new game build can break an API), so every
section quietly disappears when its data is missing or empty.
"""

import itertools
import re
from typing import NamedTuple

from wow_coach import report_details, report_gear_hints, report_items
from wow_coach.lua_table import LuaValue
from wow_coach.report_values import (
    DAY,
    HOUR,
    MINUTE,
    Table,
    as_number,
    as_table,
    as_tables,
    as_text,
    format_age,
    format_money,
    looks_unloaded,
    number_text,
)

__all__ = [
    "Table",
    "format_age",
    "format_history",
    "format_money",
    "format_progress",
    "format_status",
]

STALE_AFTER_SECONDS = 30 * 60
# Skills-tab headers, as the English game client names them. With another client
# language they don't match, and those lines simply show under Professions.
WEAPON_SKILLS_CATEGORY = "Weapon Skills"
LANGUAGES_CATEGORY = "Languages"

# ---------------------------------------------------------------------------
# format_status: one function per section
# ---------------------------------------------------------------------------


def format_status(snapshot: Table, *, now: float) -> str:
    """Build the full Markdown status report for one character snapshot.

    The item sections live in ``report_items`` and the other new ones (stats, buffs,
    reputation...) in ``report_details``; this function puts them in reading order.
    """
    sections = [
        _header_section(snapshot, now),
        report_details.character_section(snapshot, now),
        _xp_section(snapshot),
        _gold_section(snapshot),
        _location_section(snapshot),
        report_details.stats_section(snapshot),
        report_details.auras_section(snapshot),
        _quests_section(snapshot),
        _talents_section(snapshot),
        _professions_section(snapshot),
        _weapon_skills_section(snapshot),
        _other_skills_section(snapshot),
        report_items.recipes_section(snapshot, now),
        report_items.gear_section(snapshot),
        report_items.bags_section(snapshot),
        report_gear_hints.gear_hints_section(snapshot),
        report_items.bank_section(snapshot, now),
        report_items.mail_section(snapshot, now),
        report_details.spells_section(snapshot),
        report_details.action_bars_section(snapshot),
        report_details.reputation_section(snapshot),
        report_details.currencies_section(snapshot),
        report_details.legacy_section(snapshot),
        report_details.group_section(snapshot),
        report_details.mounts_section(snapshot),
        _errors_section(snapshot),
    ]
    return "\n\n".join(section for section in sections if section)


def _header_section(snapshot: Table, now: float) -> str:
    name = as_text(snapshot.get("name")) or "Unknown character"
    level = as_number(snapshot.get("level"))
    description = [
        f"level {number_text(level)}" if level is not None else None,
        as_text(snapshot.get("race")),
        as_text(snapshot.get("class")),
    ]
    line = f"# {name}"
    described = " ".join(part for part in description if part)
    if described:
        line += f": {described}"
    realm = as_text(snapshot.get("realm"))
    if realm:
        line += f" ({realm})"

    lines = [line]
    saved_at = as_number(snapshot.get("savedAt"))
    if saved_at is not None:
        reason = as_text(snapshot.get("reason"))
        suffix = f" ({reason})" if reason else ""
        lines.append(f"Saved {format_age(now - saved_at)}{suffix}")
        if now - saved_at > STALE_AFTER_SECONDS:
            lines.append("WARNING: this data may be stale; type /coach in game to refresh.")
    # The addon keeps the last full snapshot when a logout finds the character unloaded.
    logged_out_at = as_number(snapshot.get("loggedOutAt"))
    if logged_out_at is not None:
        lines.append(
            f"Logged out {format_age(now - logged_out_at)}; "
            "this is the last full save, from before that."
        )
    if looks_unloaded(snapshot):
        lines.append(
            "WARNING: this save is almost empty: the game had already unloaded the character "
            "when it was written (a logout with addon 0.6.0 or older). Level, gold, bags and "
            "stats below are wrong; type /coach in game for a full save."
        )
    return "\n".join(lines)


def _xp_section(snapshot: Table) -> str:
    xp = as_number(snapshot.get("xp"))
    xp_max = as_number(snapshot.get("xpMax"))
    if xp is None or not xp_max:
        return ""
    percent = round(100 * xp / xp_max)
    line = f"**XP:** {number_text(xp)}/{number_text(xp_max)} ({percent}%)"
    rested = as_number(snapshot.get("restedXP"))
    if rested:
        line += f", rested XP {number_text(rested)}"
    return line


def _gold_section(snapshot: Table) -> str:
    money = as_number(snapshot.get("money"))
    return "" if money is None else f"**Gold:** {format_money(int(money))}"


def _location_section(snapshot: Table) -> str:
    place = ", ".join(
        part for part in (as_text(snapshot.get("zone")), as_text(snapshot.get("subZone"))) if part
    )
    x, y = as_number(snapshot.get("x")), as_number(snapshot.get("y"))
    if place and x is not None and y is not None:
        place += f" ({x:.1f}, {y:.1f})"
    elif x is not None and y is not None:
        place = f"({x:.1f}, {y:.1f})"
    hearth = as_text(snapshot.get("hearth"))
    instance = as_table(snapshot.get("instance"))
    inside = as_text(instance.get("name"))
    if inside and (kind := as_text(instance.get("type"))):
        inside += f" ({kind})"
    parts = [
        f"**Location:** {place}" if place else "",
        f"Inside: {inside}" if inside else "",
        f"Hearth: {hearth}" if hearth else "",
    ]
    return "\n".join(part for part in parts if part)


def _quest_line(quest: Table) -> str:
    level = as_number(quest.get("level"))
    prefix = f"[{number_text(level)}] " if level is not None else ""
    title = as_text(quest.get("title")) or "Untitled quest"
    tags = []
    # The ID tells apart quests with the same title (Classic vs Retail pages on the wiki).
    if (quest_id := as_number(quest.get("questID"))) is not None:
        tags.append(f"quest {number_text(quest_id)}")
    if quest.get("failed") is True:
        tags.append("FAILED")
    if (group := as_number(quest.get("suggestedGroup"))) is not None:
        tags.append(f"group quest for {number_text(group)}")
    if zone := as_text(quest.get("zone")):
        tags.append(zone)
    title += f" ({'; '.join(tags)})" if tags else ""
    if quest.get("complete") is True:
        line = f"- {prefix}{title}, DONE (turn in)"
    else:
        objectives = [_objective_text(o) for o in as_tables(quest.get("objectives"))]
        shown = ", ".join(text for text in objectives if text)
        line = f"- {prefix}{title}, {shown}" if shown else f"- {prefix}{title}"
    # The short "Bring 10 ... to ... in Brill." text: it names who to hand the quest in to.
    if goal := as_text(quest.get("objectivesText")):
        line += f"\n  - Goal: {' '.join(goal.split())}"
    return line


def _objective_text(objective: Table) -> str:
    """One objective, e.g. "0/3 Vile Fin Murloc Skin".

    Right after logging in, the game can save an objective before it knows the item's name
    ("0/3"). Say so, so a reader (or an AI) doesn't guess what is missing or think it is done.
    """
    text = as_text(objective.get("text")) or ""
    if re.fullmatch(r"\s*\d+\s*/\s*\d+\s*", text):
        return f"{text.strip()} (the game had not loaded this item's name yet)"
    return text


def _quests_section(snapshot: Table) -> str:
    quests = as_tables(snapshot.get("quests"))
    lines = [_quest_line(quest) for quest in quests]
    completed = as_number(snapshot.get("completedQuests"))
    if completed is not None:
        lines.append(f"Quests completed so far (all time): {number_text(completed)}")
    return "\n".join(["**Quests:**", *lines]) if lines else ""


def _talents_section(snapshot: Table) -> str:
    talents = as_table(snapshot.get("talents"))
    lines: list[str] = []
    unspent = as_number(talents.get("unspent"))
    if unspent is not None:
        lines.append(f"Unspent points: {number_text(unspent)}")
    trees = []
    for tree in as_tables(talents.get("trees")):
        name, spent = as_text(tree.get("name")), as_number(tree.get("spent"))
        if name and spent is not None:
            trees.append(f"{name} {number_text(spent)}")
    if trees:
        lines.append("Points per tree: " + ", ".join(trees))
    picked = []
    for talent in as_tables(talents.get("picked")):
        name, rank = as_text(talent.get("name")), as_number(talent.get("rank"))
        max_rank = as_number(talent.get("maxRank"))
        if name and rank is not None:
            ranks = number_text(rank) + (f"/{number_text(max_rank)}" if max_rank else "")
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
    for skill in as_tables(snapshot.get("professions")):
        name, rank = as_text(skill.get("name")), as_number(skill.get("rank"))
        max_rank = as_number(skill.get("maxRank"))
        if not name or name in seen or rank is None or max_rank is None or max_rank <= 1:
            continue
        seen.add(name)
        ranks = f"{number_text(rank)}/{number_text(max_rank)}"
        skills.append(_Skill(name, ranks, as_text(skill.get("category"))))
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


def _other_skills_section(snapshot: Table) -> str:
    """Languages and the skills you simply have (armor types, magic schools...).

    Grouped by their Skills-tab header: ``Languages: Orcish 300/300; Armor: Cloth``.
    """
    groups: dict[str, list[str]] = {}
    seen: set[str] = set()
    for skill in as_tables(snapshot.get("professions")):
        name = as_text(skill.get("name"))
        rank, max_rank = as_number(skill.get("rank")), as_number(skill.get("maxRank"))
        category = as_text(skill.get("category"))
        is_simple = max_rank is not None and max_rank <= 1
        if not name or name in seen or not (is_simple or category == LANGUAGES_CATEGORY):
            continue
        seen.add(name)
        shown = name
        if not is_simple and rank is not None and max_rank is not None:
            shown += f" {number_text(rank)}/{number_text(max_rank)}"
        groups.setdefault(category or "Other", []).append(shown)
    parts = [f"{category}: {', '.join(names)}" for category, names in groups.items()]
    return f"**Other skills:** {'; '.join(parts)}" if parts else ""


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
    for event in reversed(as_tables(events)):
        if len(lines) >= limit:
            break
        text = as_text(event.get("text")) or as_text(event.get("kind")) or "(no description)"
        time = as_number(event.get("time"))
        age = format_age(now - time) if time is not None else "unknown time"
        lines.append(f"- {age}: {text}")
    return "\n".join(lines) if lines else "No history recorded yet."


# ---------------------------------------------------------------------------
# format_progress: what happened over the last days, from the progress log
# ---------------------------------------------------------------------------

# Save points closer together than this belong to the same play session.
SESSION_GAP_SECONDS = 30 * MINUTE


class _Session(NamedTuple):
    """One stretch of play: the save points inside it and when it began."""

    start: float  # the login time if the history knows it, else the first save point
    points: list[Table]

    @property
    def end(self) -> float:
        return _point_time(self.points[-1])

    @property
    def seconds(self) -> float:
        return self.end - self.start


class _Gain(NamedTuple):
    """How much a character gained between two moments."""

    levels: int
    xp: int
    money: int


def _point_time(point: Table) -> float:
    """The time of a progress point (points without a usable time are dropped earlier)."""
    return float(as_number(point.get("time")) or 0)


def _sorted_points(progress: list[LuaValue]) -> list[Table]:
    """The progress points that have a time, oldest first.

    Points saved after the game unloaded the character are left out: their zeros would
    look like lost levels and gold.
    """
    usable = [
        point
        for point in as_tables(progress)
        if as_number(point.get("time")) is not None and not looks_unloaded(point)
    ]
    return sorted(usable, key=_point_time)


def _login_times(history: list[LuaValue]) -> list[float]:
    """When the player logged in, from the history, oldest first."""
    times = [
        float(time)
        for event in as_tables(history)
        if event.get("kind") == "login" and (time := as_number(event.get("time"))) is not None
    ]
    return sorted(times)


def _make_session(group: list[Table], previous_end: float, logins: list[float]) -> _Session:
    """Build a session. It starts at the first login after the previous session ended.

    A session usually has only one save point (the one made at logout), so the login
    time is what tells us how long the player really played. Without a login event we
    fall back to the first save point.
    """
    first_time = _point_time(group[0])
    after_previous = [login for login in logins if previous_end < login <= first_time]
    return _Session(after_previous[0] if after_previous else first_time, group)


def _split_sessions(points: list[Table], logins: list[float]) -> list[_Session]:
    """Group the points into play sessions: a gap of 30 minutes or more starts a new one."""
    sessions: list[_Session] = []
    group: list[Table] = []
    previous_end = float("-inf")
    for point in points:
        if group and _point_time(point) - _point_time(group[-1]) >= SESSION_GAP_SECONDS:
            sessions.append(_make_session(group, previous_end, logins))
            previous_end = _point_time(group[-1])
            group = []
        group.append(point)
    sessions.append(_make_session(group, previous_end, logins))
    return sessions


def _difference(before: LuaValue, after: LuaValue) -> int | None:
    """``after - before`` when both are numbers, else None."""
    number_before, number_after = as_number(before), as_number(after)
    if number_before is None or number_after is None:
        return None
    return int(number_after - number_before)


def _gain_between(before: Table, after: Table) -> _Gain:
    """What was gained from one point to the next (a level-up carries the leftover XP over)."""
    levels = _difference(before.get("level"), after.get("level")) or 0
    xp = _difference(before.get("xp"), after.get("xp")) or 0
    if levels > 0:
        # XP restarts at 0 on a level-up: what was left of the old level, plus the new XP.
        left_in_level = _difference(before.get("xp"), before.get("xpMax")) or 0
        xp = left_in_level + int(as_number(after.get("xp")) or 0)
    money = _difference(before.get("money"), after.get("money")) or 0
    return _Gain(max(levels, 0), max(int(xp), 0), money)


def _total_gain(points: list[Table]) -> _Gain:
    """Add up the gains between every two neighbouring points."""
    gains = [_gain_between(a, b) for a, b in itertools.pairwise(points)]
    return _Gain(
        sum(gain.levels for gain in gains),
        sum(gain.xp for gain in gains),
        sum(gain.money for gain in gains),
    )


def _signed_money(copper: int) -> str:
    if copper == 0:
        return "no change"
    sign = "+" if copper > 0 else "-"
    return f"{sign}{format_money(abs(copper))}"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _format_duration(seconds: float) -> str:
    """``2 h 10 min``; anything under half a minute is ``under 1 min``."""
    minutes = round(seconds / MINUTE)
    if minutes < 1:
        return "under 1 min"
    hours, rest = divmod(minutes, 60)
    if hours == 0:
        return f"{rest} min"
    return f"{hours} h {rest} min" if rest else f"{hours} h"


def _count_events(history: list[LuaValue], kind: str, start: float, end: float) -> int:
    """How many history events of this kind happened after ``start``, up to ``end``."""
    return sum(
        1
        for event in as_tables(history)
        if event.get("kind") == kind
        and (time := as_number(event.get("time"))) is not None
        and start < time <= end
    )


def _place(point: Table) -> str:
    """``level 8 in Brill, Tirisfal Glades`` from a progress point."""
    parts = [text for key in ("subZone", "zone") if (text := as_text(point.get(key)))]
    level = as_number(point.get("level"))
    level_text = f"level {number_text(level)}" if level is not None else "level unknown"
    return f"{level_text} in {', '.join(parts)}" if parts else level_text


def _gain_lines(gain: _Gain, first: Table, last: Table) -> list[str]:
    """Bullet lines for levels, XP and gold."""
    lines = []
    level_before, level_after = as_number(first.get("level")), as_number(last.get("level"))
    if level_before is not None and level_after is not None:
        if gain.levels:
            levels = f"level {number_text(level_before)} to {number_text(level_after)}"
            lines.append(f"- Levels: {levels} (+{gain.levels})")
        else:
            lines.append(f"- Levels: still level {number_text(level_after)}")
    lines.append(f"- XP gained: about {gain.xp}")
    lines.append(f"- Gold: {_signed_money(gain.money)}")
    return lines


def _window_section(
    sessions: list[_Session],
    points: list[Table],
    history: list[LuaValue],
    now: float,
    days: int,
) -> str:
    """The 'last N days' block: sessions, play time, gains, quests and deaths."""
    cutoff = now - days * DAY
    title = f"**Last {_plural(days, 'day')}:**"
    recent = [session for session in sessions if session.end >= cutoff]
    if not recent:
        return f"{title} no play recorded."
    older = [point for point in points if _point_time(point) < cutoff]
    inside = [point for point in points if _point_time(point) >= cutoff]
    # The last point before the window is where the window's gains start from.
    measured = [*older[-1:], *inside]
    gain = _total_gain(measured)
    play_seconds = sum(session.seconds for session in recent)
    lines = [
        f"{title} {_plural(len(recent), 'play session')}, "
        f"about {_format_duration(play_seconds)} of play",
        *_gain_lines(gain, measured[0], measured[-1]),
    ]
    if play_seconds >= MINUTE:
        lines.append(f"- XP per hour of play: about {round(gain.xp / (play_seconds / HOUR))}")
    lines.append(f"- Quests turned in: {_count_events(history, 'quest', cutoff, now)}")
    lines.append(f"- Deaths: {_count_events(history, 'death', cutoff, now)}")
    return "\n".join(lines)


def _previous_session_section(sessions: list[_Session], history: list[LuaValue], now: float) -> str:
    """What the latest session achieved, compared with where the one before it ended."""
    if len(sessions) < 2:
        return "**Since the previous session:** this is the only play session recorded so far."
    previous, latest = sessions[-2], sessions[-1]
    start_point = previous.points[-1]
    gain = _total_gain([start_point, *latest.points])
    return "\n".join(
        [
            f"**Since the previous session** (it ended {format_age(now - previous.end)}, "
            f"at {_place(start_point)}):",
            *_gain_lines(gain, start_point, latest.points[-1]),
            f"- Quests turned in: {_count_events(history, 'quest', previous.end, latest.end)}",
            f"- Deaths: {_count_events(history, 'death', previous.end, latest.end)}",
        ]
    )


def format_progress(
    progress: list[LuaValue], history: list[LuaValue], *, now: float, days: int = 7
) -> str:
    """Describe a character's recent progress in plain words.

    Uses the addon's progress points (one per save) and the history (logins, quests,
    deaths). Play time is an estimate: a session runs from the login to the last save.

    Args:
        progress: The character's progress points, as the addon wrote them.
        history: The character's history events.
        now: The current Unix time.
        days: How many days back the summary looks (at least 1).
    """
    points = _sorted_points(progress)
    if not points:
        return (
            "No progress recorded yet. The addon adds a progress point every time the "
            "character is saved (logout, /reload or /coach), so type /coach in game."
        )
    days = max(days, 1)
    sessions = _split_sessions(points, _login_times(history))
    last = points[-1]
    return "\n\n".join(
        [
            f"**Last played:** {format_age(now - _point_time(last))}, {_place(last)}.",
            _window_section(sessions, points, history, now, days),
            _previous_session_section(sessions, history, now),
        ]
    )
