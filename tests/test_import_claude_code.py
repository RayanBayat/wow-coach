"""Tests for the Claude Code chat importer, using made-up transcripts (never real chats)."""

import json
import os
from pathlib import Path

from wow_coach.engine.conversation import ChatMessage, conversation_file, read_messages
from wow_coach.importers.claude_code import (
    IMPORT_STATE_FILE,
    claude_projects_dir,
    import_claude_chats,
)
from wow_coach.savedvars import Character

ALPHA = "Alpha-Realm"
BETA = "Beta-Realm"


def character(key: str, saved_at: int) -> Character:
    return Character(key=key, snapshot={"savedAt": saved_at, "name": key.split("-")[0]}, history=[])


CHARACTERS = {ALPHA: character(ALPHA, 100), BETA: character(BETA, 200)}  # Beta is the newest


# ---- building fake transcripts ----------------------------------------------------------


def line(**fields: object) -> str:
    return json.dumps(fields)


def setting(agent: str = "wow-coach") -> str:
    return line(type="agent-setting", agentSetting=agent, sessionId="s1")


def user(text: object, uuid: str, at: str = "2026-11-07T10:00:00.000Z", **extra: object) -> str:
    return line(
        type="user",
        uuid=uuid,
        timestamp=at,
        isSidechain=False,
        message={"role": "user", "content": text},
        **extra,
    )


def assistant(
    blocks: list[dict[str, object]],
    uuid: str,
    message_id: str,
    at: str = "2026-11-07T10:00:05.000Z",
) -> str:
    return line(
        type="assistant",
        uuid=uuid,
        timestamp=at,
        isSidechain=False,
        message={"id": message_id, "model": "claude-test", "role": "assistant", "content": blocks},
    )


def text(value: str) -> dict[str, object]:
    return {"type": "text", "text": value}


def tool_call(
    character_name: str | None, name: str = "mcp__wow-coach__character_status"
) -> dict[str, object]:
    arguments = {} if character_name is None else {"character": character_name}
    return {"type": "tool_use", "name": name, "input": arguments, "id": "t1"}


class Setup:
    """A fake ~/.claude/projects folder and data folder."""

    def __init__(self, tmp_path: Path) -> None:
        self.projects = tmp_path / "claude" / "projects"
        self.data = tmp_path / "data"
        self.project = self.projects / "-home-someone"
        self.project.mkdir(parents=True)

    def transcript(self, name: str, lines: list[str], *, old: bool = True) -> Path:
        path = self.project / f"{name}.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if old:  # a quiet file: its last reply is certainly finished
            os.utime(path, (1_000, 1_000))
        return path

    def run(self, characters: dict[str, Character] | None = None, **options: float) -> int:
        result = import_claude_chats(
            projects_dir=self.projects,
            data_dir=self.data,
            characters=CHARACTERS if characters is None else characters,
            **options,
        )
        return result.imported

    def chat(self, key: str) -> list[ChatMessage]:
        return read_messages(conversation_file(self.data, key))


SESSION = [
    setting(),
    user("Where do I go next?", "u1"),
    assistant([{"type": "thinking", "thinking": "hmm"}], "a0", "m1"),
    assistant([tool_call("Alpha")], "a1", "m1"),
    assistant([text("Go to the mine.")], "a2", "m2", "2026-11-07T10:00:06.000Z"),
    assistant([text("Then talk to the foreman.")], "a3", "m2", "2026-11-07T10:00:07.000Z"),
    user("Thanks!", "u2", "2026-11-07T10:01:00.000Z"),
    assistant([text("Good luck.")], "a4", "m3", "2026-11-07T10:01:05.000Z"),
]


# ---- what is imported ---------------------------------------------------------------------


