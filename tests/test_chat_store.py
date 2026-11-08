"""Tests for the chat store: ``conversations/<character>.jsonl``, format v1."""

import json
import threading
from pathlib import Path

from wow_coach.engine.conversation import (
    FOLDER_NAME,
    MAX_MESSAGE_CHARS,
    MAX_STORED_MESSAGES,
    ChatAnswer,
    ChatMessage,
    Lookup,
    append_messages,
    conversation_path,
    message_from_dict,
    message_to_dict,
    new_message_id,
    now_iso,
    read_messages,
)
from wow_coach.engine.sources import SourceLink


def message(
    content: str,
    *,
    role: str = "user",
    message_id: str | None = None,
    at: str = "2026-11-07T10:00:00Z",
) -> ChatMessage:
    assert role in ("user", "assistant")
    return ChatMessage(
        role="user" if role == "user" else "assistant",
        content=content,
        id=message_id or new_message_id(),
        at=at,
    )


def test_path_is_file_safe(tmp_path: Path) -> None:
    path = conversation_path("A/b:c-Realm", environ={"WOW_COACH_DATA_DIR": str(tmp_path)})
    assert path.parent.name == FOLDER_NAME
    assert path.name == "A_b_c-Realm.jsonl"


def test_messages_round_trip_with_every_field(tmp_path: Path) -> None:
    path = tmp_path / "c" / "x.jsonl"
    answer = ChatAnswer(title="T", steps=("one", "two"), text="why", warnings=("careful",))
    original = ChatMessage(
        role="assistant",
        content="T. one; two why",
        id="app:1",
        at="2026-11-07T10:00:00Z",
        source="game",
        provider="chatgpt",
        model="gpt-test",
        answer=answer,
    )
    append_messages(path, [original])
    assert read_messages(path) == [original]
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert line["v"] == 1 and line["answer"]["steps"] == ["one", "two"]


def test_format_has_exactly_the_documented_keys() -> None:
    data = message_to_dict(message("hello", message_id="x"))
    assert set(data) == {
        "v", "id", "at", "role", "content", "source", "provider", "model", "answer",
    }  # fmt: skip
    assert data["provider"] is None and data["answer"] is None


def test_old_lines_read_with_safe_defaults(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text(
        '{"role": "user", "content": "old q"}\n{"role": "assistant", "content": "old a"}\n',
        encoding="utf-8",
    )
    found = read_messages(path)
    assert [(m.role, m.content, m.source, m.provider, m.answer) for m in found] == [
        ("user", "old q", "app", None, None),
        ("assistant", "old a", "app", None, None),
    ]
    assert len({m.id for m in found}) == 2  # each old line still gets its own id
    assert read_messages(path) == found  # and the ids do not change between reads


def test_old_lines_get_their_ids_saved_on_the_next_append(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text('{"role": "user", "content": "old"}\n', encoding="utf-8")
    before = read_messages(path)[0].id
    append_messages(path, [message("new")])
    assert read_messages(path)[0].id == before
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])["v"] == 1


def test_unknown_fields_and_values_are_ignored() -> None:
    parsed = message_from_dict(
        {"v": 7, "role": "user", "content": "hi", "future": [1], "source": "mars", "provider": 5}
    )
    assert parsed is not None
    assert parsed.source == "app" and parsed.provider is None


