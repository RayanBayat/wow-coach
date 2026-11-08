"""The core and the watcher import the Claude coach's chats in the background."""

import json
import time
from pathlib import Path

from test_app_support import make_rig

from wow_coach.app.watcher import Watcher


def contents(state: dict[str, object]) -> list[object]:
    """The ``content`` of every message in a state's conversation."""
    conversation = state["conversation"]
    assert isinstance(conversation, list)
    return [item["content"] for item in conversation]


def write_claude_session(projects: Path) -> None:
    """A tiny made-up coach session with one question and one reply."""
    folder = projects / "-project"
    folder.mkdir(parents=True)
    lines = [
        {"type": "agent-setting", "agentSetting": "wow-coach"},
        {
            "type": "user",
            "uuid": "u1",
            "timestamp": "2026-11-07T10:00:00.000Z",
            "message": {"role": "user", "content": "Where next?"},
        },
        {
            "type": "assistant",
            "uuid": "a1",
            "timestamp": "2026-11-07T10:00:05.000Z",
            "message": {"id": "m1", "content": [{"type": "text", "text": "To the mine."}]},
        },
        {
            "type": "system",
            "subtype": "turn_duration",
            "uuid": "s1",
            "timestamp": "2026-11-07T10:00:06.000Z",
        },
    ]
    text = "\n".join(json.dumps(item) for item in lines) + "\n"
    (folder / "session.jsonl").write_text(text, encoding="utf-8")


def test_the_core_imports_claude_chats_and_tells_the_window(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    write_claude_session(projects)
    rig = make_rig(tmp_path, claude_projects_dir=projects)
    mailbox = rig.core.bus.subscribe()
    assert rig.core.import_claude_chats() == 2
    assert rig.core.import_claude_chats() == 0  # nothing new the second time
    assert contents(rig.core.state(None)) == ["Where next?", "To the mine."]
    event = mailbox.get_nowait()
    assert event is not None and event.kind == "history"


def test_turning_the_setting_off_stops_the_import(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    write_claude_session(projects)
    rig = make_rig(tmp_path, claude_projects_dir=projects)
    rig.core.change_settings({"use_claude_chats": False})
    assert rig.core.import_claude_chats() == 0
    rig.core.change_settings({"use_claude_chats": True})
    assert rig.core.import_claude_chats() == 2


def test_without_a_projects_folder_nothing_is_imported(tmp_path: Path) -> None:
    assert make_rig(tmp_path).core.import_claude_chats() == 0


def test_the_watcher_imports_when_it_starts(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    write_claude_session(projects)
    rig = make_rig(tmp_path, claude_projects_dir=projects)
    watcher = Watcher(rig.core, rig.wow_dir, poll_seconds=0.02, settle_seconds=0)
    watcher.start()
    try:
        deadline = time.monotonic() + 5
        while not contents(rig.core.state(None)) and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        watcher.stop()
    assert contents(rig.core.state(None)) == ["Where next?", "To the mine."]


def test_check_imports_picks_up_a_later_session(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    rig = make_rig(tmp_path, claude_projects_dir=projects)
    watcher = Watcher(rig.core, rig.wow_dir)
    watcher.check_imports()
    assert contents(rig.core.state(None)) == []
    write_claude_session(projects)
    watcher.check_imports()
    assert contents(rig.core.state(None)) == ["Where next?", "To the mine."]
