"""The contract for "when the game saves" (0.9.0+).

The game only hands data to wow-coach when it saves (/reload, /coach, logout, the Coach
panel's Ask), so nothing here can ever be live. Each save is compared with the one before,
which gives ``Event``s: you died, you levelled up, your bags are almost full... The player
makes one choice (``OnSave``): tell nothing, tell what is worth knowing in one
notification, or also add the coach's advice. Working out what is worth knowing uses no AI.
"""

from dataclasses import dataclass
from typing import Final, Literal

type EventKind = Literal[
    "died",
    "died_again_soon",  # died again within a few minutes of coming back to life
    "level_up",
    "quest_done",  # a quest in the log became ready to turn in
    "bags_nearly_full",
    "new_zone",
    "talent_points",  # unspent talent points
    "gear_hint",  # the report found a possible upgrade or an unusable item
    "durability_low",
]

type OnSave = Literal["off", "notify", "advice"]
# off: nothing. notify: one notification listing what is worth knowing, no AI.
# advice: the same notification, plus one coach answer about those things.
ON_SAVE_CHOICES: Final[tuple[OnSave, ...]] = ("off", "notify", "advice")


@dataclass(frozen=True, slots=True)
class Event:
    """Something that happened between two saves."""

    kind: EventKind
    character_key: str
    at: int  # Unix time (the save's savedAt, or the history event's time)
    summary: str  # one plain sentence, e.g. "Died in Brill to Scarlet Warrior (elite)."


@dataclass(frozen=True, slots=True)
class TriggerSettings:
    """The player's choices. Stored under "triggers" in settings.json."""

    on_save: OnSave = "notify"
    quiet_in_instances: bool = True  # nothing unasked inside dungeons and raids
