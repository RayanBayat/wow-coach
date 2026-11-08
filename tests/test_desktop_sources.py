"""The answer bubble: no small meta line, sources as buttons, lookups, and the live activity."""

from pathlib import Path

import pytest
from desktop_support import KEY, sample_message
from PySide6.QtGui import QDesktopServices
from pytestqt.qtbot import QtBot
from test_desktop_coach import answer_event, start

from wow_coach.desktop.widgets.bubbles import CoachBubble

WIKI_PAGE = "https://warcraft.wiki.gg/wiki/Abigail_Shiel"


def newest_bubble(setup: object) -> CoachBubble:
    bubble = setup.page.chat._rows[-1].content  # type: ignore[attr-defined]
    assert isinstance(bubble, CoachBubble)
    return bubble


def sourced_event() -> dict[str, object]:
    event = answer_event("Sourced", answered_at=2_599)
    event["sources"] = [
        {"title": "Abigail Shiel", "url": WIKI_PAGE},
        {"title": "", "url": "https://www.example.com/page"},
        {"title": "bad", "url": "javascript:alert(1)"},
        {"title": "file", "url": "file:///etc/passwd"},
    ]
    event["lookups"] = [
        {"kind": "web", "text": 'Read the Warcraft Wiki page "Abigail Shiel"'},
        {"kind": "read", "text": "Read your character status"},
    ]
    return event


def test_an_answer_has_no_small_meta_line_and_shows_its_time_on_hover(
    qtbot: QtBot, tmp_path: Path
) -> None:
    setup = start(qtbot, tmp_path, answers=[])
    event = answer_event("Saved one", answered_at=2_599)
    event["written_to_game"] = True
    setup.event("answer", **event)
    joined = " ".join(setup.texts())
    assert "From " not in joined and "Also in your in-game panel" not in joined
    assert "just now" not in joined
    bubble = newest_bubble(setup)
    assert bubble.toolTip() == "Answered just now"
    setup.clock.now += 5 * 60
    setup.page._tick()
    assert bubble.toolTip() == "Answered 5 min ago"


def test_sources_are_link_buttons_with_title_or_site_and_the_link_as_tooltip(
    qtbot: QtBot, tmp_path: Path
) -> None:
    setup = start(qtbot, tmp_path, answers=[])
    setup.event("answer", **sourced_event())
    sources = newest_bubble(setup).sources_list
    assert sources is not None
    assert [b.text() for b in sources.buttons] == ["Abigail Shiel", "example.com"]
    assert [b.toolTip() for b in sources.buttons] == [WIKI_PAGE, "https://www.example.com/page"]


def test_clicking_a_source_opens_only_that_link(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []

    def fake_open(url: object) -> bool:
        opened.append(url.toString())  # type: ignore[attr-defined]
        return True

    monkeypatch.setattr(QDesktopServices, "openUrl", fake_open)
    setup = start(qtbot, tmp_path, answers=[])
    setup.event("answer", **sourced_event())
    sources = newest_bubble(setup).sources_list
    assert sources is not None
    assert opened == []  # nothing opens by itself
    sources.buttons[0].click()
    assert opened == [WIKI_PAGE]


def test_the_lookups_toggle_starts_folded_and_opens(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path, answers=[])
    setup.event("answer", **sourced_event())
    toggle = newest_bubble(setup).lookups_toggle
    assert toggle is not None and not toggle.opened
    assert "What the coach looked up (2)" in toggle.button.text()
    toggle.button.click()
    assert toggle.opened
    assert "Read your character status" in toggle.details.text()
    toggle.button.click()
    assert not toggle.opened


def test_lookups_are_hidden_when_the_player_turned_them_off(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path, answers=[], settings={"show_lookups": False})
    setup.event("answer", **sourced_event())
    bubble = newest_bubble(setup)
    assert bubble.lookups_toggle is None and bubble.sources_list is not None


def test_the_newest_activity_shows_in_the_typing_bubble(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path, answers=[])
    setup.page.chat.set_typing(True)
    setup.event("activity", character=KEY, text="Searched the Warcraft Wiki for bears", kind="web")
    assert setup.page.chat.activity_text == "Searched the Warcraft Wiki for bears"
    setup.event("activity", character=KEY, text="Read your character status", kind="read")
    assert setup.page.chat.activity_text == "Read your character status"
    setup.page.chat.set_typing(False)
    assert setup.page.chat.activity_text == ""


def test_activity_stays_hidden_when_lookups_are_off(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path, answers=[], settings={"show_lookups": False})
    setup.page.chat.set_typing(True)
    setup.event("activity", character=KEY, text="Read it", kind="read")
    assert setup.page.chat.activity_text == ""


def test_the_history_shows_sources_and_lookups_too(qtbot: QtBot, tmp_path: Path) -> None:
    stored = sample_message(
        "Train. Step.",
        role="assistant",
        message_id="app:1",
        seconds=2_400,
        provider="chatgpt",
        answer={
            "title": "Train",
            "steps": ["Step"],
            "text": "",
            "warnings": [],
            "sources": [{"title": "Abigail Shiel", "url": WIKI_PAGE}],
            "lookups": [{"kind": "web", "text": "Searched the web"}],
        },
    )
    setup = start(qtbot, tmp_path, answers=[], conversation=[stored])
    bubble = newest_bubble(setup)
    assert bubble.sources_list is not None and bubble.lookups_toggle is not None
