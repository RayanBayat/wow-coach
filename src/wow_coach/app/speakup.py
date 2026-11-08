""" "When the game saves": turns a save into one notification, and maybe one coach answer.

The steps for one save, in plain words:

1. Compare the new save with the previous one of the same character: that gives events
   (you died, you levelled up...).
2. ``worth_knowing`` applies the player's choice and the quiet rule. No AI is used.
3. What is worth knowing becomes ONE desktop notification (one short text).
4. If the player chose "advice" ("Update my next steps"), EVERY save also makes ONE
   "status updated, what next?" coach request, which mentions the events if there were any.
   The player asked for this on purpose: a /reload means "look at me again". Its answer shows
   in the chat and on the small keep-on-top card. One save never costs more than one unasked
   AI call.
5. A save that carries a question typed in the game gets no extra request: that question
   gets its own answer.

The AI call runs while holding the shared AI lock: one AI call at a time, everywhere.
"""

import time
from collections.abc import Callable
from typing import Final

from wow_coach.app.core import AppCore
from wow_coach.characters import pick_character
from wow_coach.savedvars import Character
from wow_coach.triggers.decide import notification_text, worth_knowing
from wow_coach.triggers.events import events_between
from wow_coach.triggers.prompt import coach_request_for

# The addon saves with this reason when the player asked a question in the game's Coach panel.
ASKED_IN_GAME: Final = "ask"


class SpeakUp:
    """Decides, and carries out, what happens when the game saves."""

    def __init__(self, core: AppCore, *, clock: Callable[[], float] = time.time) -> None:
        self._core = core
        self._clock = clock
        # The previous save of each character, so a save can be compared with the one before.
        self._previous: dict[str, Character] = dict(core.game().characters)

    def on_save(self, characters: dict[str, Character]) -> None:
        """The game saved: look at the newest character."""
        newest = pick_character(characters, None)
        if newest is None:
            return
        before = self._previous.get(newest.key)
        events = events_between(before, newest, now=int(self._clock()))
        self._previous = dict(characters)
        core = self._core
        settings = core.settings.triggers
        in_instance = bool(newest.snapshot.get("instance"))
        events = worth_knowing(events, settings, in_instance=in_instance)
        if events:
            core.notify_text(notification_text(events))
        if settings.on_save != "advice" or (settings.quiet_in_instances and in_instance):
            return
        if newest.snapshot.get("reason") == ASKED_IN_GAME:
            return  # this save carries a question typed in the game: it gets its own answer
        with core.ai_lock:  # one AI call at a time
            reply = core.coach.ask(coach_request_for(events), character=newest.key)
            core.publish_reply(reply)
            core.alert(reply.answer)
