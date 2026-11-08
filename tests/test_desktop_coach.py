"""The Coach page's behavior: refreshing, asking, queues, answers, errors and the small card."""

from collections.abc import Callable
from pathlib import Path

from desktop_support import (
    KEY,
    FakeCore,
    make_bridge,
    sample_answer,
    sample_message,
    sample_state,
)
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton
from pytestqt.qtbot import QtBot

from wow_coach.desktop.bridge import CoreBridge
from wow_coach.desktop.main_window import MainWindow
from wow_coach.desktop.pages.coach import (
    BUSY_TEXT,
    MAX_TYPED_REMEMBERED,
    OPEN_BUSY_TEXT,
    OPEN_NONE_TEXT,
    SAVE_DIVIDER_TEXT,
    SAVED_NOTICE_TEXT,
    CoachPage,
)
from wow_coach.desktop.quick_actions import QUICK_ACTIONS
from wow_coach.desktop.theme import WOW
from wow_coach.desktop.widgets.styles import chat_style

NOW = 2_600.0  # ten minutes after the sample answer


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, start: float = NOW) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class Setup:
    """A page, its bridge, its fake core and its clock, wired together."""

    def __init__(self, qtbot: QtBot, tmp_path: Path, core: FakeCore) -> None:
        self.core = core
        self.bridge: CoreBridge = make_bridge(core)[0]
        self.clock = Clock()
        self.page = CoachPage(
            self.bridge,
            now=self.clock,
            card_settings=QSettings(str(tmp_path / "card.ini"), QSettings.Format.IniFormat),
        )
        qtbot.addWidget(self.page)
        self.bridge.state_changed.connect(self.page.show_state)
        self.bridge.refresh_state()

    def event(self, event_kind: str, /, **data: object) -> None:
        """Deliver a live event, then re-read the state (as the real bridge does)."""
        self.page.on_event(event_kind, data)
        self.bridge.refresh_state()

    def texts(self) -> list[str]:
        return self.page.chat.texts()


def start(qtbot: QtBot, tmp_path: Path, **state: object) -> Setup:
    core = FakeCore(raw_state=sample_state(**state))
    return Setup(qtbot, tmp_path, core)


def answer_event(title: str, *, answered_at: int, question: str | None = None) -> dict[str, object]:
    answer = sample_answer(title, answered_at=answered_at)
    answer["question"] = question
    return {"character": KEY, "answer": answer, "note": "", "written_to_game": False}


# ---- the header and the freshness pill ----------------------------------------------------


def test_the_pill_follows_the_clock_without_reading_the_disk(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path, last_save=2_590)
    pill = setup.page.header.pill
    assert (pill.text, pill.level) == ("Game data: just now", "success")
    reads = len(setup.core.state_reads)
    setup.clock.now = 2_590 + 12 * 60
    setup.page._tick()
    assert (pill.text, pill.level) == ("Game data: 12 min old", "warning")
    setup.clock.now = 2_590 + 3 * 3_600
    setup.page._tick()
    assert (pill.text, pill.level) == ("Game data: 3 h old", "muted")
    assert len(setup.core.state_reads) == reads


def test_the_pill_says_when_there_is_no_data(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path, last_save=None)
    assert setup.page.header.pill.text == "No game data yet"


def test_the_header_shows_the_character_and_a_picker_for_several(
    qtbot: QtBot, tmp_path: Path
) -> None:
    summary = {"name": "Thrall", "level": 12, "class_name": "Mage", "zone": "Durotar", "money": 250}
    setup = start(qtbot, tmp_path, character=summary)
    assert setup.page.header.picker_visible is False
    detail = setup.page.header.findChildren(QLabel)
    assert any("Level 12 Mage · Durotar · 2s 50c" in label.text() for label in detail)
    two = start(qtbot, tmp_path, characters=[KEY, "Other-Realm"], character=summary)
    assert two.page.header.picker_visible is True
    two.page.header.choose(1)
    assert two.bridge.selected_character == "Other-Realm"
    assert two.core.state_reads[-1] == "Other-Realm"


