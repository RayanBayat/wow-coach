"""Turn events into decisions using the player's rules.

Order of the checks for one event:

1. The player's mode for that kind of event (off, notify or coach).
2. Quiet: inside a dungeon or raid, or during the quiet hours, nothing unasked happens.
3. Cooldown: after an unasked "coach" answer, the next one only becomes a notification.

Then all "coach" decisions of one save are merged, so one save costs at most one AI call.
A question the player asked (kind ``asked``) skips all of this: it is always answered.
"""

import math
from collections.abc import Sequence
from dataclasses import replace
from typing import Final

from wow_coach.triggers.contract import Decision, Event, EventKind, Mode, TriggerSettings
from wow_coach.triggers.state import TriggerState

SECONDS_PER_MINUTE: Final = 60

# Plain names for the reasons shown to the player.
KIND_LABELS: Final[dict[EventKind, str]] = {
    "asked": "questions",
    "died": "deaths",
    "died_again_soon": "dying again soon",
    "level_up": "level-ups",
    "quest_done": "finished quests",
    "bags_nearly_full": "full bags",
    "new_zone": "new zones",
    "talent_points": "talent points",
    "gear_hint": "gear hints",
    "durability_low": "worn gear",
    "timer": "the timer",
}


def decide(
    events: Sequence[Event],
    settings: TriggerSettings,
    *,
    state: TriggerState,
    now: int,
    in_instance: bool,
    local_hour: int,
    character_key: str | None = None,
) -> list[Decision]:
    """One decision per event (plus one for the timer when it is due).

    Args:
        events: What ``events_between`` found in one save.
        settings: The player's rules.
        state: What was remembered (cooldown and timer times).
        now: The current Unix time.
        in_instance: True while the character is inside a dungeon or raid.
        local_hour: The hour of the day on the player's clock, 0-23.
        character_key: Whose save this is. Only needed so the timer can fire when
            ``events`` is empty; otherwise it is taken from the first event.

    Returns:
        Decisions in the same order as the events. Several "coach" decisions mean ONE
        request: use ``coach_request_for`` on them and call the engine once.
    """
    everything = list(events) + _timer_events(events, settings, state, now, character_key)
    quiet_reason = _quiet_reason(settings, in_instance, local_hour)
    decisions = [_decide_one(event, settings, state, now, quiet_reason) for event in everything]
    decisions = _drop_double_death(decisions, settings)
    return _merge_coach(decisions)


def _timer_events(
    events: Sequence[Event],
    settings: TriggerSettings,
    state: TriggerState,
    now: int,
    character_key: str | None,
) -> list[Event]:
    """The timer event when the timer is on and its time has come."""
    key = character_key or (events[0].character_key if events else None)
    if key is None or settings.every_minutes <= 0 or settings.modes.get("timer") == "off":
        return []
    if now - state.last_timer_at < settings.every_minutes * SECONDS_PER_MINUTE:
        return []
    return [Event("timer", key, now, f"It has been {settings.every_minutes} minutes.")]


def _quiet_reason(settings: TriggerSettings, in_instance: bool, local_hour: int) -> str | None:
    """Why nothing unasked may happen right now, or None."""
    if settings.quiet_in_instances and in_instance:
        return "quiet in dungeons and raids"
    if _in_quiet_hours(settings, local_hour):
        return f"quiet hours ({settings.quiet_from_hour}:00 to {settings.quiet_to_hour}:00)"
    return None


def _in_quiet_hours(settings: TriggerSettings, hour: int) -> bool:
    start, end = settings.quiet_from_hour, settings.quiet_to_hour
    if start is None or end is None or start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # wraps past midnight, e.g. 23 to 7


def _cooldown_left_minutes(
    settings: TriggerSettings, state: TriggerState, key: str, now: int
) -> int:
    """Whole minutes left of the cooldown for this character (0 = free to answer)."""
    last = state.last_coach_at.get(key)
    if last is None:
        return 0
    seconds_left = last + settings.cooldown_minutes * SECONDS_PER_MINUTE - now
    return max(math.ceil(seconds_left / SECONDS_PER_MINUTE), 0)


def _decide_one(
    event: Event,
    settings: TriggerSettings,
    state: TriggerState,
    now: int,
    quiet_reason: str | None,
) -> Decision:
    if event.kind == "asked":
        return Decision(event, "coach", "you asked, so the coach answers")
    mode: Mode = settings.modes.get(event.kind, "off")
    label = KIND_LABELS[event.kind]
    if mode == "off":
        return Decision(event, "off", f"your rule for {label} is off")
    if quiet_reason:
        return Decision(event, "off", f"{quiet_reason}, so nothing happens")
    if mode == "coach":
        minutes_left = _cooldown_left_minutes(settings, state, event.character_key, now)
        if minutes_left > 0:
            reason = f"cooldown: {minutes_left} min left, so you are only notified"
            return Decision(event, "notify", reason)
    return Decision(event, mode, f"your rule for {label} says {mode}")


def _drop_double_death(decisions: list[Decision], settings: TriggerSettings) -> list[Decision]:
    """A death in a death loop gives two events; the repeat-death rule wins if it is on."""
    if settings.modes.get("died_again_soon") == "off":
        return decisions
    loops = {
        (d.event.character_key, d.event.at) for d in decisions if d.event.kind == "died_again_soon"
    }
    result = []
    for decision in decisions:
        event = decision.event
        if event.kind == "died" and (event.character_key, event.at) in loops:
            reason = "your rule for dying again soon covers this death"
            decision = Decision(event, "off", reason)
        result.append(decision)
    return result


def _merge_coach(decisions: list[Decision]) -> list[Decision]:
    """Keep the first unasked "coach" decision; the others join its request."""
    leader: Event | None = None
    merged = []
    for decision in decisions:
        if decision.action == "coach" and decision.event.kind != "asked":
            if leader is None:
                leader = decision.event
            else:
                reason = "joined the one coach request for this save (one AI call)"
                decision = replace(decision, reason=reason)
        merged.append(decision)
    return merged
