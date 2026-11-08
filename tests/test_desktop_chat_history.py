"""The Coach page shows the stored chat history: all sources, once each, in time order."""

from pathlib import Path

from desktop_support import KEY, FakeCore, make_bridge, sample_answer, sample_message, sample_state
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QLabel, QPushButton
from pytestqt.qtbot import QtBot

from wow_coach.desktop.pages.coach import CoachPage
from wow_coach.desktop.state import read_state
from wow_coach.desktop.widgets.bubbles import COLLAPSE_AFTER_CHARS, ReplyBubble

NOW = 5_000.0


class Setup:
    """A page over a fake core whose state holds a chat history."""

    def __init__(self, qtbot: QtBot, tmp_path: Path, **state: object) -> None:
        self.core = FakeCore(raw_state=sample_state(answers=[], **state))
        self.bridge = make_bridge(self.core)[0]
        self.page = CoachPage(
            self.bridge,
            now=lambda: NOW,
            card_settings=QSettings(str(tmp_path / "card.ini"), QSettings.Format.IniFormat),
        )
        qtbot.addWidget(self.page)
        self.bridge.state_changed.connect(self.page.show_state)
        self.bridge.refresh_state()

    def texts(self) -> list[str]:
        return self.page.chat.texts()

    def set_conversation(self, *messages: dict[str, object]) -> None:
        self.core.raw_state = {**self.core.raw_state, "conversation": list(messages)}
        self.bridge.refresh_state()


def stored_answer(title: str) -> dict[str, object]:
    return {"title": title, "steps": ["Step one"], "text": "Because.", "warnings": []}


def test_every_source_is_shown_oldest_first_with_its_tag(qtbot: QtBot, tmp_path: Path) -> None:
    setup = Setup(qtbot, tmp_path)
    setup.set_conversation(
        sample_message("Where is Brill?", message_id="game:q1", seconds=1_000, source="game"),
        sample_message("Plain app question", message_id="a1", seconds=1_100),
        sample_message("Ask the foreman.", role="assistant", message_id="c1", seconds=1_200,
                       source="claude-code", provider="claude-code"),
        sample_message("Outside tip", role="assistant", message_id="o1", seconds=1_300,
                       source="outside"),
        sample_message("Question for Claude", message_id="c0", seconds=1_400, source="claude-code"),
    )  # fmt: skip
    texts = setup.texts()
    assert texts[0].startswith("from the game") and "Where is Brill?" in texts[0]
    assert "from your Claude coach" in texts[2] and "Ask the foreman." in texts[2]
    assert "from another app" in texts[3] and "Outside tip" in texts[3]
    assert "from your Claude coach" in texts[4] and "Question for Claude" in texts[4]
    assert "from" not in texts[1].replace("Plain app question", "")  # no tag for the app itself


def test_structured_answers_keep_their_parchment_layout(qtbot: QtBot, tmp_path: Path) -> None:
    setup = Setup(qtbot, tmp_path)
    setup.set_conversation(
        sample_message("Next?", message_id="q", seconds=1_000),
        sample_message("Train. Step one Because.", role="assistant", message_id="a", seconds=1_010,
                       provider="chatgpt", answer=stored_answer("Train")),
    )  # fmt: skip
    answer_text = setup.texts()[1]
    assert "Train" in answer_text and "Step one" in answer_text and "Because." in answer_text
    assert "From ChatGPT" not in answer_text  # no small "from ..." line under answers


def test_a_plain_reply_is_plain_text_and_long_ones_fold(qtbot: QtBot, tmp_path: Path) -> None:
    long_text = "<b>word</b> " * 200
    setup = Setup(qtbot, tmp_path)
    setup.set_conversation(
        sample_message(long_text, role="assistant", message_id="c1", seconds=1_000,
                       source="claude-code", provider="claude-code"),
    )  # fmt: skip
    bubble = setup.page.chat.findChildren(ReplyBubble)[0]
    assert bubble.folded
    shown = [label for label in bubble.findChildren(QLabel) if "<b>word</b>" in label.text()]
    assert len(shown) == 1 and shown[0].textFormat() == Qt.TextFormat.PlainText
    assert len(shown[0].text()) <= COLLAPSE_AFTER_CHARS + 1
    bubble.toggle_button.click()
    assert not bubble.folded and len(shown[0].text()) == len(long_text)
    assert bubble.toggle_button.text() == "Show less"
    bubble.toggle_button.click()
    assert bubble.folded


def test_a_short_reply_has_no_show_more_button(qtbot: QtBot, tmp_path: Path) -> None:
    setup = Setup(qtbot, tmp_path)
    short = sample_message("Short.", role="assistant", message_id="c1", seconds=1_000)
    setup.set_conversation(short)
    bubble = setup.page.chat.findChildren(ReplyBubble)[0]
    buttons = [b for b in bubble.findChildren(QPushButton) if not b.isHidden()]
    assert buttons == []


def test_a_message_is_never_shown_twice(qtbot: QtBot, tmp_path: Path) -> None:
    setup = Setup(qtbot, tmp_path)
    first = sample_message("Hello", message_id="m1", seconds=1_000)
    setup.set_conversation(first)
    setup.bridge.refresh_state()
    setup.set_conversation(first)
    assert setup.page.chat.message_count() == 1
    second = sample_message("Hi there", role="assistant", message_id="m2", seconds=1_100,
                            source="claude-code")  # fmt: skip
    setup.set_conversation(first, second)
    assert setup.page.chat.message_count() == 2


