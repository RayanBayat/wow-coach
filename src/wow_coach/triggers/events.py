"""Compare two saves of one character and say what happened in between.

``events_between`` is the only public function. It never asks the AI anything and never
raises on odd data: the saves come from a game addon, so any field can be missing or wrong.
"""

import re
from typing import Final

from wow_coach.report_gear_hints import gear_hints_section
from wow_coach.report_values import (
    Table,
    as_number,
    as_table,
    as_tables,
    as_text,
    looks_unloaded,
    number_text,
)
from wow_coach.savedvars import Character
from wow_coach.triggers.contract import Event, EventKind

# A first save (nothing to compare with) only reports things from the last 10 minutes,
# so restarting the app does not replay old deaths.
FIRST_SAVE_WINDOW_SECONDS: Final = 600
BAGS_FULL_AT: Final = 2  # "nearly full" = this many free slots or fewer
DURABILITY_LOW_PERCENT: Final = 25
DEATH_LOOP_SECONDS: Final = 300  # the addon only stores secondsSinceRevive up to this
MAX_SUMMARY_CHARS: Final = 240
MAX_LISTED_NAMES: Final = 3
_UPGRADE_PREFIX: Final = "- Possible upgrade: "
_CANT_USE_PREFIX: Final = "- Can't use: "
_CONTROL_CHARS: Final = re.compile(r"[\x00-\x1f\x7f]")


def events_between(before: Character | None, after: Character, *, now: int) -> list[Event]:
    """What happened between two saves of the same character.

    Args:
        before: The previous save, or None the first time the app sees this character.
        after: The newest save.
        now: The current Unix time.

    Returns:
        Events, in the order they are looked for. Empty when nothing changed.
    """
    since = _since(before, now)
    events = _history_events(after, since)
    if before is not None and not _unloaded(before, after):
        events += _snapshot_events(before, after, now)
    return events


def _since(before: Character | None, now: int) -> float:
    """History events must be newer than this Unix time to count."""
    saved_at = as_number(before.snapshot.get("savedAt")) if before is not None else None
    if saved_at is None:
        return now - FIRST_SAVE_WINDOW_SECONDS
    return saved_at


def _unloaded(before: Character, after: Character) -> bool:
    """True when a save was made while the game had unloaded the character (empty bags...)."""
    return looks_unloaded(before.snapshot) or looks_unloaded(after.snapshot)


def _save_time(after: Character, now: int) -> int:
    saved_at = as_number(after.snapshot.get("savedAt"))
    return int(saved_at) if saved_at is not None else now


def _clean(text: str) -> str:
    """One line, no control characters, not too long."""
    text = " ".join(_CONTROL_CHARS.sub(" ", text).split())
    return text if len(text) <= MAX_SUMMARY_CHARS else text[: MAX_SUMMARY_CHARS - 3] + "..."


# ---------------------------------------------------------------------------
# History events: deaths and level-ups
# ---------------------------------------------------------------------------


def _history_events(after: Character, since: float) -> list[Event]:
    """Deaths and level-ups the addon wrote down after ``since``."""
    events: list[Event] = []
    level_times: list[int] = []
    for entry in as_tables(after.history):
        time = as_number(entry.get("time"))
        if time is None or time <= since:
            continue
        kind = as_text(entry.get("kind"))
        if kind == "death":
            events += _death_events(after.key, entry, int(time))
        elif kind == "level":
            level_times.append(int(time))
    if level_times:
        level = as_number(after.snapshot.get("level"))
        text = f"Reached level {number_text(level)}." if level is not None else "Leveled up."
        events.append(Event("level_up", after.key, max(level_times), text))
    return events


def _death_events(key: str, entry: Table, time: int) -> list[Event]:
    events = [Event("died", key, time, _death_summary(entry))]
    seconds = as_number(entry.get("secondsSinceRevive"))
    if seconds is not None and 0 <= seconds <= DEATH_LOOP_SECONDS:
        text = f"Died again {number_text(int(seconds))} seconds after coming back."
        events.append(Event("died_again_soon", key, time, text))
    return events


def _death_summary(entry: Table) -> str:
    """The death text without the long parts, and without other players' names."""
    text = as_text(entry.get("text")) or "Died."
    # Keep "Died in X (level N)." and "Attacked by ...". The killing blow and the
    # "40 s after coming back" parts are too long for one short sentence.
    sentences = text.split(". ")
    kept = [
        s for s in sentences if not s.startswith("Killing blow") and not re.match(r"\d+ s after", s)
    ]
    summary = ". ".join(kept)
    for name in _player_attacker_names(entry):
        summary = summary.replace(name, "a player")
    return _clean(summary if summary.endswith(".") else summary + ".")


def _player_attacker_names(entry: Table) -> list[str]:
    """Names of attackers (and the killer) that are other players, longest first."""
    names = [
        name
        for attacker in as_tables(entry.get("attackers"))
        if attacker.get("isPlayer") is True and (name := as_text(attacker.get("name")))
    ]
    killer = as_text(as_table(entry.get("killer")).get("name"))
    if killer and killer in names:
        names.append(killer)
    return sorted(set(names), key=len, reverse=True)


# ---------------------------------------------------------------------------
# Snapshot events: need an earlier save to compare with
# ---------------------------------------------------------------------------


