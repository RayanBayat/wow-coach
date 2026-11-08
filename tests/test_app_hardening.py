"""Fixes from the security review: private launcher file, plan protection, outside-write race."""

import os
import stat
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from test_app_support import (
    KEY,
    FakeCoach,
    make_answer,
    make_rig,
    write_advice_file,
    write_save,
)

from wow_coach.app.launcher import open_start_page, write_launcher
from wow_coach.app.watcher import Watcher
from wow_coach.engine.contract import CoachReply

START_URL = "http://127.0.0.1:5555/#secret-token"


# ---- the private launcher file ---------------------------------------------------------------


def test_the_launcher_file_and_folder_are_private(tmp_path: Path) -> None:
    page = write_launcher(START_URL, {"XDG_RUNTIME_DIR": str(tmp_path)})
    try:
        assert page.parent.parent == tmp_path
        if os.name != "nt":  # Windows has no such modes; its user folders are private anyway
            assert stat.S_IMODE(page.stat().st_mode) == 0o600
            assert stat.S_IMODE(page.parent.stat().st_mode) == 0o700
        text = page.read_text("utf-8")
        assert 'http-equiv="refresh"' in text and START_URL in text
    finally:
        page.unlink()


def _path_of(uri: str) -> Path:
    """The file a file:// address points to (on Windows it looks like file:///C:/...)."""
    return Path(url2pathname(urlsplit(uri).path))


def test_the_browser_gets_the_file_not_the_token() -> None:
    opened: list[str] = []
    clean_up = open_start_page(START_URL, opened.append, keep_seconds=60)
    assert len(opened) == 1
    assert opened[0].startswith("file://") and "secret-token" not in opened[0]
    page = _path_of(opened[0])
    assert page.is_file()
    clean_up()
    assert not page.exists() and not page.parent.exists()


def test_the_launcher_file_deletes_itself() -> None:
    opened: list[str] = []
    open_start_page(START_URL, opened.append, keep_seconds=0.05)
    page = _path_of(opened[0])
    for _ in range(100):
        if not page.exists():
            break
        import time  # noqa: PLC0415

        time.sleep(0.05)
    assert not page.exists()


# ---- the plan is never burned twice ----------------------------------------------------------


class NoIdCoach(FakeCoach):
    """An engine whose replies forget the question id (the worst case)."""

    def answer_open_questions(self, *, character: str | None = None) -> list[CoachReply]:
        self.answered_calls.append(character)
        answer = make_answer("No id", 7_000, None)
        return [CoachReply(KEY, answer, False, "The game file could not be written.")]


def test_a_question_is_not_answered_again_even_if_the_reply_has_no_id(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    rig.core.coach = NoIdCoach(rig.wow_dir)
    write_save(rig.wow_dir, ("1-1", "How?"), mtime=2_000)
    assert rig.core.start_answer_open(None) == "started"
    for _ in range(100):
        if not rig.core.ai_lock.locked():
            break
        import time  # noqa: PLC0415

        time.sleep(0.05)
    assert rig.core.start_answer_open(None) == "none"
    assert len(rig.core.coach.answered_calls) == 1  # type: ignore[attr-defined]


def test_the_watcher_answers_a_save_only_once(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    watcher = Watcher(rig.core, rig.wow_dir, clock=lambda: 2_100)
    write_save(rig.wow_dir, ("1-1", "How?"), mtime=2_000)
    watcher.check_once()
    watcher.check_once()
    watcher.check_once()
    assert rig.coach.answered_calls == [KEY]


def test_a_locked_keychain_means_not_signed_in_for_the_watcher(tmp_path: Path) -> None:
    from wow_coach.ai.base import AIError  # noqa: PLC0415

    class Locked:
        @property
        def is_signed_in(self) -> bool:
            raise AIError("locked")

    rig = make_rig(tmp_path)
    rig.core.signin = Locked()  # type: ignore[assignment]
    watcher = Watcher(rig.core, rig.wow_dir, clock=lambda: 2_100)
    write_save(rig.wow_dir, ("1-1", "How?"), mtime=2_000)
    watcher.check_once()
    assert rig.coach.answered_calls == []


def test_an_outside_answer_written_during_our_own_call_is_still_announced(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    watcher = Watcher(rig.core, rig.wow_dir)
    mailbox = rig.core.bus.subscribe()

    class Both(FakeCoach):
        def ask(self, question: str, *, character: str | None = None) -> CoachReply:
            del question, character
            own = make_answer("Ours", 9_000)
            outside = make_answer("From Claude Code", 9_001)
            path = write_advice_file(self.wow_dir, [own, outside], mtime=9_500)
            del path
            return CoachReply(KEY, own, True, "ok")

    rig.core.coach = Both(rig.wow_dir)
    assert rig.core.start_ask("hi", None)
    for _ in range(100):
        if not rig.core.ai_lock.locked():
            break
        import time  # noqa: PLC0415

        time.sleep(0.05)
    watcher.check_once()
    titles = []
    while not mailbox.empty():
        event = mailbox.get_nowait()
        if event is not None and event.kind == "answer":
            titles.append(event.data["answer"]["title"])  # type: ignore[index]
    assert titles == ["Ours", "From Claude Code"]  # ours once (the reply), theirs once


# ---- outside writes during an AI call ----------------------------------------------------------


def test_an_outside_write_during_a_call_is_announced_after_it(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    watcher = Watcher(rig.core, rig.wow_dir)
    mailbox = rig.core.bus.subscribe()
    assert rig.core.ai_lock.acquire(blocking=False)  # pretend the coach is busy
    write_advice_file(rig.wow_dir, [make_answer("From outside", 50)], mtime=4_000)
    watcher.check_once()
    assert mailbox.empty()  # skipped while busy
    rig.core.ai_lock.release()
    watcher.check_once()
    event = mailbox.get_nowait()
    assert event is not None and event.kind == "answer"
