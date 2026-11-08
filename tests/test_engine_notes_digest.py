"""The coach's notes as the AI sees them: useful sections whole, computer details left out."""

from wow_coach.engine.notes_digest import (
    LEFT_OUT_NOTE,
    OLDER_MARK,
    digest,
    split_sections,
    without_private_sections,
)
from wow_coach.engine.prompt import PromptData, user_message

JOURNAL = """# Journal: Testchar-Testrealm

## Goals
{goals}

## Where we are
Level 12, Silverpine Forest.

## Quests
{quests}

## Next steps (in order)
1. Turn in Delivery to Silverpine Forest.

## Choices
- Spec: Frost

## Addon issues
{issues}

## Progress log
- 2026-11-06: started.
{log}
- 2026-11-08: reached level 12.
"""


def journal(*, goals: int = 100, quests: int = 100, issues: int = 100, log: int = 0) -> str:
    return JOURNAL.format(
        goals="g" * goals,
        quests="q" * quests,
        issues="i" * issues,
        log="\n".join(f"- old entry {n}" for n in range(log)),
    )


def test_notes_that_fit_are_sent_unchanged() -> None:
    text = journal()
    assert digest(text, 10_000) == text


def test_long_notes_keep_the_most_useful_sections_whole() -> None:
    text = journal(goals=3_000, quests=3_000, issues=3_000)
    short = digest(text, 4_000)
    assert len(short) <= 4_000
    # Next steps, where we are and choices come first and are whole.
    assert short.index("## Next steps") < short.index("## Where we are") < short.index("## Choices")
    assert "1. Turn in Delivery to Silverpine Forest." in short
    assert "- Spec: Frost" in short
    # The least useful section is named, so the AI knows it exists.
    assert LEFT_OUT_NOTE.split("{")[0] in short
    assert "Addon issues" in short.split(LEFT_OUT_NOTE.split("{")[0])[1]


def test_a_shortened_progress_log_keeps_its_newest_lines() -> None:
    text = journal(log=400)
    short = digest(text, 3_000)
    assert "2026-11-08: reached level 12." in short
    assert OLDER_MARK in short


def test_sections_about_the_computer_never_leave_it() -> None:
    notes = (
        "# Player notes\n\n## Player\n- Likes short answers\n\n"
        "## This computer\n- Game folder: /opt/example-games/secret path\n\n"
        "## Terms they know\n- aggro\n"
    )
    kept = without_private_sections(notes)
    assert "secret path" not in kept
    assert "Likes short answers" in kept and "aggro" in kept


def test_the_prompt_leaves_computer_sections_out_and_keeps_the_whole_journal() -> None:
    notes = "## Player\n- Likes short answers\n\n## PC setup\n- /home/someone/wow\n"
    big_journal = journal(goals=4_300, quests=1_500, issues=800, log=60)  # a real-sized journal
    message = user_message(
        PromptData(status="S", question="Q", journal=big_journal, player_notes=notes),
        hidden_names=set(),
    )
    assert "/home/someone/wow" not in message
    for heading in (
        "## Goals",
        "## Where we are",
        "## Next steps",
        "## Choices",
        "## Progress log",
    ):
        assert heading in message


def test_split_sections_keeps_the_title_and_every_heading() -> None:
    sections = split_sections(journal())
    assert sections[0].heading == ""
    assert sections[0].body.startswith("# Journal")
    assert [s.name for s in sections[1:]][:3] == ["Goals", "Where we are", "Quests"]
