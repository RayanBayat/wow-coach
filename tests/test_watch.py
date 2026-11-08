"""Tests for the /coach save watcher (fake clock and sleep, no real waiting)."""

import io
import os
from datetime import datetime
from pathlib import Path

import pytest

from wow_coach.watch import POLL_SECONDS, watch

START = datetime(2026, 11, 7, 12, 0, 0)


def snapshot_file(name: str, level: int, saved_at: int, reason: str = "coach") -> str:
    return (
        'HeroBridgeDB = {\n["formatVersion"] = 1,\n["characters"] = {\n'
        f'["{name}-Testrealm"] = {{\n["snapshot"] = {{\n["name"] = "{name}",\n'
        f'["level"] = {level},\n["savedAt"] = {saved_at},\n["reason"] = "{reason}",\n'
        "},\n},\n},\n}\n"
    )


def account_file(wow_dir: Path, account: str = "ACC") -> Path:
    folder = wow_dir / "WTF" / "Account" / account / "SavedVariables"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "HeroBridge.lua"


class Script:
    """A fake sleep. Each 2-second poll runs one scripted action; when none are left it
    stops the watcher like Ctrl+C. The 1-second settle wait never uses up an action."""

    def __init__(self, *actions: object) -> None:
        self.actions = list(actions)
        self.sleeps: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if seconds != POLL_SECONDS:
            return
        if not self.actions:
            raise KeyboardInterrupt
        action = self.actions.pop(0)
        if callable(action):
            action()


def run_watch(wow_dir: Path, sleep: Script, status: io.StringIO | None = None) -> list[str]:
    """Run the watcher and return the save lines it printed (the status line goes elsewhere)."""
    out = io.StringIO()
    with pytest.raises(KeyboardInterrupt):
        watch(wow_dir, out=out, status=status or io.StringIO(), sleep=sleep, clock=lambda: START)
    return out.getvalue().splitlines()


def write(path: Path, text: str, mtime: int) -> None:
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_the_start_line_goes_to_the_status_stream_only(tmp_path: Path) -> None:
    # Under a monitor every line on standard output is an event for the coach, so the
    # start line (which is not a save) must not be one.
    status = io.StringIO()
    lines = run_watch(tmp_path, Script(), status)
    assert lines == []
    assert status.getvalue() == "watching for /coach saves (started 12:00:00)\n"


def test_reports_a_save_with_name_level_and_reason(tmp_path: Path) -> None:
    file = account_file(tmp_path)
    write(file, snapshot_file("Testchar", 7, 100), 1000)
    script = Script(lambda: write(file, snapshot_file("Testchar", 8, 200, "logout"), 2000))
    lines = run_watch(tmp_path, script)
    assert lines == ["HeroBridge saved at 12:00:00: Testchar level 8 (reason: logout)"]


def test_an_unloaded_save_is_called_almost_empty(tmp_path: Path) -> None:
    file = account_file(tmp_path)
    write(file, snapshot_file("Testchar", 7, 100), 1000)
    unloaded = snapshot_file("Testchar", 6, 200, "logout").replace(
        '["reason"]', '["xpMax"] = 0,\n["reason"]'
    )
    lines = run_watch(tmp_path, Script(lambda: write(file, unloaded, 2000)))
    assert lines[0].endswith("Testchar level 6 (reason: logout; almost empty, type /coach)")


def test_a_question_from_the_coach_panel_is_counted(tmp_path: Path) -> None:
    file = account_file(tmp_path)
    write(file, snapshot_file("Testchar", 7, 100), 1000)
    asked = snapshot_file("Testchar", 7, 200, "ask").replace(
        '["snapshot"] = {',
        '["questions"] = {\n{\n["id"] = "200-1",\n["text"] = "Where?",\n'
        '["askedAt"] = 200,\n},\n},\n["snapshot"] = {',
    )
    lines = run_watch(tmp_path, Script(lambda: write(file, asked, 2000)))
    assert lines[0].endswith("Testchar level 7 (reason: ask; 1 open question)")


def test_polls_every_two_seconds_and_waits_one_second_after_a_change(tmp_path: Path) -> None:
    file = account_file(tmp_path)
    write(file, snapshot_file("Testchar", 7, 100), 1000)
    script = Script(lambda: write(file, snapshot_file("Testchar", 8, 200), 2000))
    run_watch(tmp_path, script)
    assert script.sleeps == [2, 1, 2]


def test_no_change_prints_nothing_more(tmp_path: Path) -> None:
    file = account_file(tmp_path)
    write(file, snapshot_file("Testchar", 7, 100), 1000)
    assert run_watch(tmp_path, Script(None, None)) == []


def test_first_save_ever_is_reported(tmp_path: Path) -> None:
    (tmp_path / "WTF").mkdir()
    script = Script(lambda: write(account_file(tmp_path), snapshot_file("Testchar", 2, 5), 10))
    assert "Testchar level 2" in run_watch(tmp_path, script)[0]


def test_newest_snapshot_by_saved_at_is_described(tmp_path: Path) -> None:
    file = account_file(tmp_path)
    both = snapshot_file("Old", 20, 100).replace(
        "},\n},\n},\n}\n",
        '},\n},\n["New-Testrealm"] = {\n["snapshot"] = {\n["name"] = "New",\n["level"] = 3,\n'
        '["savedAt"] = 900,\n["reason"] = "coach",\n},\n},\n},\n}\n',
    )
    write(file, snapshot_file("Old", 20, 100), 1000)
    script = Script(lambda: write(file, both, 2000))
    assert "New level 3" in run_watch(tmp_path, script)[0]


def test_unreadable_file_is_reported_and_watching_continues(tmp_path: Path) -> None:
    file = account_file(tmp_path)
    write(file, snapshot_file("Testchar", 7, 100), 1000)
    script = Script(
        lambda: write(file, "HeroBridgeDB = {", 2000),
        None,
        lambda: write(file, snapshot_file("Testchar", 9, 300), 3000),
    )
    lines = run_watch(tmp_path, script)
    assert lines[0].startswith("HeroBridge saved at 12:00:00: (could not read the snapshot: ")
    assert lines[0].endswith(")")
    assert "Testchar level 9" in lines[1]


def test_every_line_is_flushed() -> None:
    class Recorder(io.StringIO):
        flushes = 0

        def flush(self) -> None:
            self.flushes += 1
            super().flush()

    status = Recorder()
    folder = Path(__file__).parent
    with pytest.raises(KeyboardInterrupt):
        watch(folder, out=io.StringIO(), status=status, sleep=Script(), clock=lambda: START)
    assert status.flushes >= 1