def test_damaged_lines_are_skipped_and_cleaned_on_append(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    good = json.dumps(message_to_dict(message("kept", message_id="k")))
    path.write_bytes(
        good.encode() + b'\nnot json\n{"role":"boss","content":"x"}\n[1]\n\xff\xfe\n'
        b'{"role":"user","content":5}\n{"role":"user","content":"  "}\n'
    )
    assert [m.content for m in read_messages(path)] == ["kept"]
    append_messages(path, [message("new")])
    assert [m.content for m in read_messages(path)] == ["kept", "new"]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_missing_file_gives_no_messages(tmp_path: Path) -> None:
    assert read_messages(tmp_path / "nope.jsonl") == []


def test_limit_gives_the_newest_oldest_first(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    append_messages(path, [message(f"m{n}", at=f"2026-11-07T10:00:{n:02d}Z") for n in range(5)])
    assert [m.content for m in read_messages(path, limit=2)] == ["m3", "m4"]
    assert read_messages(path, limit=0) == []


def test_same_id_is_never_stored_twice(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    append_messages(path, [message("a", message_id="same")])
    append_messages(path, [message("a again", message_id="same"), message("b", message_id="other")])
    assert [m.content for m in read_messages(path)] == ["a", "b"]


def test_messages_are_ordered_by_time_even_when_appended_late(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    append_messages(path, [message("late", at="2026-11-07T12:00:00Z")])
    append_messages(path, [message("early", at="2026-11-07T11:00:00.500Z")])
    append_messages(path, [message("middle", at="2026-11-07T11:30:00Z")])
    assert [m.content for m in read_messages(path)] == ["early", "middle", "late"]


def test_only_the_newest_messages_are_kept(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    count = MAX_STORED_MESSAGES + 10
    append_messages(
        path, [message(f"m{n}", at=f"2026-11-07T10:00:00.{n:06d}Z") for n in range(count)]
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == MAX_STORED_MESSAGES
    assert json.loads(lines[-1])["content"] == f"m{count - 1}"


def test_long_messages_are_cut(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    append_messages(path, [message("w" * (MAX_MESSAGE_CHARS * 3))])
    assert len(read_messages(path)[0].content) == MAX_MESSAGE_CHARS


def test_empty_messages_are_not_stored(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    append_messages(path, [message("   ")])
    assert not path.exists()


def test_two_writers_at_once_lose_nothing(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"

    def write(prefix: str) -> None:
        for n in range(15):
            append_messages(path, [message(f"{prefix}{n}")])

    threads = [threading.Thread(target=write, args=(p,)) for p in "ab"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(read_messages(path)) == 30
    assert not list(tmp_path.glob("*.lock"))


def test_now_iso_is_utc_and_parseable() -> None:
    stamp = now_iso(1_794_000_000.0)
    assert stamp.endswith("Z") and stamp.startswith("2026-")


def test_sources_and_lookups_round_trip_inside_the_answer(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    wiki = "https://warcraft.wiki.gg/wiki/Abigail_Shiel"
    looked = 'Read the Warcraft Wiki page "Abigail Shiel"'
    answer = ChatAnswer(
        "T",
        ("one",),
        "why",
        (),
        sources=(SourceLink("Abigail Shiel", wiki),),
        lookups=(Lookup("wiki", looked),),
    )
    original = ChatMessage(
        "assistant", "T. one why", "app:1", "2026-11-07T10:00:00Z", answer=answer
    )
    append_messages(path, [original])
    assert read_messages(path) == [original]
    stored = json.loads(path.read_text(encoding="utf-8").splitlines()[0])["answer"]
    assert stored["sources"] == [{"title": "Abigail Shiel", "url": wiki}]
    assert stored["lookups"] == [{"kind": "wiki", "text": looked}]


def test_an_answer_without_sources_keeps_the_old_shape() -> None:
    answer = ChatAnswer("T", (), "t", ())
    data = message_to_dict(ChatMessage("assistant", "x", "a:1", answer=answer))
    assert data["answer"] == {"title": "T", "steps": [], "text": "t", "warnings": []}


def test_stored_sources_with_unsafe_links_are_dropped_on_reading(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    line = {
        "role": "assistant",
        "content": "hi",
        "answer": {
            "title": "T",
            "steps": [],
            "text": "t",
            "warnings": [],
            "sources": [
                {"title": "bad", "url": "javascript:alert(1)"},
                {"title": "file", "url": "file:///etc/passwd"},
                {"url": "https://ok.example/"},
                "nonsense",
                {"title": 5, "url": "https://ok2.example/"},
            ],
            "lookups": [{"kind": "web", "text": "Searched"}, {"kind": 1}, "x"],
        },
    }
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")
    answer = read_messages(path)[0].answer
    assert answer is not None
    assert [(s.title, s.url) for s in answer.sources] == [
        ("", "https://ok.example/"),
        ("", "https://ok2.example/"),
    ]
    assert answer.lookups == (Lookup("web", "Searched"),)
