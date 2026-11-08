"""The question the coach is asked after a save when the player chose "Update my next steps"."""

from collections.abc import Sequence

from wow_coach.triggers.contract import Event

MAX_EVENTS: int = 8  # a long list would only cost tokens


STATUS_UPDATED = (
    "Status updated: my game just saved. Look at my current status, my journal and my goals, "
    "and tell me what to do next. Keep it short."
)


def coach_request_for(events: Sequence[Event]) -> str:
    """One question for a save: "what next?", plus what notable happened, if anything."""
    if not events:
        return STATUS_UPDATED
    listed = " ".join(event.summary for event in events[:MAX_EVENTS])
    return f"{STATUS_UPDATED} These just happened: {listed}"
