"""Pick what the AI sees from the coach's notes: the useful parts, whole, private parts left out.

The player notes (``coach-notes.md``) and each character's journal are Markdown files: a
title line, then sections that start with ``## ``. Two jobs happen here:

* **Private sections stay on this computer.** A section whose heading mentions the computer
  ("## This computer", "## PC setup", "## Machine") holds things like folder paths. The coach
  doesn't need them to coach, so they are never sent.
* **Long notes keep their most useful sections.** Cutting a long file at a fixed length would
  keep only its first sections (often a long "Goals") and lose "Next steps" and "Choices".
  Instead, when a file is too long, whole sections are kept in order of usefulness, the last
  one that fits partly is shortened, and the names of the left-out sections are listed, so
  the AI knows they exist.
"""

import re
from dataclasses import dataclass
from typing import Final

SECTION_START: Final = "## "
# A heading with one of these words marks a section that stays on this computer.
PRIVATE_HEADING: Final = re.compile(r"\b(computer|pc|machine)\b", re.IGNORECASE)
# Sections in order of usefulness for answering a question now. A heading belongs to the first
# group that has one of its words; headings that match no group come last.
PRIORITY: Final = (
    ("next step", "open advice"),
    ("where we are",),
    ("choice",),
    ("goal",),
    ("learned", "terms they know", "player"),
    ("quest",),
    ("progress",),
)
# In these sections the newest lines are at the end, so a shortened one keeps its end.
NEWEST_AT_END: Final = ("progress",)
# A section is only kept partly when at least this many characters of it fit.
SMALLEST_PART: Final = 300
CUT_MARK: Final = "[cut: too long]"
OLDER_MARK: Final = "[older lines left out]"
LEFT_OUT_NOTE: Final = "[left out to save space: {names}]"
LEFT_OUT_ROOM: Final = 200  # kept free for the "left out" note


@dataclass(frozen=True, slots=True)
class Section:
    """One part of a notes file: its ``## `` heading line ("" before the first one) and text."""

    heading: str
    body: str

    @property
    def text(self) -> str:
        """The whole section as it appears in the file."""
        return f"{self.heading}\n{self.body}".strip("\n") if self.heading else self.body

    @property
    def name(self) -> str:
        """The heading without its ``## `` mark, for the "left out" note."""
        return self.heading.removeprefix(SECTION_START).strip()


def split_sections(text: str) -> list[Section]:
    """Split Markdown notes at each ``## `` heading. Text before the first heading comes first."""
    sections: list[Section] = []
    heading = ""
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith(SECTION_START):
            sections.append(Section(heading, "\n".join(lines).strip("\n")))
            heading, lines = line.rstrip(), []
        else:
            lines.append(line)
    sections.append(Section(heading, "\n".join(lines).strip("\n")))
    return [s for s in sections if s.heading or s.body.strip()]


def is_private(section: Section) -> bool:
    """True for a section about the player's computer, which is never sent."""
    return bool(section.heading) and PRIVATE_HEADING.search(section.heading) is not None


def without_private_sections(text: str) -> str:
    """The notes without the sections about the player's computer."""
    kept = [s for s in split_sections(text) if not is_private(s)]
    return "\n\n".join(s.text for s in kept)


def usefulness(section: Section) -> int:
    """The section's place in ``PRIORITY`` (0 = most useful). Unknown headings come last."""
    heading = section.heading.lower()
    for place, words in enumerate(PRIORITY):
        if any(word in heading for word in words):
            return place
    return len(PRIORITY)


def shorten(section: Section, size: int) -> str:
    """The section in about ``size`` characters, its heading always kept.

    Sections whose newest lines are at the end (a progress log) keep their end; the others
    keep their start.
    """
    room = max(size - len(section.heading) - len(CUT_MARK) - 2, 0)
    body = section.body
    if any(word in section.heading.lower() for word in NEWEST_AT_END):
        return f"{section.heading}\n{OLDER_MARK}\n{body[len(body) - room :].lstrip()}"
    return f"{section.heading}\n{body[:room].rstrip()}\n{CUT_MARK}"


def digest(text: str, budget: int) -> str:
    """The notes in at most ``budget`` characters: unchanged when they fit, else whole
    sections, most useful first.
    """
    if len(text) <= budget:
        return text
    sections = split_sections(text)
    title = [s for s in sections if not s.heading]  # the "# Journal: ..." line, if any
    ranked = sorted((s for s in sections if s.heading), key=usefulness)  # stable: file order
    kept = [s.text for s in title]
    used = sum(len(piece) + 2 for piece in kept)
    room = budget - LEFT_OUT_ROOM
    left_out: list[str] = []
    for section in ranked:
        piece = section.text
        if used + len(piece) + 2 <= room:
            kept.append(piece)
            used += len(piece) + 2
        elif room - used >= SMALLEST_PART:
            part = shorten(section, room - used - 2)
            kept.append(part)
            used += len(part) + 2
        else:
            left_out.append(section.name)
    if left_out:
        kept.append(LEFT_OUT_NOTE.format(names="; ".join(left_out)))
    return "\n\n".join(kept)[:budget]