# ---- the game saves by itself --------------------------------------------------------------


def test_there_is_no_refresh_button_or_banner(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path)
    assert not hasattr(setup.page.header, "refresh_button")
    assert not hasattr(setup.page, "refresh_banner")
    texts = " ".join(label.text() for label in setup.page.findChildren(QLabel))
    buttons = [b.text() for b in setup.page.header.findChildren(QPushButton)]
    assert "Refresh game data" not in buttons and "Refresh" not in texts
    assert "Keep on top of the game" in buttons


def test_the_pill_explains_that_it_updates_by_itself(qtbot: QtBot, tmp_path: Path) -> None:
    pill = start(qtbot, tmp_path).page.header.pill
    assert pill.toolTip() == (
        "Updates by itself whenever the game saves: press your Save for the coach key "
        "in WoW, type /coach, or /reload."
    )


def test_a_question_is_asked_right_away(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path)
    setup.page.send_question("Where next?")
    assert setup.core.asked == [("Where next?", KEY)]
    assert setup.page.chat.typing_visible is True


def test_a_save_shows_a_calm_note_that_fades_and_updates_the_pill(
    qtbot: QtBot, tmp_path: Path
) -> None:
    setup = start(qtbot, tmp_path, answers=[sample_answer("Old", answered_at=2_000)])
    before = setup.page.chat.message_count()
    setup.page._save_notice_timer.setInterval(50)  # the real note stays about 3 seconds
    setup.core.raw_state = sample_state(
        last_save=2_599, answers=[sample_answer("Old", answered_at=2_000)]
    )
    setup.event("save", saved_at=2_599, problem=None)
    assert SAVED_NOTICE_TEXT in setup.texts()
    assert setup.page.header.pill.text == "Game data: just now"
    qtbot.waitUntil(lambda: SAVED_NOTICE_TEXT not in setup.texts(), timeout=3_000)
    assert setup.page.chat.message_count() == before


def test_two_saves_in_a_row_show_one_note(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path, answers=[sample_answer("Old", answered_at=2_000)])
    setup.event("save", saved_at=2_599, problem=None)
    setup.event("save", saved_at=2_600, problem=None)
    assert setup.texts().count(SAVED_NOTICE_TEXT) == 1


def test_a_save_in_an_empty_chat_keeps_the_welcome_screen(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path, answers=[])
    setup.event("save", saved_at=2_599, problem=None)
    assert setup.page.chat.message_count() == 0


# ---- the coach is busy ---------------------------------------------------------------------


def test_a_busy_coach_queues_the_question_and_sends_it_after_the_answer(
    qtbot: QtBot, tmp_path: Path
) -> None:
    setup = start(qtbot, tmp_path)
    setup.core.busy = True
    setup.page.send_question("Second question")
    assert setup.core.asked == []
    assert BUSY_TEXT in setup.texts()
    setup.core.busy = False
    setup.event("answer", **answer_event("First answer", answered_at=2_700))
    assert setup.core.asked == [("Second question", KEY)]


def test_a_failed_answer_also_releases_the_queue(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path)
    setup.core.busy = True
    setup.page.send_question("Waiting one")
    setup.core.busy = False
    setup.event("error", message="The AI had a hiccup.", kind="error")
    assert setup.core.asked == [("Waiting one", KEY)]


def test_a_usage_limit_drops_the_queue_and_offers_manage_usage(
    qtbot: QtBot, tmp_path: Path
) -> None:
    setup = start(qtbot, tmp_path)
    setup.core.busy = True
    setup.page.send_question("One")
    setup.core.busy = False
    setup.event("error", message="Your plan is used up for now.", kind="limit")
    assert setup.core.asked == []
    assert any("Manage usage" in text for text in setup.texts())
    assert any("Your plan is used up for now." in text for text in setup.texts())


def test_an_ordinary_error_has_no_manage_button(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path)
    setup.event("error", message="The AI had a hiccup.", kind="error")
    assert not any("Manage usage" in text for text in setup.texts())
    setup.event("error", message="")
    assert any("Something went wrong" in text for text in setup.texts())