def test_a_live_answer_and_its_stored_copy_show_once(qtbot: QtBot, tmp_path: Path) -> None:
    setup = Setup(qtbot, tmp_path)
    setup.page.send_question("How do I fish?")  # no sign-in needed? the sample state is signed in
    live = sample_answer("Fishing", answered_at=2_000)
    live["question"] = "How do I fish?"
    setup.page.on_event(
        "answer", {"character": KEY, "answer": live, "note": "", "written_to_game": False}
    )
    count = setup.page.chat.message_count()
    assert count == 2  # the typed question and the answer
    setup.set_conversation(
        sample_message("How do I fish?", message_id="app:q", seconds=1_999),
        sample_message("Fishing. x", role="assistant", message_id="app:a", seconds=2_000,
                       provider="chatgpt", answer=stored_answer("Fishing")),
    )  # fmt: skip
    assert setup.page.chat.message_count() == count
    assert sum("Fishing" in t for t in setup.texts()) == 1
    assert sum("How do I fish?" in t for t in setup.texts()) == 1


def test_a_game_question_shown_live_is_not_repeated_from_the_history(
    qtbot: QtBot, tmp_path: Path
) -> None:
    setup = Setup(qtbot, tmp_path)
    setup.page.on_event(
        "question", {"character": KEY, "questions": [{"id": "q1", "text": "Where?"}]}
    )
    setup.set_conversation(
        sample_message("Where?", message_id="game:q1", seconds=1_000, source="game")
    )
    assert setup.texts() == ["from the game Where?"]


def test_older_chats_arriving_later_are_put_in_time_order(qtbot: QtBot, tmp_path: Path) -> None:
    setup = Setup(qtbot, tmp_path)
    setup.set_conversation(sample_message("Newest", message_id="n", seconds=3_000))
    setup.page.send_question("Still waiting")
    setup.set_conversation(
        sample_message("Oldest", message_id="o", seconds=1_000, source="claude-code"),
        sample_message("Newest", message_id="n", seconds=3_000),
    )
    texts = setup.texts()
    assert "Oldest" in texts[0] and "Newest" in texts[1]
    assert "Still waiting" in texts[2]  # the question that has no answer yet is kept
    assert len(texts) == 3


def test_answers_only_the_game_file_has_are_still_shown_in_order(
    qtbot: QtBot, tmp_path: Path
) -> None:
    setup = Setup(qtbot, tmp_path)
    old = sample_answer("From the file", answered_at=500)
    setup.core.raw_state = {
        **setup.core.raw_state,
        "answers": [old],
        "conversation": [sample_message("Newer message", message_id="m", seconds=1_000)],
    }
    setup.bridge.refresh_state()
    texts = setup.texts()
    assert any("From the file" in t for t in texts)
    assert "From the file" in texts[1] and "Newer message" in texts[-1]  # question first, then it


def test_an_answer_in_both_the_file_and_the_history_shows_once(
    qtbot: QtBot, tmp_path: Path
) -> None:
    setup = Setup(qtbot, tmp_path)
    in_file = sample_answer("Same one", answered_at=1_000)
    in_file["question"] = None
    setup.core.raw_state = {
        **setup.core.raw_state,
        "answers": [in_file],
        "conversation": [
            sample_message(
                "x",
                role="assistant",
                message_id="a",
                seconds=1_000,
                provider="chatgpt",
                answer=stored_answer("Same one"),
            ),
        ],
    }
    setup.bridge.refresh_state()
    assert sum("Same one" in t for t in setup.texts()) == 1


def test_a_second_character_gets_its_own_chat(qtbot: QtBot, tmp_path: Path) -> None:
    setup = Setup(qtbot, tmp_path)
    setup.set_conversation(sample_message("For the first", message_id="m1", seconds=1_000))
    setup.core.raw_state = {
        **setup.core.raw_state,
        "selected": "Other-Realm",
        "conversation": [sample_message("For the other", message_id="m2", seconds=1_000)],
    }
    setup.bridge.refresh_state()
    assert len(setup.texts()) == 1 and "For the other" in setup.texts()[0]


# ---- reading the state ---------------------------------------------------------------------


def test_the_state_reads_messages_and_ignores_broken_ones() -> None:
    good = sample_message("Hi", message_id="m1", seconds=1_000, source="claude-code")
    raw = sample_state(
        conversation=[
            good,
            {"role": "user"},
            {"role": "boss", "content": "x"},
            "not a dict",
            {"role": "user", "content": "   "},
            {**good, "id": "m2", "at": "garbage", "answer": "nope"},
        ]
    )
    state = read_state(raw)
    assert [m.id for m in state.conversation] == ["m1", "m2"]
    assert (
        state.conversation[0].seconds == 1_000.0 and state.conversation[0].source == "claude-code"
    )
    assert state.conversation[1].seconds is None and state.conversation[1].answer is None


def test_a_state_without_a_conversation_has_none() -> None:
    raw = sample_state()
    del raw["conversation"]
    assert read_state(raw).conversation == ()
