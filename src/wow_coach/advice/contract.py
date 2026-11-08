"""The contract for questions and answers between the game and wow-coach (addon 0.8.0+).

Two channels, because a WoW addon can't use the network or read files while it runs:

* **Questions, game -> wow-coach.** The Coach panel stores the player's questions in the
  addon's SavedVariables, under the character (``questions``). WoW writes that file at
  ``/reload``, logout or exit. ``Character.questions`` holds them after loading.
* **Answers, wow-coach -> game.** wow-coach writes ``Interface/AddOns/HeroBridge_Advice/
  Advice.lua``. That is a tiny data-only addon of its own (not part of the HeroBridge zip,
  so addon managers never overwrite it). The game reads it at the next ``/reload`` or
  login, and the Coach panel shows it.

The Lua shapes are documented in docs/design.md ("Coach panel: questions and advice").
This module holds the Python side: names, limits and value types. It has no logic.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

# The data-only addon wow-coach writes, and what is inside it.
ADVICE_ADDON_NAME: Final = "HeroBridge_Advice"
ADVICE_FILE_NAME: Final = "Advice.lua"
ADVICE_GLOBAL: Final = "HeroBridgeAdvice"  # the one global variable Advice.lua sets
ADVICE_FORMAT_VERSION: Final = 1
# Before 0.11.0 the addon was called CoachLink and the answers addon CoachLink_Advice. If only
# the old addon is installed, we keep writing under the old names so it still shows answers.
LEGACY_ADVICE_ADDON_NAME: Final = "CoachLink_Advice"
LEGACY_ADVICE_GLOBAL: Final = "CoachLinkAdvice"

# Limits. The addon enforces the question limits; wow-coach enforces the answer limits
# (it cuts text that is too long and keeps only the newest answers).
MAX_QUESTIONS_KEPT: Final = 20
MAX_QUESTION_CHARS: Final = 500
MAX_ANSWERS_PER_CHARACTER: Final = 10
MAX_STEPS: Final = 5
MAX_STEP_CHARS: Final = 300
MAX_TITLE_CHARS: Final = 80
MAX_TEXT_CHARS: Final = 4000
MAX_WARNINGS: Final = 5
MAX_SOURCE_CHARS: Final = 80
MAX_FILE_BYTES: Final = 200_000
# Question ids already answered, kept apart from the answers: answers are pushed out after
# MAX_ANSWERS_PER_CHARACTER, but the addon keeps up to MAX_QUESTIONS_KEPT questions, and a
# question must never look "open" again just because its answer was pushed out.
MAX_ANSWERED_IDS: Final = 2 * MAX_QUESTIONS_KEPT
# At most this many characters in the file; the one written to longest ago is dropped first.
MAX_CHARACTERS: Final = 20
# Ids and keys are compared as they are in the game, so they are checked, never changed.
QUESTION_ID_PATTERN: Final = r"^[0-9]{1,12}-[0-9]{1,6}$"  # "<askedAt>-<counter>"
MAX_CHARACTER_KEY_CHARS: Final = 100  # "Name-Realm"; no "|" and no control characters


@dataclass(frozen=True, slots=True)
class Question:
    """A question the player typed in the Coach panel."""

    id: str  # "<askedAt>-<counter>", unique per character
    text: str
    asked_at: int  # Unix time


@dataclass(frozen=True, slots=True)
class AdviceAnswer:
    """One answer shown in the Coach panel."""

    answered_at: int  # Unix time
    source: str  # who wrote it, e.g. "Claude Code coach" or "ChatGPT (your plan)"
    title: str  # e.g. "Next steps"
    steps: tuple[str, ...] = ()  # the next 1-3 (at most MAX_STEPS) actions, in order
    text: str = ""  # a longer explanation, may be empty
    warnings: tuple[str, ...] = ()  # e.g. "This quest is orange: bring a friend"
    question_id: str | None = None  # the Question it answers, None for unasked advice
    question: str | None = None  # the question's text, so the panel can show it
    asked_at: int | None = None


@dataclass(frozen=True, slots=True)
class CoachPlan:
    """The character's current goal and plan, if the coach has one."""

    goal: str
    steps: tuple[str, ...]
    updated_at: int


@dataclass(frozen=True, slots=True)
class CharacterAdvice:
    """Everything the panel shows for one character."""

    based_on_save: int | None  # savedAt of the snapshot the coach read
    answers: tuple[AdviceAnswer, ...] = ()  # oldest first, at most MAX_ANSWERS_PER_CHARACTER
    plan: CoachPlan | None = None
    # Every question id answered so far, newest last, at most MAX_ANSWERED_IDS.
    answered_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AdviceFile:
    """The whole Advice.lua: advice for every character on this PC, by "Name-Realm"."""

    written_at: int
    characters: Mapping[str, CharacterAdvice] = field(default_factory=dict)