# ---- quick actions -------------------------------------------------------------------------


def test_a_chip_sends_its_question_like_a_typed_one(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path)
    action = QUICK_ACTIONS[1]
    chip = next(c for c in setup.page._chip_buttons if c.text() == action.label)
    qtbot.mouseClick(chip, Qt.MouseButton.LeftButton)
    assert setup.core.asked == [(action.question, KEY)]
    assert action.question in setup.texts()


def test_explain_a_word_only_fills_the_box(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path)
    explain = next(a for a in QUICK_ACTIONS if a.fills_composer)
    setup.page.use_action(explain)
    assert setup.core.asked == []
    assert setup.page.composer.text() == "What does  mean?"
    box = setup.page.composer.findChild(QPlainTextEdit)
    assert box is not None
    assert box.textCursor().position() == len("What does ")


def test_the_welcome_cards_send_their_question(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path, answers=[])
    assert setup.page.stack.currentIndex() == 1  # the welcome
    card = setup.page.welcome.cards[0]
    card.clicked.emit()
    assert setup.core.asked == [(card.action.question, KEY)]
    assert setup.page.stack.currentIndex() == 0  # the chat


# ---- the conversation ----------------------------------------------------------------------


def test_history_is_shown_oldest_first_with_its_question(qtbot: QtBot, tmp_path: Path) -> None:
    older = sample_answer("Older answer", answered_at=1_500)
    newer = sample_answer("Newer answer", answered_at=2_500)
    setup = start(qtbot, tmp_path, answers=[newer, older])  # the state lists the newest first
    texts = setup.texts()
    assert [("Older answer" in t) for t in texts].index(True) < [
        ("Newer answer" in t) for t in texts
    ].index(True)
    assert "What now?" in texts[0]


def test_the_same_answer_is_never_shown_twice(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path)
    count = setup.page.chat.message_count()
    setup.bridge.refresh_state()
    setup.bridge.refresh_state()
    assert setup.page.chat.message_count() == count
    # A live answer, then the state that contains it, shows it once.
    event = answer_event("Brand new", answered_at=2_700, question="Fresh question?")
    setup.event("answer", **event)
    after_event = setup.page.chat.message_count()
    new_answer = event["answer"]
    assert isinstance(new_answer, dict)
    setup.core.raw_state = sample_state(answers=[new_answer, sample_answer()])
    setup.bridge.refresh_state()
    setup.bridge.refresh_state()
    assert setup.page.chat.message_count() == after_event
    assert sum("Brand new" in text for text in setup.texts()) == 1


def test_a_typed_question_is_not_repeated_when_its_answer_arrives(
    qtbot: QtBot, tmp_path: Path
) -> None:
    setup = start(qtbot, tmp_path, answers=[])
    setup.page.send_question("How do I fish?")
    setup.event("answer", **answer_event("Fishing", answered_at=2_700, question="How do I fish?"))
    assert sum("How do I fish?" in text for text in setup.texts()) == 1
    assert setup.page.chat.typing_visible is False


def test_questions_from_the_game_are_tagged_and_shown_once(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path, answers=[])
    setup.event("question", character=KEY, questions=[{"id": "q1", "text": "Where is Brill?"}])
    setup.event("question", character=KEY, questions=[{"id": "q1", "text": "Where is Brill?"}])
    assert setup.texts() == ["from the game Where is Brill?"]
    answer = answer_event("Brill is east", answered_at=2_700, question="Where is Brill?")
    reply = answer["answer"]
    assert isinstance(reply, dict)
    reply["question_id"] = "q1"
    setup.event("answer", **answer)
    assert sum("Where is Brill?" in text for text in setup.texts()) == 1


def test_answers_for_another_character_are_left_out(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path)
    count = setup.page.chat.message_count()
    other = answer_event("Not for you", answered_at=2_700)
    other["character"] = "Other-Realm"
    setup.event("answer", **other)
    assert setup.page.chat.message_count() == count


