"""What the coach engine promises the rest of wow-coach (0.9.0+).

The engine turns a question (or "what next?") plus the character's save into an answer:
it builds the prompt (coaching rules, the status report, history, journal, player notes),
hides other players' names unless the player allows them, asks the AI through a
``Provider`` (``ai/base.py``), reads the JSON answer, writes it into the Coach panel's file
(``advice/``) and keeps the conversation. The app window and the CLI only use ``Coach``.
"""

from dataclasses import dataclass
from typing import Protocol

from wow_coach.advice.contract import AdviceAnswer
from wow_coach.engine.conversation import Lookup
from wow_coach.engine.sources import SourceLink


@dataclass(frozen=True, slots=True)
class CoachReply:
    """One answer from the engine."""

    character_key: str
    answer: AdviceAnswer  # what the panel shows (title, steps, text, warnings, source)
    written_to_game: bool  # True when Advice.lua now holds it
    note: str  # a plain sentence for the player, e.g. "In the game after your next /reload."
    sources: tuple[SourceLink, ...] = ()  # the web pages the answer came from
    lookups: tuple[Lookup, ...] = ()  # what the coach looked up, as plain sentences


class Coach(Protocol):
    """The coach engine, as the app window and the CLI see it."""

    def ask(self, question: str, *, character: str | None = None) -> CoachReply:
        """Answer a question typed outside the game (the window or ``wow-coach ask``).

        Args:
            question: The player's question, their own words.
            character: Name or "Name-Realm"; None for the most recently saved character.

        Raises:
            AIError: The AI could not answer (not signed in, plan limit, network...),
                with a plain sentence for the player.
        """
        ...

    def answer_open_questions(self, *, character: str | None = None) -> list[CoachReply]:
        """Answer every question from the game's Coach panel that has no answer yet.

        Returns one reply per question answered (empty if none were open).

        Raises:
            AIError: As for ``ask``. Questions answered before the error keep their answers.
        """
        ...
