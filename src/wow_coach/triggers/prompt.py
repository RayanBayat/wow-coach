"""The question the coach is asked when the rules say "coach"."""

from collections.abc import Sequence

from wow_coach.triggers.contract import Decision

MAX_EVENTS: int = 8  # a long list would only cost tokens


def coach_request_for(decisions: Sequence[Decision]) -> str:
    """One question for all the "coach" decisions of a save. Empty if there are none.

    Questions the player typed (kind ``asked``) are answered separately, so they are left out.
    """
    summaries = [
        decision.event.summary
        for decision in decisions
        if decision.action == "coach" and decision.event.kind != "asked"
    ]
    if not summaries:
        return ""
    listed = " ".join(summaries[:MAX_EVENTS])
    return f"These just happened: {listed} What should I do now? Keep it short."
