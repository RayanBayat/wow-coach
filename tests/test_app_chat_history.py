"""The core keeps answers written by other apps in the chat history, and shows the history."""

from pathlib import Path

from test_app_support import KEY, make_answer, make_rig

from wow_coach.engine.conversation import (
    ChatMessage,
    append_messages,
    conversation_file,
    read_messages,
)


def contents(state: dict[str, object]) -> list[object]:
    """The ``content`` of every message in a state's conversation."""
    conversation = state["conversation"]
    assert isinstance(conversation, list)
    return [item["content"] for item in conversation]


def test_an_outside_answer_is_kept_once_with_its_question(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    answer = make_answer("From Claude", 1_794_000_000, question_id="q1")
    rig.core.publish_outside_answer(KEY, answer)
    rig.core.publish_outside_answer(KEY, answer)  # seen again: no duplicate
    found = read_messages(conversation_file(rig.settings_file.parent, KEY))
    assert [(m.role, m.source) for m in found] == [("user", "outside"), ("assistant", "outside")]
    assert found[0].content == "What now?"
    assert found[1].answer is not None and found[1].answer.title == "From Claude"
    assert found[1].at.startswith("2026-")


def test_state_carries_the_newest_messages_oldest_first(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    path = conversation_file(rig.settings_file.parent, KEY)
    append_messages(
        path,
        [
            ChatMessage("user", f"m{n}", f"id{n}", f"2026-11-07T10:{n // 60:02d}:{n % 60:02d}Z")
            for n in range(250)
        ],
    )
    shown = contents(rig.core.state(None))
    assert len(shown) == 200
    assert shown[0] == "m50" and shown[-1] == "m249"


def test_state_has_an_empty_conversation_without_history(tmp_path: Path) -> None:
    assert make_rig(tmp_path).core.state(None)["conversation"] == []


def test_claude_chats_are_hidden_when_turned_off(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    path = conversation_file(rig.settings_file.parent, KEY)
    append_messages(
        path,
        [
            ChatMessage("user", "from claude", "c1", "2026-11-07T10:00:00Z", "claude-code"),
            ChatMessage("user", "from app", "c2", "2026-11-07T10:00:01Z", "app"),
        ],
    )
    rig.core.change_settings({"use_claude_chats": False})
    assert contents(rig.core.state(None)) == ["from app"]
