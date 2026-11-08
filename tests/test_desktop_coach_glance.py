"""The "At a glance" notes summary beside the chat on the Coach page."""

import os

from desktop_support import KEY, make_bridge, run_now
from pytestqt.qtbot import QtBot

from wow_coach.desktop.pages.coach import GLANCE_MIN_PAGE_WIDTH, CoachPage
from wow_coach.notes import journal_path

JOURNAL = """# Journal: Testchar-Testrealm

## Goals
- Goal: reach level 20 by Sunday

## Next steps (in order)
1. Train Frost Nova rank 2 in Brill
"""


def make_page(qtbot: QtBot) -> CoachPage:
    path = journal_path(KEY, environ=os.environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(JOURNAL, encoding="utf-8")
    bridge, _core = make_bridge()
    page = CoachPage(bridge, notes_runner=run_now)
    qtbot.addWidget(page)
    bridge.state_changed.connect(page.show_state)
    bridge.refresh_state()
    return page


def test_the_summary_beside_the_chat_shows_the_characters_notes(qtbot: QtBot) -> None:
    page = make_page(qtbot)
    texts = " ".join(label.text() for label in page.glance.findChildren(type(page.header._name)))
    assert "reach level 20 by Sunday" in texts
    assert "Train Frost Nova rank 2 in Brill" in texts


def test_open_the_notebook_goes_to_the_notebook_page(qtbot: QtBot) -> None:
    page = make_page(qtbot)
    with qtbot.waitSignal(page.navigate) as wanted:
        page.glance.open_requested.emit()
    assert wanted.args == ["notebook"]


def test_a_narrow_page_gives_the_chat_the_whole_width(qtbot: QtBot) -> None:
    page = make_page(qtbot)
    page.show()
    page.resize(GLANCE_MIN_PAGE_WIDTH - 100, 600)
    qtbot.waitUntil(lambda: page.glance.isHidden())
    page.resize(GLANCE_MIN_PAGE_WIDTH + 200, 700)
    qtbot.waitUntil(lambda: not page.glance.isHidden())
