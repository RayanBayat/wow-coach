"""Pick what is worth telling the player after one save. No AI is used here.

``worth_knowing`` applies the player's choice and the quiet rule to the events of ONE save.
``notification_text`` joins them into a single short text, so a save gives at most one
notification, and the caller makes at most one coach request for the whole save.
"""

from collections.abc import Sequence
from typing import Final

from wow_coach.triggers.contract import Event, TriggerSettings

# Longest notification text: desktops cut long ones off anyway.
MAX_NOTIFICATION_CHARS: Final = 240


def worth_knowing(
    events: Sequence[Event], settings: TriggerSettings, *, in_instance: bool
) -> list[Event]:
    """The events to tell the player about, in order. Empty means: say nothing.

    Nothing is told when the player chose "off", or while they are inside a dungeon or
    raid and asked for quiet there.
    """
    if settings.on_save == "off":
        return []
    if settings.quiet_in_instances and in_instance:
        return []
    return _drop_double_death(events)


def _drop_double_death(events: Sequence[Event]) -> list[Event]:
    """A death in a death loop gives two events; keep the "died again" one only."""
    loops = {(e.character_key, e.at) for e in events if e.kind == "died_again_soon"}
    return [e for e in events if not (e.kind == "died" and (e.character_key, e.at) in loops)]


def notification_text(events: Sequence[Event]) -> str:
    """All the events as one short text, e.g. "Reached level 9. Bags are nearly full..."."""
    text = " ".join(event.summary for event in events)
    if len(text) <= MAX_NOTIFICATION_CHARS:
        return text
    return text[: MAX_NOTIFICATION_CHARS - 3] + "..."
