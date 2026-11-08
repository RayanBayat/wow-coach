""" "When should the coach speak up?": turns saves (and a timer) into notifications or advice.

The steps for one save, in plain words:

1. Compare the new save with the previous one of the same character: that gives events
   (you died, you levelled up...).
2. ``decide`` applies the player's rules, cooldown and quiet times to each event.
3. If the player turned on triage, a small AI may turn "ask the coach" into "just notify".
4. "notify" decisions become desktop notifications. All the "coach" decisions of the save
   together make ONE coach request, so a busy minute never costs several answers.
5. The cooldown and the timer are remembered in a small file.

The AI parts run while holding the shared AI lock: one AI call at a time, everywhere.
"""

import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from wow_coach.app.core import AppCore
from wow_coach.characters import pick_character
from wow_coach.savedvars import Character
from wow_coach.triggers.contract import Decision, Event
from wow_coach.triggers.decide import decide
from wow_coach.triggers.events import events_between
from wow_coach.triggers.prompt import coach_request_for
from wow_coach.triggers.state import load_state, record_decisions, save_state
from wow_coach.triggers.triage import triage


def _is_unasked_coach(decision: Decision) -> bool:
    return decision.action == "coach" and decision.event.kind != "asked"


class SpeakUp:
    """Decides, and carries out, what happens when the game saves or the timer is due."""

    def __init__(
        self,
        core: AppCore,
        state_file: Path,
        *,
        clock: Callable[[], float] = time.time,
        local_hour: Callable[[], int] = lambda: datetime.now().hour,
    ) -> None:
        self._core = core
        self._state_file = state_file
        self._clock = clock
        self._local_hour = local_hour
        # The previous save of each character, so a save can be compared with the one before.
        self._previous: dict[str, Character] = dict(core.game().characters)
        self._latest: Character | None = pick_character(self._previous, None)

    # ---- entry points -------------------------------------------------------------

    def on_save(self, characters: dict[str, Character]) -> None:
        """The game saved: look at the newest character."""
        newest = pick_character(characters, None)
        if newest is None:
            return
        now = int(self._clock())
        events = events_between(self._previous.get(newest.key), newest, now=now)
        self._previous = dict(characters)
        self._latest = newest
        self._handle(events, newest, now)

    def on_timer(self) -> None:
        """A minute passed: only the timer rule can fire without a save."""
        if self._latest is None:
            return
        self._handle([], self._latest, int(self._clock()))

    # ---- the work -----------------------------------------------------------------

    def _handle(self, events: list[Event], character: Character, now: int) -> None:
        core = self._core
        settings = core.settings
        state = load_state(self._state_file)
        decisions = decide(
            events,
            settings.triggers,
            state=state,
            now=now,
            in_instance=bool(character.snapshot.get("instance")),
            local_hour=self._local_hour(),
            character_key=character.key,
        )
        if not decisions:
            return
        try:
            decisions = self._carry_out(decisions, character)
        finally:
            # Start the cooldown even when the AI failed: the plan is protected either way.
            save_state(self._state_file, record_decisions(state, decisions, now=now))

    def _carry_out(self, decisions: list[Decision], character: Character) -> list[Decision]:
        core = self._core
        if any(_is_unasked_coach(d) for d in decisions):
            with core.ai_lock:  # one AI call at a time
                decisions = self._triage(decisions)
                self._publish(decisions)
                self._notify(decisions)
                self._ask_coach(decisions, character.key)
        else:
            self._publish(decisions)
            self._notify(decisions)
        return decisions

    def _triage(self, decisions: list[Decision]) -> list[Decision]:
        core = self._core
        settings = core.settings.triggers
        model = core.small_model() if settings.use_triage else None
        if core.triage_provider is None or model is None:
            return decisions
        return triage(decisions, settings, core.triage_provider, model=model)

    def _publish(self, decisions: list[Decision]) -> None:
        for decision in decisions:
            self._core.bus.publish(
                "decision",
                {
                    "kind": decision.event.kind,
                    "summary": decision.event.summary,
                    "action": decision.action,
                    "reason": decision.reason,
                },
            )

    def _notify(self, decisions: list[Decision]) -> None:
        for decision in decisions:
            if decision.action == "notify":
                self._core.notify_text(decision.event.summary)

    def _ask_coach(self, decisions: list[Decision], character_key: str) -> None:
        request = coach_request_for(decisions)
        if not request:
            return
        core = self._core
        try:
            reply = core.coach.ask(request, character=character_key)
        finally:
            core.baseline.refresh()  # our own write is not an "outside change"
        core.publish_reply(reply)
        core.alert(reply.answer, allow_speak=True)