def test_answer_text_is_shown_as_plain_text_never_as_markup(qtbot: QtBot, tmp_path: Path) -> None:
    nasty = sample_answer("<b>Bold?</b>", answered_at=2_500)
    nasty["steps"] = ["<a href='https://evil.example'>click</a>"]
    nasty["text"] = "# Heading **x**"
    nasty["warnings"] = ["<img src=x>"]
    setup = start(qtbot, tmp_path, answers=[nasty])
    labels = setup.page.chat.findChildren(QLabel)
    shown = [label for label in labels if "<" in label.text() or "#" in label.text()]
    assert len(shown) >= 4
    for label in shown:
        assert label.textFormat() == Qt.TextFormat.PlainText
        assert not label.openExternalLinks()
    assert any(label.text() == "<b>Bold?</b>" for label in labels)


def test_scrolled_up_readers_get_a_new_answer_pill_instead_of_being_moved(
    qtbot: QtBot, tmp_path: Path
) -> None:
    many = [sample_answer(f"Answer {i}", answered_at=1_000 + i) for i in range(30, 0, -1)]
    setup = start(qtbot, tmp_path, answers=many)
    setup.page.resize(900, 600)
    setup.page.show()
    qtbot.wait(700)  # let the chat settle at the bottom
    bar = setup.page.chat.verticalScrollBar()
    bar.setValue(0)
    qtbot.wait(100)
    setup.event("answer", **answer_event("Late one", answered_at=2_900))
    assert setup.page.chat.pill_visible is True
    assert bar.value() == 0
    setup.page.chat.scroll_to_newest()
    assert setup.page.chat.pill_visible is False


# ---- not signed in, problems and open questions ----------------------------------------------


def test_not_signed_in_turns_off_asking_and_offers_sign_in(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path, signed_in=False, answers=[])
    page = setup.page
    assert page.sign_in_card.isHidden() is False
    assert page.composer.send_enabled is False
    assert all(not chip.isEnabled() for chip in page._chip_buttons)
    page.send_question("Hello?")
    assert setup.core.asked == []
    assert page.sign_in_card.button.text() == "Open the ChatGPT page"
    seen: list[str] = []
    page.navigate.connect(seen.append)
    page.sign_in_card.button.click()
    assert seen == ["chatgpt"]


def test_signed_in_hides_the_sign_in_card(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path)
    assert setup.page.sign_in_card.isHidden() is True
    assert all(chip.isEnabled() for chip in setup.page._chip_buttons)


def test_the_problem_sentence_is_shown_calmly(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path, problem="No saved game data yet. In the game, type /coach.")
    assert setup.page.problem_banner.isHidden() is False
    assert "type /coach" in setup.page.problem_banner.text
    setup.core.raw_state = sample_state(problem=None)
    setup.bridge.refresh_state()
    assert setup.page.problem_banner.isHidden() is True


def test_open_questions_bar_offers_answer_now(qtbot: QtBot, tmp_path: Path) -> None:
    waiting = [{"id": "a", "text": "x", "asked_at": 1}, {"id": "b", "text": "y", "asked_at": 2}]
    setup = start(qtbot, tmp_path, open_questions=waiting)
    bar = setup.page.questions_bar
    assert bar.isHidden() is False
    assert bar.text == "2 questions from the game are waiting"
    bar.button.click()
    assert setup.core.answered_open_for == [None]
    assert setup.page.chat.typing_visible is True


def test_open_questions_bar_handles_busy_and_none(qtbot: QtBot, tmp_path: Path) -> None:
    waiting = [{"id": "a", "text": "x", "asked_at": 1}]
    setup = start(qtbot, tmp_path, open_questions=waiting)
    assert setup.page.questions_bar.text == "1 question from the game is waiting"
    setup.core.busy = True
    setup.page.answer_open_questions()
    assert OPEN_BUSY_TEXT in setup.texts()
    setup.core.open_result = "none"
    setup.page.answer_open_questions()
    assert OPEN_NONE_TEXT in setup.texts()


