"""Did a save change anything that matters for "what should I do next"?

Every save also changes things that don't matter for advice: the time of the save, why it
was saved, the play time, the exact spot the character stands on. So two saves count as
different only when one of the fields below changed.
"""

from typing import Final

from wow_coach.savedvars import Character

# The parts of a snapshot that change what the coach would advise.
MEANINGFUL_FIELDS: Final = (
    "level",
    "xp",
    "money",
    "zone",
    "subZone",
    "quests",
    "completedQuests",
    "bags",
    "gear",
    "professions",
    "talents",
    "spells",
)


def status_changed(before: Character | None, after: Character) -> bool:
    """True when the new save differs from the one before in something that matters.

    A character seen for the first time (nothing to compare with) counts as unchanged, so
    the app never surprises the player with a question right after it starts.
    """
    if before is None:
        return False
    old, new = before.snapshot, after.snapshot
    return any(old.get(field) != new.get(field) for field in MEANINGFUL_FIELDS)
