"""The Coach page's building blocks: words and numbers, the refresh banner, the composer, the
small card, the quick actions and the character summary."""

from pathlib import Path

import pytest
from desktop_support import sample_state
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtWidgets import QPlainTextEdit
from pytestqt.qtbot import QtBot

from wow_coach.advice.contract import MAX_QUESTION_CHARS
from wow_coach.app.views import character_summary
from wow_coach.desktop.compact import POSITION_KEY, CompactCard
from wow_coach.desktop.quick_actions import QUICK_ACTIONS, suggestions
from wow_coach.desktop.state import AnswerView, read_state
from wow_coach.desktop.widgets.composer import COUNTER_FROM, Composer
from wow_coach.desktop.widgets.formatting import (
    age_words,
    freshness,
    gold_text,
    relative_time,
)
from wow_coach.desktop.widgets.header import character_label
from wow_coach.desktop.widgets.refresh_banner import (
    HINT_AFTER_SECONDS,
    STILL_WAITING_TEXT,
    WAITING_TEXT,
    RefreshBanner,
)
from wow_coach.savedvars import Character

# ---- words and numbers ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("age", "text", "level"),
    [
        (0, "Game data: just now", "success"),
        (59, "Game data: just now", "success"),
        (60, "Game data: 1 min old", "success"),
        (599, "Game data: 9 min old", "success"),
        (600, "Game data: 10 min old", "warning"),
        (3_599, "Game data: 59 min old", "warning"),
        (3_600, "Game data: 1 h old", "muted"),
        (3 * 3_600, "Game data: 3 h old", "muted"),
        (2 * 86_400, "Game data: 2 days old", "muted"),
        (-30, "Game data: just now", "success"),  # a clock that is a little behind
    ],
)
def test_freshness_words_and_color_at_the_boundaries(age: int, text: str, level: str) -> None:
    result = freshness(10_000, 10_000 + age)
    assert (result.text, result.level) == (text, level)


def test_no_save_means_no_game_data_yet() -> None:
    result = freshness(None, 10_000)
    assert (result.text, result.level) == ("No game data yet", "muted")


def test_money_is_written_like_the_game_does() -> None:
    assert gold_text(123_405) == "12g 34s 5c"
    assert gold_text(10_000) == "1g 0s 0c"
    assert gold_text(250) == "2s 50c"
    assert gold_text(0) == "0c"


def test_relative_time_words() -> None:
    assert relative_time(5) == "just now"
    assert relative_time(12 * 60) == "12 min ago"
    assert relative_time(86_400) == "1 day ago"
    assert age_words(3 * 3_600) == "3 h"


# ---- the refresh banner -----------------------------------------------------------------


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def test_banner_waits_then_shows_the_hint_after_two_minutes(qtbot: QtBot) -> None:
    clock = Clock()
    banner = RefreshBanner(now=clock)
    qtbot.addWidget(banner)
    assert banner.state == "idle"
    banner.start()
    assert banner.state == "waiting"
    assert banner.message == WAITING_TEXT
    clock.now += HINT_AFTER_SECONDS - 1
    banner.tick()
    assert banner.hint_visible is False
    clock.now += 1
    banner.tick()
    assert banner.hint_visible is True
    assert STILL_WAITING_TEXT.startswith("Still waiting")


def test_banner_turns_into_a_success_message_and_fades_away(qtbot: QtBot) -> None:
    clock = Clock()
    banner = RefreshBanner(now=clock, done_visible_ms=20)
    qtbot.addWidget(banner)
    banner.start()
    banner.mark_saved(int(clock.now) - 5)
    assert banner.state == "done"
    assert banner.message == "Got it: fresh data from just now"
    with qtbot.waitSignal(banner.closed, timeout=3_000):
        pass
    assert banner.state == "idle"
    assert banner.isHidden()


def test_a_save_without_a_waiting_banner_changes_nothing(qtbot: QtBot) -> None:
    banner = RefreshBanner(now=Clock())
    qtbot.addWidget(banner)
    banner.mark_saved(5)
    assert banner.state == "idle"


def test_cancel_stops_waiting_and_says_so(qtbot: QtBot) -> None:
    banner = RefreshBanner(now=Clock())
    qtbot.addWidget(banner)
    banner.start()
    with qtbot.waitSignal(banner.cancelled):
        banner.cancel()
    assert banner.state == "idle"
    assert banner.isHidden()


# ---- the composer ---------------------------------------------------------------------


def _edit(composer: Composer) -> QPlainTextEdit:
    box = composer.findChild(QPlainTextEdit)
    assert box is not None
    return box


def test_send_is_off_while_the_box_is_empty(qtbot: QtBot) -> None:
    composer = Composer()
    qtbot.addWidget(composer)
    assert composer.send_enabled is False
    composer.set_text("   ")
    assert composer.send_enabled is False
    composer.set_text("Hello")
    assert composer.send_enabled is True