def test_answer_now_waits_for_the_background_result(qtbot: QtBot, tmp_path: Path) -> None:
    waiting = [{"id": "a", "text": "x", "asked_at": 1}]
    setup = start(qtbot, tmp_path, open_questions=waiting)
    jobs: list[Callable[[], None]] = []
    setup.bridge._run = jobs.append  # hold the background work back
    setup.page.answer_open_questions()
    assert setup.page.chat.typing_visible is False  # nothing is known yet
    jobs.pop()()
    assert setup.page.chat.typing_visible is True


def test_open_questions_bar_hides_when_the_game_questions_are_answered_automatically(
    qtbot: QtBot, tmp_path: Path
) -> None:
    waiting = [{"id": "a", "text": "x", "asked_at": 1}]
    setup = start(
        qtbot,
        tmp_path,
        open_questions=waiting,
        settings={"answer_questions_from_game": True},
    )
    assert setup.page.questions_bar.isHidden() is True


# ---- the keep-on-top card --------------------------------------------------------------------


def test_the_card_shows_the_newest_answer_and_follows_new_ones(
    qtbot: QtBot, tmp_path: Path
) -> None:
    older = sample_answer("Older", answered_at=1_500)
    newer = sample_answer("Newer", answered_at=2_500)
    setup = start(qtbot, tmp_path, answers=[newer, older])
    setup.page.toggle_card()
    card = setup.page.card
    assert card is not None
    assert card.texts[0] == "Newer"
    setup.event("answer", **answer_event("Newest", answered_at=2_900))
    assert card.texts[0] == "Newest"
    assert setup.page.header.keep_button.text() == "Hide the small card"
    setup.page.toggle_card()
    assert card.isVisible() is False
    assert setup.page.header.keep_button.text() == "Keep on top of the game"


def test_the_card_can_bring_the_main_window_back(qtbot: QtBot, tmp_path: Path) -> None:
    bridge, _core = make_bridge()
    window = MainWindow(bridge)
    qtbot.addWidget(window)
    page = window.pages[0]
    assert isinstance(page, CoachPage)
    page._card_settings = QSettings(str(tmp_path / "card.ini"), QSettings.Format.IniFormat)
    window.show()
    window.showMinimized()
    page.toggle_card()
    assert page.card is not None
    page.card.open_requested.emit()
    assert not window.isMinimized()
    page.card.close()


def test_a_failed_state_read_does_not_wipe_the_chat(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path)
    count = setup.page.chat.message_count()
    assert count > 0

    class Broken(FakeCore):
        def state(self, wanted_character: str | None) -> dict[str, object]:  # noqa: ARG002
            raise RuntimeError("disk on fire")

    setup.bridge._core = Broken()  # type: ignore[assignment]
    setup.bridge.refresh_state()
    assert setup.page.chat.message_count() == count


def test_coach_answers_are_drawn_on_parchment_with_dark_ink() -> None:
    style = chat_style(WOW)
    assert WOW.parchment in style and WOW.on_parchment in style
    assert WOW.success in style


# ---- the busy queue retries on its own -------------------------------------------------------


