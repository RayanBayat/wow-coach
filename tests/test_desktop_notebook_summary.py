"""The no-AI notebook summary: which lines it picks out of different journal shapes."""

from wow_coach.desktop.notebook_summary import LINE_LIMIT, NotebookSummary, summarize

FULL = """# Journal: Testchar-Testrealm

## Goals
- **Goal:** Reach **level 20** by Sunday
- Run Deadmines

## Where we are
Level 12, Silverpine Forest.
Second line.

## Quests
- Delivery to Silverpine

## Next steps (in order)
1. Turn in Delivery
2. Train spells in Brill
3. Buy a bag
4. Visit the bank

## Choices
- Spec: Frost
- Why: it was popular
- Professions: Tailoring and Enchanting

## This computer
- Game folder: /opt/example-games/wow

## Progress log
- 2026-11-06: started.
- 2026-11-08: reached level 12.
"""


def test_a_full_journal_is_summarized() -> None:
    summary = summarize(FULL)
    assert summary.goal == "Reach level 20 by Sunday"
    assert summary.where == "Level 12, Silverpine Forest."
    assert summary.next_steps == ("Turn in Delivery", "Train spells in Brill", "Buy a bag")
    assert summary.choices == ("Spec: Frost", "Professions: Tailoring and Enchanting")
    assert summary.latest == "2026-11-08: reached level 12."
    assert not summary.is_empty


def test_an_empty_or_missing_file_gives_an_empty_summary() -> None:
    assert summarize("").is_empty
    assert summarize(None).is_empty
    assert summarize("# Journal: x\n\nJust some words.\n").is_empty
    assert summarize("") == NotebookSummary()


def test_missing_sections_leave_their_fields_empty() -> None:
    summary = summarize("## Goals\nGoal: Learn fishing\n")
    assert summary.goal == "Learn fishing"
    assert summary.next_steps == ()
    assert summary.where == ""
    assert summary.choices == ()
    assert summary.latest == ""


def test_headings_match_loosely_and_open_advice_counts_as_next_steps() -> None:
    text = "## MY GOALS\n- Be rich\n\n## Open Advice\n- Sell the cloth\n- Visit the AH\n"
    summary = summarize(text)
    assert summary.goal == "Be rich"
    assert summary.next_steps == ("Sell the cloth", "Visit the AH")


def test_private_sections_are_never_summarized() -> None:
    text = "## Goals (this computer)\n- Secret folder\n\n## Next steps\n- Open the PC setup\n"
    assert summarize(text).goal == ""
    assert summarize("## PC setup\n## Progress log\n- Done.\n").latest == "Done."


def test_long_lines_are_cut_with_an_ellipsis() -> None:
    summary = summarize("## Where we are\n" + "word " * 100 + "\n")
    assert summary.where.endswith("…")
    assert len(summary.where) <= LINE_LIMIT + 1


def test_the_latest_progress_is_the_last_entry_not_the_first() -> None:
    summary = summarize("## Progress log\n- one\n- two\n\n- three\n")
    assert summary.latest == "three"


def test_choices_without_spec_or_profession_lines_are_left_out() -> None:
    assert summarize("## Choices\n- Why: popular\n").choices == ()


def test_player_notes_give_an_about_you_line() -> None:
    summary = summarize(None, "# Player notes\n\n## Style\n- Wants **exact** click steps\n")
    assert summary.about_you == "Wants exact click steps"
    assert not summary.is_empty