def test_enter_sends_and_shift_enter_makes_a_new_line(qtbot: QtBot) -> None:
    composer = Composer()
    qtbot.addWidget(composer)
    sent: list[str] = []
    composer.submitted.connect(sent.append)
    box = _edit(composer)
    qtbot.keyClicks(box, "Hello")
    qtbot.keyClick(box, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    qtbot.keyClicks(box, "world")
    assert composer.text() == "Hello\nworld"
    assert sent == []
    qtbot.keyClick(box, Qt.Key.Key_Return)
    assert sent == ["Hello\nworld"]
    assert composer.text() == ""


def test_the_box_grows_with_the_text_up_to_six_lines(qtbot: QtBot) -> None:
    composer = Composer()
    qtbot.addWidget(composer)
    composer.show()
    one_line = _edit(composer).height()
    composer.set_text("\n".join(["line"] * 3))
    three_lines = _edit(composer).height()
    composer.set_text("\n".join(["line"] * 20))
    many_lines = _edit(composer).height()
    composer.set_text("\n".join(["line"] * 6))
    assert one_line < three_lines < many_lines
    assert many_lines == _edit(composer).height()


def test_long_text_is_cut_and_a_counter_appears_near_the_limit(qtbot: QtBot) -> None:
    composer = Composer()
    qtbot.addWidget(composer)
    composer.set_text("a" * (COUNTER_FROM - 1))
    assert composer.counter_text == ""
    composer.set_text("a" * COUNTER_FROM)
    assert composer.counter_text == f"{COUNTER_FROM} / {MAX_QUESTION_CHARS}"
    composer.set_text("b" * (MAX_QUESTION_CHARS + 50))
    assert len(composer.text()) == MAX_QUESTION_CHARS


def test_a_disabled_composer_does_not_send(qtbot: QtBot) -> None:
    composer = Composer()
    qtbot.addWidget(composer)
    composer.set_text("Hello")
    composer.set_input_enabled(False)
    sent: list[str] = []
    composer.submitted.connect(sent.append)
    composer.submit()
    assert sent == []
    assert composer.send_enabled is False


# ---- quick actions ---------------------------------------------------------------------


def test_every_quick_action_fits_the_question_limit_and_has_a_tooltip() -> None:
    assert QUICK_ACTIONS[0].label == "What next?"
    for action in QUICK_ACTIONS:
        assert len(action.question) <= MAX_QUESTION_CHARS
        assert action.tooltip


def test_explain_a_word_puts_the_cursor_in_the_gap() -> None:
    explain = next(a for a in QUICK_ACTIONS if a.fills_composer)
    assert explain.question == "What does  mean?"
    assert explain.question[: explain.cursor_position] == "What does "
    assert len(suggestions()) == 3


# ---- the small card ---------------------------------------------------------------------


def _answer(title: str, answered_at: int = 2_000) -> AnswerView:
    return AnswerView(title, ("Step one", "Step two"), "", (), "ChatGPT", answered_at, None, None)


def test_the_card_is_a_frameless_tool_window_that_stays_on_top(
    qtbot: QtBot, tmp_path: Path
) -> None:
    card = CompactCard(QSettings(str(tmp_path / "card.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(card)
    flags = card.windowFlags()
    assert flags & Qt.WindowType.Tool
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert card.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)


def test_the_card_shows_title_and_numbered_steps(qtbot: QtBot, tmp_path: Path) -> None:
    card = CompactCard(QSettings(str(tmp_path / "card.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(card)
    card.show_answer(_answer("Go to Brill"))
    assert card.texts == ["Go to Brill", "1. Step one", "2. Step two"]
    card.show_answer(None)
    assert "No answers yet" in card.texts[0]


def test_the_card_remembers_where_it_was_left(qtbot: QtBot, tmp_path: Path) -> None:
    path = str(tmp_path / "card.ini")
    card = CompactCard(QSettings(path, QSettings.Format.IniFormat))
    qtbot.addWidget(card)
    card.move(50, 60)
    card.remember_position()
    again = CompactCard(QSettings(path, QSettings.Format.IniFormat))
    qtbot.addWidget(again)
    again.show_at_saved_position()
    assert again.pos() == QPoint(50, 60)
    assert QSettings(path, QSettings.Format.IniFormat).contains(POSITION_KEY)


def test_the_close_button_tells_the_page(qtbot: QtBot, tmp_path: Path) -> None:
    card = CompactCard(QSettings(str(tmp_path / "card.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(card)
    card.show()
    with qtbot.waitSignal(card.closed):
        card.close()


# ---- the character summary ---------------------------------------------------------------


def test_character_summary_reads_the_snapshot() -> None:
    character = Character(
        key="Thrall-Realm",
        snapshot={
            "name": "Thrall",
            "level": 12,
            "race": "Orc",
            "class": "Shaman",
            "zone": "Durotar",
            "money": 123_405,
        },
        history=[],
    )
    summary = character_summary(character)
    assert summary == {
        "name": "Thrall",
        "level": 12,
        "race": "Orc",
        "class_name": "Shaman",
        "zone": "Durotar",
        "money": 123_405,
    }
    view = read_state(sample_state(character=summary)).character
    assert view is not None
    assert (view.name, view.level, view.class_name, view.money) == ("Thrall", 12, "Shaman", 123_405)


def test_character_summary_copes_with_a_thin_save() -> None:
    thin = Character(key="Jaina-Realm", snapshot={"level": "x"}, history=[])
    summary = character_summary(thin)
    assert summary is not None
    assert summary["name"] == "Jaina"
    assert summary["level"] is None
    assert character_summary(None) is None
    assert read_state(sample_state()).character is None


def test_the_picker_shows_name_and_realm_but_hands_back_the_key() -> None:
    assert character_label("Thrall-Some Realm 8") == "Thrall (Some Realm 8)"
    assert character_label("NoRealm") == "NoRealm"


def test_very_old_or_broken_times_read_as_over_a_year() -> None:
    assert relative_time(400 * 86_400) == "over a year ago"
    assert relative_time(2 * 86_400) == "2 days ago"