def _snapshot_events(before: Character, after: Character, now: int) -> list[Event]:
    at = _save_time(after, now)
    old, new = before.snapshot, after.snapshot
    reported = _has_level_history(after, old)
    found: list[tuple[EventKind, str | None]] = [
        ("level_up", None if reported else _level_rise(old, new)),
        ("quest_done", _quests_done(old, new)),
        ("bags_nearly_full", _bags_full(old, new)),
        ("new_zone", _zone_change(old, new)),
        ("talent_points", _talent_points(old, new)),
        ("gear_hint", _gear_hint(old, new)),
        ("durability_low", _durability(old, new)),
    ]
    return [Event(kind, after.key, at, _clean(text)) for kind, text in found if text]


def _has_level_history(after: Character, old: Table) -> bool:
    """True when a level event newer than the old save was already reported from history."""
    since = as_number(old.get("savedAt"))
    for entry in as_tables(after.history):
        time = as_number(entry.get("time"))
        is_level = as_text(entry.get("kind")) == "level" and time is not None
        if is_level and (since is None or (time is not None and time > since)):
            return True
    return False


def _level_rise(old: Table, new: Table) -> str | None:
    level_before, level_now = as_number(old.get("level")), as_number(new.get("level"))
    if level_before is None or level_now is None or level_now <= level_before:
        return None
    return f"Reached level {number_text(level_now)}."


def _quest_id(quest: Table) -> str | None:
    """An identity for a quest: its id, else its title."""
    quest_id = as_number(quest.get("questID"))
    return str(int(quest_id)) if quest_id is not None else as_text(quest.get("title"))


def _complete_quest_ids(snapshot: Table) -> set[str]:
    return {
        ident
        for quest in as_tables(snapshot.get("quests"))
        if quest.get("complete") is True and (ident := _quest_id(quest))
    }


def _quests_done(old: Table, new: Table) -> str | None:
    newly = _complete_quest_ids(new) - _complete_quest_ids(old)
    titles = [
        as_text(quest.get("title")) or "A quest"
        for quest in as_tables(new.get("quests"))
        if _quest_id(quest) in newly
    ]
    if not titles:
        return None
    return f"Ready to turn in: {_name_list(titles)}."


def _name_list(names: list[str]) -> str:
    """'A, B, C' or 'A, B, C and 2 more'."""
    shown = ", ".join(names[:MAX_LISTED_NAMES])
    extra = len(names) - MAX_LISTED_NAMES
    return f"{shown} and {extra} more" if extra > 0 else shown


def _free_slots(snapshot: Table) -> int | float | None:
    return as_number(as_table(snapshot.get("bags")).get("free"))


def _bags_full(old: Table, new: Table) -> str | None:
    free_now, free_before = _free_slots(new), _free_slots(old)
    if free_now is None or free_before is None:
        return None
    if free_now <= BAGS_FULL_AT < free_before:
        return f"Bags are nearly full: {number_text(free_now)} free slots left."
    return None


def _zone_change(old: Table, new: Table) -> str | None:
    zone_before, zone_now = as_text(old.get("zone")), as_text(new.get("zone"))
    if zone_before and zone_now and zone_before != zone_now:
        return f"Now in {zone_now}."
    return None


def _unspent(snapshot: Table) -> int | float:
    return as_number(as_table(snapshot.get("talents")).get("unspent")) or 0


def _talent_points(old: Table, new: Table) -> str | None:
    unspent_now = _unspent(new)
    if unspent_now > 0 and unspent_now > _unspent(old):
        return f"You have {number_text(unspent_now)} unspent talent points."
    return None


def _hint_lines(snapshot: Table) -> list[str]:
    """The upgrade and can't-use lines of the report's gear hints."""
    try:
        section = gear_hints_section(snapshot)
    except TypeError, ValueError, KeyError, AttributeError:
        return []  # odd data in the save: no hint is better than a crash
    prefixes = (_UPGRADE_PREFIX, _CANT_USE_PREFIX)
    return [line for line in section.splitlines() if line.startswith(prefixes)]


def _item_name(line: str, prefix: str) -> str:
    """The item name in a hint line, without its details in brackets."""
    return line.removeprefix(prefix).split(" (", 1)[0].strip() or "an item"


def _gear_hint(old: Table, new: Table) -> str | None:
    known = set(_hint_lines(old))
    fresh = [line for line in _hint_lines(new) if line not in known]
    upgrades = [_item_name(x, _UPGRADE_PREFIX) for x in fresh if x.startswith(_UPGRADE_PREFIX)]
    unusable = [_item_name(x, _CANT_USE_PREFIX) for x in fresh if x.startswith(_CANT_USE_PREFIX)]
    parts = []
    if upgrades:
        parts.append(f"Possible upgrade in your bags: {_name_list(upgrades)}")
    if unusable:
        parts.append(f"can't use yet: {_name_list(unusable)}")
    return "; ".join(parts) + "." if parts else None


def _durability_percent(item: Table) -> float | None:
    current, maximum = as_number(item.get("durability")), as_number(item.get("durabilityMax"))
    if current is None or maximum is None or maximum <= 0:
        return None
    return 100 * current / maximum


def _low_slots(snapshot: Table) -> dict[str, float]:
    """Worn slots under the limit, with their percent."""
    low = {}
    for item in as_tables(snapshot.get("gear")):
        percent = _durability_percent(item)
        slot = as_text(item.get("slot"))
        if slot and percent is not None and percent < DURABILITY_LOW_PERCENT:
            low[slot] = percent
    return low


def _durability(old: Table, new: Table) -> str | None:
    was_low = _low_slots(old)
    fresh = {slot: pct for slot, pct in _low_slots(new).items() if slot not in was_low}
    if not fresh:
        return None
    shown = [f"{slot} {number_text(round(pct))}%" for slot, pct in fresh.items()]
    return f"Worn gear needs repair: {_name_list(shown)}."
