"""The Notebook page and its background file reader.

Tests use temporary files (``conftest.py`` points the notes at a temp folder) and a runner
that works at once, so nothing waits or touches the real notebook.
"""

import os
from pathlib import Path

import pytest
from desktop_support import KEY, make_bridge, run_now, sample_state
from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QPushButton, QWidget
from pytestqt.qtbot import QtBot

from wow_coach.desktop.notes_reader import NotebookData, NotesReader
from wow_coach.desktop.pages.notebook import (
    NO_JOURNAL,
    NO_PLAYER_NOTES,
    PRIVATE_NOTE,
    BlockKind,
    NotebookPage,
    parse_notes,
    strip_bold,
)
from wow_coach.desktop.state import read_state
from wow_coach.notes import journal_path, notes_path

JOURNAL = """# Journal: Testchar

## Goals
- Reach **level 20** by Sunday
- Run Deadmines

## Next steps
1. Train spells in Brill
2. Turn in the quest

## This computer
- Game folder: /opt/example-games/wow

## Progress log
Killed the boar.
"""


def journal_file(key: str = KEY) -> Path:
    return journal_path(key, environ=os.environ)


def write_journal(text: str = JOURNAL, key: str = KEY) -> Path:
    path = journal_file(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_player(text: str) -> Path:
    path = notes_path(environ=os.environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_page(qtbot: QtBot, key: str | None = KEY) -> NotebookPage:
    bridge, _core = make_bridge()
    page = NotebookPage(bridge, runner=run_now)
    qtbot.addWidget(page)
    page.show_state(read_state(sample_state(selected=key)))
    return page


def texts(widget: QWidget) -> list[str]:
    """The texts of the labels a player can see (not those of closed sections)."""
    return [label.text() for label in widget.findChildren(QLabel) if label.isVisibleTo(widget)]


def open_all(page: NotebookPage) -> None:
    """Open every section (the page starts with all of them closed)."""
    page.character_part.set_all_open(True)
    page.player_part.set_all_open(True)


# ---- parsing --------------------------------------------------------------------------


def test_sections_are_parsed_in_the_files_order() -> None:
    sections = parse_notes(JOURNAL)
    assert [s.title for s in sections] == ["Goals", "Next steps", "This computer", "Progress log"]
    goals, steps = sections[0], sections[1]
    assert [b.kind for b in goals.blocks] == [BlockKind.BULLET, BlockKind.BULLET]
    assert [b.marker for b in steps.blocks] == ["1.", "2."]
    assert sections[3].blocks[0].kind is BlockKind.PARAGRAPH


def test_private_sections_are_marked() -> None:
    private = {s.title: s.private for s in parse_notes(JOURNAL)}
    assert private == {
        "Goals": False,
        "Next steps": False,
        "This computer": True,
        "Progress log": False,
    }


def test_bold_markers_are_removed() -> None:
    assert strip_bold("Reach **level 20** and **win**") == "Reach level 20 and win"


# ---- the page -------------------------------------------------------------------------


def test_the_page_shows_sections_bullets_and_stripped_bold(qtbot: QtBot) -> None:
    write_journal()
    page = make_page(qtbot)
    open_all(page)
    shown = texts(page)
    headings = [row.header.text() for row in page.character_part.rows]
    assert headings == ["▾  Goals", "▾  Next steps", "▾  This computer", "▾  Progress log"]
    assert "Reach level 20 by Sunday" in shown
    assert not any("**" in text for text in shown)
    assert "Your character: " + KEY in shown


def test_a_private_section_says_it_stays_on_this_computer(qtbot: QtBot) -> None:
    write_journal()
    page = make_page(qtbot)
    assert texts(page).count(PRIVATE_NOTE) == 1  # closed: the note is the section's preview
    open_all(page)
    assert texts(page).count(PRIVATE_NOTE) == 1  # open: the note is at the top of its body


def test_notes_are_shown_as_plain_text_never_as_html(qtbot: QtBot) -> None:
    write_journal("## Goals\n- Try <b>tag</b> and <a href='x'>link</a>\n")
    page = make_page(qtbot)
    open_all(page)
    label = next(label for label in page.findChildren(QLabel) if "<b>tag</b>" in label.text())
    assert label.text() == "Try <b>tag</b> and <a href='x'>link</a>"
    assert label.textFormat() is Qt.TextFormat.PlainText
    assert all(label.textFormat() is Qt.TextFormat.PlainText for label in page.findChildren(QLabel))


def test_empty_states_when_nothing_is_written(qtbot: QtBot) -> None:
    page = make_page(qtbot)
    shown = texts(page)
    assert NO_JOURNAL in shown
    assert NO_PLAYER_NOTES in shown
    assert not page.character_part.open_button.isEnabled()
    assert not page.player_part.open_button.isEnabled()


def test_no_character_selected_shows_a_friendly_message(qtbot: QtBot) -> None:
    page = make_page(qtbot, key=None)
    assert any("No character yet" in text for text in texts(page))


def test_player_notes_are_shown_under_you(qtbot: QtBot) -> None:
    write_player("# Player notes\n\n## Style\n- Wants exact click steps\n")
    page = make_page(qtbot)
    open_all(page)
    assert "Wants exact click steps" in texts(page)
    assert NO_PLAYER_NOTES not in texts(page)


def test_switching_character_loads_the_other_journal(qtbot: QtBot) -> None:
    write_journal("## Goals\n- First goal\n", "Alt-Realm")
    write_journal("## Goals\n- Second goal\n", "Main-Realm")
    page = make_page(qtbot, key="Alt-Realm")
    open_all(page)
    assert "First goal" in texts(page)
    page.show_state(read_state(sample_state(selected="Main-Realm")))
    open_all(page)
    assert "Second goal" in texts(page)
    assert "First goal" not in texts(page)


def test_open_in_editor_opens_only_the_known_files(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()))
    journal = write_journal()
    player = write_player("## Style\n- Short answers\n")
    page = make_page(qtbot)
    page.character_part.open_button.click()
    page.player_part.open_button.click()
    assert opened == [str(journal), str(player)]


def test_reload_reads_again_even_without_a_change(qtbot: QtBot) -> None:
    write_journal()
    page = make_page(qtbot)
    seen: list[object] = []
    page.reader.loaded.connect(seen.append)
    page.check_for_changes()
    assert seen == []
    reload_button = next(b for b in page.findChildren(QPushButton) if b.text() == "Reload")
    reload_button.click()
    assert len(seen) == 1


def test_the_timer_runs_only_while_the_page_is_shown(qtbot: QtBot) -> None:
    page = make_page(qtbot)
    assert not page._timer.isActive()
    page.show()
    assert page._timer.isActive()
    page.hide()
    assert not page._timer.isActive()


def test_an_edit_on_disk_shows_up_on_the_next_check(qtbot: QtBot) -> None:
    path = write_journal("## Goals\n- Old goal\n")
    page = make_page(qtbot)
    open_all(page)
    path.write_text("## Goals\n- New goal that is longer\n", encoding="utf-8")
    page.check_for_changes()
    assert "New goal that is longer" in texts(page)


# ---- collapsed and lazy ---------------------------------------------------------------


def built_bodies(page: NotebookPage) -> int:
    rows = page.character_part.rows + page.player_part.rows
    return sum(1 for row in rows if row.body is not None)


def test_every_section_starts_collapsed_with_nothing_built(qtbot: QtBot) -> None:
    write_journal()
    page = make_page(qtbot)
    rows = page.character_part.rows
    assert [row.section.title for row in rows] == [
        "Goals",
        "Next steps",
        "This computer",
        "Progress log",
    ]
    assert not any(row.is_open for row in rows)
    assert built_bodies(page) == 0
    assert "Run Deadmines" not in texts(page.character_part)  # a bullet of a closed section
    assert "Reach level 20 by Sunday" in texts(page.glance)  # but the summary has the goal


def test_a_closed_row_shows_its_first_line_as_a_preview(qtbot: QtBot) -> None:
    write_journal()
    page = make_page(qtbot)
    assert page.character_part.rows[1].preview.text() == "Train spells in Brill"


def test_opening_one_section_builds_only_that_one(qtbot: QtBot) -> None:
    write_journal()
    page = make_page(qtbot)
    page.character_part.rows[1].header.click()
    assert built_bodies(page) == 1
    assert page.character_part.rows[1].is_open
    assert "Turn in the quest" in texts(page)
    page.character_part.rows[1].header.click()  # close again: hidden, kept for next time
    assert not page.character_part.rows[1].is_open
    assert built_bodies(page) == 1


def test_expand_all_and_collapse_all(qtbot: QtBot) -> None:
    write_journal()
    page = make_page(qtbot)
    page.character_part.expand_button.click()
    assert all(row.is_open for row in page.character_part.rows)
    page.character_part.collapse_button.click()
    assert not any(row.is_open for row in page.character_part.rows)


def test_a_change_updates_the_summary_and_rebuilds_only_opened_sections(qtbot: QtBot) -> None:
    path = write_journal("## Goals\n- Old goal\n\n## Quests\n- Old quest\n")
    page = make_page(qtbot)
    page.character_part.rows[0].header.click()
    quests_row = page.character_part.rows[1]
    path.write_text("## Goals\n- New goal\n\n## Quests\n- New quest\n", encoding="utf-8")
    page.check_for_changes()
    assert "New goal" in texts(page.glance)
    assert page.character_part.rows[1] is quests_row  # same row, kept
    assert quests_row.body is None  # the closed one is still unbuilt
    assert "New goal" in texts(page.character_part)  # the open one was rebuilt
    assert "Old goal" not in texts(page)


def test_an_unchanged_section_keeps_its_built_body(qtbot: QtBot) -> None:
    path = write_journal("## Goals\n- Same goal\n\n## Quests\n- Old quest\n")
    page = make_page(qtbot)
    page.character_part.rows[0].header.click()
    body = page.character_part.rows[0].body
    path.write_text("## Goals\n- Same goal\n\n## Quests\n- New quest\n", encoding="utf-8")
    page.check_for_changes()
    assert page.character_part.rows[0].body is body


def test_the_glance_has_no_open_button_on_the_page_itself(qtbot: QtBot) -> None:
    page = make_page(qtbot)
    assert page.glance.open_button.isHidden()
    assert any("hasn't saved notes" in text for text in texts(page.glance))


# ---- the reader -----------------------------------------------------------------------


def test_the_reader_reads_only_when_something_changed() -> None:
    path = write_journal()
    reader = NotesReader(runner=run_now)
    seen: list[NotebookData] = []
    reader.loaded.connect(seen.append)
    reader.request(KEY)
    reader.request(KEY)
    assert len(seen) == 1
    path.write_text(JOURNAL + "\n- more\n", encoding="utf-8")
    reader.request(KEY)
    assert len(seen) == 2
    reader.request("Other-Realm")  # another character counts as a change
    assert len(seen) == 3
    assert seen[2].character is not None and seen[2].character.text is None


def test_the_reader_works_through_its_runner() -> None:
    jobs: list[object] = []
    reader = NotesReader(runner=jobs.append)
    seen: list[object] = []
    reader.loaded.connect(seen.append)
    reader.request(KEY)
    assert seen == []  # nothing was read on the caller's thread
    assert len(jobs) == 1
    job = jobs[0]
    assert callable(job)
    job()
    assert len(seen) == 1


def test_a_request_during_a_running_job_is_not_lost() -> None:
    jobs: list[object] = []
    reader = NotesReader(runner=jobs.append)
    seen: list[NotebookData] = []
    reader.loaded.connect(seen.append)
    reader.request("A-Realm")
    reader.request("B-Realm")  # arrives while the first job is waiting to run
    assert len(jobs) == 1  # still one job, which will look again
    job = jobs[0]
    assert callable(job)
    job()
    assert [data.character_key for data in seen] == ["B-Realm", "B-Realm"][: len(seen)]
    assert seen[-1].character_key == "B-Realm"


def test_an_unreadable_file_shows_a_problem_not_a_crash(qtbot: QtBot) -> None:
    path = journal_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe\x00bad")
    page = make_page(qtbot)
    assert any("could not be read" in text for text in texts(page))
