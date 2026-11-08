"""The question the coach is asked when the player chose "Tell me and add the advice"."""

from collections.abc import Sequence

from wow_coach.triggers.contract import Event

MAX_EVENTS: int = 8  # a long list would only cost tokens


def coach_request_for(events: Sequence[Event]) -> str:
    """One question for all the events of a save. Empty if there are none."""
    if not events:
        return ""
    listed = " ".join(event.summary for event in events[:MAX_EVENTS])
    return f"These just happened: {listed} What should I do now? Keep it short."
