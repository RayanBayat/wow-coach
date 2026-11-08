"""A short, free summary of the coach's notes: the important stuff, picked without any AI.

The Notebook can be long. This module reads the journal (and the player notes) and pulls out
the few lines a player wants at a glance: the goal, the next steps, where they are, their
choices and the latest progress. It is plain Python with no Qt, so it is instant and easy to
test. Nothing here changes the text it finds, except to tidy it (bullet signs, ``**bold**``
markers and the ``Goal:`` label are removed, long lines are shortened).

Sections are found by their headings, matched loosely: a heading counts when it has a word
that starts with the wanted word ("Goals" matches "goal", "Next steps (in order)" matches
"next" + "step"). Sections about the player's computer are skipped, like everywhere else.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from wow_coach.engine.notes_digest import Section, is_private, split_sections

LINE_LIMIT: Final = 110  # characters kept of one summary line
MAX_STEPS: Final = 3
MAX_CHOICES: Final = 3

_WORDS: Final = re.compile(r"[a-z]+")
_BULLET: Final = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")
_BOLD: Final = re.compile(r"\*\*(.+?)\*\*")
_LABEL: Final = re.compile(r"^(?:goal|goals)\s*:\s*", re.IGNORECASE)
# A "Choices" line is interesting when it starts with one of these labels.
_CHOICE_LABELS: Final = ("spec", "class", "profession", "talent")


@dataclass(frozen=True, slots=True)
class NotebookSummary:
    """The important stuff of a notebook. Every field may be empty."""

    goal: str = ""
    next_steps: tuple[str, ...] = ()
    where: str = ""
    choices: tuple[str, ...] = ()
    latest: str = ""
    about_you: str = ""

    @property
    def is_empty(self) -> bool:
        """True when nothing could be picked out (no notes, or no known sections)."""
        return not (
            self.goal
            or self.next_steps
            or self.where
            or self.choices
            or self.latest
            or self.about_you
        )


def summarize(journal: str | None, player_notes: str | None = None) -> NotebookSummary:
    """Pick the important lines out of a journal and the player notes (either may be None)."""
    sections = _public_sections(journal)
    goal_lines = _lines(_find(sections, _is_goal))
    where_lines = _lines(_find(sections, _is_where))
    return NotebookSummary(
        goal=_shorten(_LABEL.sub("", goal_lines[0])) if goal_lines else "",
        next_steps=tuple(_shorten(line) for line in _lines(_find(sections, _is_steps)))[:MAX_STEPS],
        where=_shorten(where_lines[0]) if where_lines else "",
        choices=_choices(_find(sections, _is_choices)),
        latest=_latest(_find(sections, _is_progress)),
        about_you=_about_you(player_notes),
    )


# ---- finding sections ------------------------------------------------------------------


def _public_sections(text: str | None) -> list[Section]:
    """The sections of ``text`` that have a heading and are not about the computer."""
    if not text:
        return []
    return [s for s in split_sections(text) if s.heading and not is_private(s)]


def _heading_words(section: Section) -> list[str]:
    return _WORDS.findall(section.name.lower())


def _has_word(section: Section, start: str) -> bool:
    """True when some word of the heading starts with ``start``."""
    return any(word.startswith(start) for word in _heading_words(section))


def _is_goal(section: Section) -> bool:
    return _has_word(section, "goal")


def _is_steps(section: Section) -> bool:
    return (_has_word(section, "next") and _has_word(section, "step")) or (
        _has_word(section, "open") and _has_word(section, "advice")
    )


def _is_where(section: Section) -> bool:
    return _has_word(section, "where") and _has_word(section, "are")


def _is_choices(section: Section) -> bool:
    return _has_word(section, "choice")


def _is_progress(section: Section) -> bool:
    return _has_word(section, "progress")


def _find(sections: list[Section], matches: Callable[[Section], bool]) -> Section | None:
    """The first section for which ``matches(section)`` is true."""
    for section in sections:
        if matches(section):
            return section
    return None


# ---- tidying lines ---------------------------------------------------------------------


def _tidy(line: str) -> str:
    """One line without its bullet sign or ``**bold**`` markers."""
    return _BOLD.sub(r"\1", _BULLET.sub("", line.strip())).strip()


def _lines(section: Section | None) -> list[str]:
    """The meaningful lines of a section: tidy, not empty, not a Markdown heading."""
    if section is None:
        return []
    lines = [_tidy(raw) for raw in section.body.splitlines() if not raw.lstrip().startswith("#")]
    return [line for line in lines if line]


def _shorten(line: str, limit: int = LINE_LIMIT) -> str:
    """Cut a long line at a word boundary and add an ellipsis."""
    if len(line) <= limit:
        return line
    cut = line[:limit].rsplit(" ", 1)[0] if " " in line[:limit] else line[:limit]
    return cut.rstrip(" ,;:.-") + "…"


def _choices(section: Section | None) -> tuple[str, ...]:
    """The spec / class / professions lines of the Choices section."""
    wanted = [line for line in _lines(section) if line.lower().startswith(_CHOICE_LABELS)]
    return tuple(_shorten(line) for line in wanted[:MAX_CHOICES])


def _latest(section: Section | None) -> str:
    """The newest progress entry: the last line (the log grows at its end)."""
    lines = _lines(section)
    return _shorten(lines[-1]) if lines else ""


def _about_you(player_notes: str | None) -> str:
    """The first line of the first public section of the player notes."""
    for section in _public_sections(player_notes):
        lines = _lines(section)
        if lines:
            return _shorten(lines[0])
    return ""