def test_a_queued_question_is_retried_by_the_timer_without_any_event(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """The coach can stay busy after its answer was published (alerts, speech...)."""
    setup = start(qtbot, tmp_path)
    setup.core.busy = True
    setup.page.send_question("First waiting")
    setup.page.send_question("Second waiting")
    assert setup.page._queue_timer.isActive() is True
    setup.page._queue_timer.timeout.emit()  # still busy: nothing goes out
    assert setup.core.asked == []
    setup.core.busy = False
    setup.page._queue_timer.timeout.emit()
    setup.page._queue_timer.timeout.emit()
    assert [q for q, _ in setup.core.asked] == ["First waiting", "Second waiting"]
    assert setup.page._queue_timer.isActive() is False


def test_the_goes_next_notice_is_shown_once_however_often_it_retries(
    qtbot: QtBot, tmp_path: Path
) -> None:
    setup = start(qtbot, tmp_path)
    setup.core.busy = True
    setup.page.send_question("Waiting")
    for _ in range(3):
        setup.page._queue_timer.timeout.emit()
    assert setup.texts().count(BUSY_TEXT) == 1


def test_an_event_retry_that_fails_keeps_the_order_and_the_question(
    qtbot: QtBot, tmp_path: Path
) -> None:
    setup = start(qtbot, tmp_path)
    setup.core.busy = True
    setup.page.send_question("One")
    setup.page.send_question("Two")
    setup.event("answer", **answer_event("Done", answered_at=2_700))  # core still busy
    assert setup.core.asked == []
    setup.core.busy = False
    setup.page._queue_timer.timeout.emit()
    assert [q for q, _ in setup.core.asked] == ["One"]


def test_an_info_event_releases_the_queue(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path)
    setup.core.busy = True
    setup.page.send_question("Queued behind it")
    setup.core.busy = False
    setup.event("info", text="Those questions were already answered.")
    assert setup.core.asked == [("Queued behind it", KEY)]


def test_an_info_event_alone_turns_the_typing_dots_off(qtbot: QtBot, tmp_path: Path) -> None:
    waiting = [{"id": "a", "text": "x", "asked_at": 1}]
    setup = start(qtbot, tmp_path, open_questions=waiting)
    setup.page.answer_open_questions()
    assert setup.page.chat.typing_visible is True
    setup.event("info", text="Those questions were already answered.")
    assert setup.page.chat.typing_visible is False


def test_a_waiting_question_is_asked_for_the_character_it_was_typed_for(
    qtbot: QtBot, tmp_path: Path
) -> None:
    setup = start(qtbot, tmp_path)
    setup.core.busy = True
    setup.page.send_question("For the first one")
    setup.bridge._selected = "Other-Realm"  # the player picks someone else
    setup.core.busy = False
    setup.page._queue_timer.timeout.emit()
    assert setup.core.asked == [("For the first one", KEY)]


def test_a_character_switch_drops_the_old_characters_waiting_questions(
    qtbot: QtBot, tmp_path: Path
) -> None:
    setup = start(qtbot, tmp_path)
    setup.core.busy = True
    setup.page.send_question("Queued for the first")
    setup.core.raw_state = sample_state(selected="Other-Realm", characters=[KEY, "Other-Realm"])
    setup.bridge.refresh_state()
    setup.core.busy = False
    setup.page._queue_timer.timeout.emit()
    setup.event("save", saved_at=2_599, problem=None)
    assert setup.core.asked == []
    assert setup.page._queue_timer.isActive() is False
    assert setup.page.chat.typing_visible is False


def test_an_answer_without_a_question_adds_no_question_bubble(qtbot: QtBot, tmp_path: Path) -> None:
    """The real engine drops ``question`` unless the answer has a valid id."""
    setup = start(qtbot, tmp_path, answers=[])
    setup.page.send_question("How do I fish?")
    setup.event("answer", **answer_event("Fishing", answered_at=2_700, question=None))
    assert sum("How do I fish?" in text for text in setup.texts()) == 1


def test_remembered_typed_questions_cannot_grow_forever(qtbot: QtBot, tmp_path: Path) -> None:
    setup = start(qtbot, tmp_path, answers=[])
    for number in range(MAX_TYPED_REMEMBERED + 30):
        setup.page.send_question(f"Question {number}")
    assert len(setup.page._typed_questions) == MAX_TYPED_REMEMBERED


def test_the_automatic_question_after_a_save_is_a_slim_line_not_a_bubble(
    qtbot: QtBot, tmp_path: Path
) -> None:
    conversation = [
        sample_message(
            "Status updated: my game just saved...",
            message_id="save:1",
            seconds=1_900,
            source="save",
        ),
        sample_message("Back to Brill.", role="assistant", message_id="app:2", seconds=1_901),
    ]
    setup = start(qtbot, tmp_path, conversation=conversation)
    texts = setup.texts()
    assert SAVE_DIVIDER_TEXT in texts
    assert not any(text.startswith("Status updated") for text in texts)
