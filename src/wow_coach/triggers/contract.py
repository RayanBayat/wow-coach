"""The contract for "when the coach speaks up" (0.9.0+).

The game only hands data to wow-coach when it saves (/reload, /coach, logout, the Coach
panel's Ask). Each save is compared with the one before, which gives ``Event``s: you died,
you levelled up, your bags are almost full... The player decides per kind of event what
happens (``Mode``): nothing, a notification, or the coach looks at it and gives advice. A
timer can also ask the coach every N minutes. Cooldowns, quiet times and the plan caps
always come first, and the default is manual only: the coach only answers when asked.

An optional small AI step (triage) reads the events and the player's own words ("only wake
the coach if I die twice in 10 minutes") and decides which events are worth the bigger
model. It uses the smallest model on the player's ChatGPT plan.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final, Literal

type EventKind = Literal[
    "asked",  # a question from the Coach panel (always answered when the app runs)
    "died",
    "died_again_soon",  # died again within a few minutes of coming back to life
    "level_up",
    "quest_done",  # a quest in the log became ready to turn in
    "bags_nearly_full",
    "new_zone",
    "talent_points",  # unspent talent points
    "gear_hint",  # the report found a possible upgrade or an unusable item
    "durability_low",
    "timer",  # every N minutes, if the player wants it
]
EVENT_KINDS: Final[tuple[EventKind, ...]] = (
    "asked",
    "died",
    "died_again_soon",
    "level_up",
    "quest_done",
    "bags_nearly_full",
    "new_zone",
    "talent_points",
    "gear_hint",
    "durability_low",
    "timer",
)

type Mode = Literal["off", "notify", "coach"]
# off: nothing. notify: a notification with the event's sentence, no AI.
# coach: the coach looks at the event and gives advice (uses the plan).
MODES: Final[tuple[Mode, ...]] = ("off", "notify", "coach")


@dataclass(frozen=True, slots=True)
class Event:
    """Something that happened between two saves."""

    kind: EventKind
    character_key: str
    at: int  # Unix time (the save's savedAt, or the history event's time)
    summary: str  # one plain sentence, e.g. "Died in Brill to Scarlet Warrior (elite)."


def _default_modes() -> dict[EventKind, Mode]:
    # Manual by default: only questions the player asks get an answer.
    modes: dict[EventKind, Mode] = dict.fromkeys(EVENT_KINDS, "off")
    modes["asked"] = "coach"
    return modes


@dataclass(frozen=True, slots=True)
class TriggerSettings:
    """The player's rules. Stored under "triggers" in settings.json."""

    modes: Mapping[EventKind, Mode] = field(default_factory=_default_modes)
    cooldown_minutes: int = 10  # at most one unasked "coach" answer per this many minutes
    quiet_in_instances: bool = True  # nothing unasked inside dungeons and raids
    quiet_from_hour: int | None = None  # local hours 0-23, e.g. 23 to 7; None = never quiet
    quiet_to_hour: int | None = None
    every_minutes: int = 0  # the timer; 0 = off
    use_triage: bool = False
    rules_text: str = ""  # the player's own words for the triage step, at most 500 chars


@dataclass(frozen=True, slots=True)
class Decision:
    """What to do about one event, and why (shown to the player in the window)."""

    event: Event
    action: Mode
    reason: str  # e.g. "your rule for deaths says notify", "cooldown: 4 min left"