def test_a_coach_session_is_imported_with_everything_filled_in(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    setup.transcript("one", SESSION)
    assert setup.run() == 4
    chat = setup.chat(ALPHA)
    assert [(m.role, m.content) for m in chat] == [
        ("user", "Where do I go next?"),
        ("assistant", "Go to the mine.\n\nThen talk to the foreman."),
        ("user", "Thanks!"),
        ("assistant", "Good luck."),
    ]
    first, reply = chat[0], chat[1]
    assert first.id == "claude-code:u1" and reply.id == "claude-code:a2"
    assert (first.source, first.provider) == ("claude-code", None)
    assert (reply.source, reply.provider, reply.model) == (
        "claude-code",
        "claude-code",
        "claude-test",
    )
    assert first.at == "2026-11-07T10:00:00.000Z" and reply.answer is None


def test_other_sessions_are_not_imported(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    setup.transcript("coding", [setting("other-agent"), user("fix my bug", "u1")])
    setup.transcript("plain", [user("hello", "u1")])
    assert setup.run() == 0
    assert setup.chat(ALPHA) == [] and setup.chat(BETA) == []


def test_only_what_people_said_is_imported(tmp_path: Path) -> None:
    lines = [
        setting(),
        user("<command-name>/clear</command-name>", "x1"),
        user("<local-command-stdout>ok</local-command-stdout>", "x2"),
        user("<system-reminder>be nice</system-reminder>", "x3"),
        user("<task-notification>done</task-notification>", "x4"),
        user("[Request interrupted by user]", "x5"),
        user("meta text", "x6", isMeta=True),
        line(type="user", uuid="x7", timestamp="2026-11-07T10:00:00Z", isSidechain=True,
             message={"role": "user", "content": "from a sub agent"}),
        user([{"type": "tool_result", "content": "secret tool output"}], "x8"),
        user("typed by a peer", "x9", origin={"kind": "peer"}),
        user([text("real question"), text("in two blocks")], "u1", origin={"kind": "human"}),
        assistant([tool_call(None)], "a1", "m1"),
        assistant([{"type": "thinking", "thinking": "private thoughts"}], "a2", "m2"),
        line(type="attachment", uuid="z1", timestamp="2026-11-07T10:00:00Z"),
        line(type="assistant", uuid="a3", timestamp="2026-11-07T10:00:00Z", isSidechain=True,
             message={"id": "m9", "content": [text("side chain reply")]}),
        assistant([text("the answer")], "a4", "m3"),
    ]  # fmt: skip
    setup = Setup(tmp_path)
    setup.transcript("one", lines)
    setup.run()
    assert [m.content for m in setup.chat(BETA)] == ["real question\n\nin two blocks", "the answer"]


def test_unexpected_shapes_never_crash(tmp_path: Path) -> None:
    lines = [
        setting(),
        "not json at all",
        "[1, 2, 3]",
        "null",
        line(type="user"),
        line(type="user", message="a string"),
        line(type="user", message={"content": 5}),
        line(type="user", message={"content": [None, 3, "x", {"type": "text", "text": 5}]}),
        line(type="assistant", message={"id": 7, "content": "text"}),
        line(type="assistant", message={"id": "m", "content": [text("no uuid or time")]}),
        line(type="assistant", uuid="a", timestamp="x", message={"id": "m2", "content": [text("b")]}),  # noqa: E501
        user("fine", "u1"),
    ]  # fmt: skip
    setup = Setup(tmp_path)
    setup.transcript("one", lines)
    setup.run()
    assert "fine" in [m.content for m in setup.chat(BETA)]


# ---- which character -----------------------------------------------------------------------


def test_the_character_comes_from_the_coach_tool_calls(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    setup.transcript("one", SESSION)  # asks about "Alpha"
    setup.run()
    assert len(setup.chat(ALPHA)) == 4 and setup.chat(BETA) == []


def test_without_a_tool_call_the_newest_saved_character_is_used(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    setup.transcript("one", [setting(), user("hi", "u1")])
    setup.run()
    assert len(setup.chat(BETA)) == 1 and setup.chat(ALPHA) == []


def test_an_unknown_character_falls_back_to_the_newest(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    setup.transcript(
        "one", [setting(), assistant([tool_call("Nobody")], "a1", "m1"), user("hi", "u1")]
    )
    setup.run()
    assert len(setup.chat(BETA)) == 1


def test_other_tools_do_not_pick_a_character(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    setup.transcript(
        "one",
        [
            setting(),
            assistant([tool_call("Alpha", name="mcp__other__thing")], "a1", "m1"),
            user("hi", "u1"),
        ],
    )
    setup.run()
    assert len(setup.chat(BETA)) == 1


def test_nothing_is_imported_or_remembered_without_saved_characters(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    setup.transcript("one", SESSION)
    assert setup.run(characters={}) == 0
    assert setup.run() == 4  # once a character exists, the chats are imported


# ---- incremental and idempotent -------------------------------------------------------------


def test_a_second_run_imports_nothing_and_new_lines_are_picked_up(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    path = setup.transcript("one", SESSION)
    assert setup.run() == 4
    assert setup.run() == 0
    with path.open("a", encoding="utf-8") as file:
        file.write(user("one more thing", "u3", "2026-11-07T10:02:00.000Z") + "\n")
    assert setup.run() == 1
    assert [m.content for m in setup.chat(ALPHA)][-1] == "one more thing"
    assert (setup.data / IMPORT_STATE_FILE).is_file()


def test_losing_the_import_state_cannot_create_duplicates(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    setup.transcript("one", SESSION)
    setup.run()
    (setup.data / IMPORT_STATE_FILE).unlink()
    assert setup.run() == 0
    assert len(setup.chat(ALPHA)) == 4


def test_a_half_written_last_line_waits_for_its_end(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    path = setup.transcript("one", [setting(), user("first", "u1")])
    with path.open("a", encoding="utf-8") as file:
        file.write(user("second", "u2")[:30])  # the program is still writing this line
    assert setup.run() == 1
    with path.open("a", encoding="utf-8") as file:
        file.write(user("second", "u2")[30:] + "\n")
    assert setup.run() == 1
    assert [m.content for m in setup.chat(BETA)] == ["first", "second"]


def test_a_reply_still_being_written_is_imported_whole_later(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    path = setup.transcript(
        "one", [setting(), user("q", "u1"), assistant([text("part one")], "a1", "m1")], old=False
    )
    assert setup.run(settle_seconds=60) == 1  # the question; the fresh reply may still grow
    with path.open("a", encoding="utf-8") as file:
        file.write(assistant([text("part two")], "a2", "m1") + "\n")
    os.utime(path, (1_000, 1_000))
    assert setup.run(settle_seconds=60) == 1
    assert [m.content for m in setup.chat(BETA)][-1] == "part one\n\npart two"


def test_a_finished_turn_is_imported_at_once_even_in_a_fresh_file(tmp_path: Path) -> None:
    end_of_turn = line(
        type="system", subtype="turn_duration", uuid="z", timestamp="2026-11-07T10:00:09Z"
    )
    setup = Setup(tmp_path)
    setup.transcript(
        "one",
        [setting(), user("q", "u1"), assistant([text("done")], "a1", "m1"), end_of_turn],
        old=False,
    )
    assert setup.run(settle_seconds=60) == 2


def test_a_shrunk_file_is_read_again_from_the_start(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    path = setup.transcript("one", SESSION)
    setup.run()
    path.write_text(setting() + "\n" + user("brand new", "n1") + "\n", encoding="utf-8")
    os.utime(path, (1_000, 1_000))
    assert setup.run() == 1


def test_a_damaged_state_file_is_ignored(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    setup.transcript("one", SESSION)
    setup.data.mkdir()
    (setup.data / IMPORT_STATE_FILE).write_text("{{{ not json", encoding="utf-8")
    assert setup.run() == 4


def test_a_missing_projects_folder_is_fine(tmp_path: Path) -> None:
    result = import_claude_chats(
        projects_dir=tmp_path / "nope", data_dir=tmp_path / "data", characters=CHARACTERS
    )
    assert result.imported == 0


# ---- where the transcripts are ----------------------------------------------------------------


def test_the_projects_folder_follows_claude_config_dir(tmp_path: Path) -> None:
    assert (
        claude_projects_dir({"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")})
        == tmp_path / "cfg" / "projects"
    )
    assert claude_projects_dir({}).parts[-2:] == (".claude", "projects")
