"""The save watcher: new saves, open questions, alerts and outside changes to Advice.lua."""

from pathlib import Path

from test_app_support import (
    KEY,
    Rig,
    make_answer,
    make_rig,
    write_advice_file,
    write_save,
)

from wow_coach.ai.base import PlanLimitReached
from wow_coach.app.events import Event, Mailbox
from wow_coach.app.watcher import Watcher


def drain(mailbox: Mailbox) -> list[Event]:
    events: list[Event] = []
    while not mailbox.empty():
        event = mailbox.get_nowait()
        if event is not None:
            events.append(event)
    return events


def kinds(events: list[Event]) -> list[str]:
    return [event.kind for event in events]


def start(tmp_path: Path, **settings: object) -> tuple[Rig, Watcher, Mailbox]:
    rig = make_rig(tmp_path)
    if settings:
        rig.core.change_settings(dict(settings))
    watcher = Watcher(rig.core, rig.wow_dir)
    return rig, watcher, rig.core.bus.subscribe()


def test_nothing_happens_without_a_change(tmp_path: Path) -> None:
    rig, watcher, mailbox = start(tmp_path)
    watcher.check_once()
    assert drain(mailbox) == [] and rig.coach.answered_calls == []


def test_a_new_save_with_a_question_is_answered_once(tmp_path: Path) -> None:
    rig, watcher, mailbox = start(tmp_path, notify=True)
    write_save(rig.wow_dir, ("1-1", "How?"), mtime=2_000)
    watcher.check_once()
    events = drain(mailbox)
    assert kinds(events) == ["save", "question", "answer"]
    assert rig.coach.answered_calls == [KEY]
    assert rig.alerts.notified == [("Your coach answered", "Open answer")]
    # The same question, even in a later save, is never answered a second time.
    write_save(rig.wow_dir, ("1-1", "How?"), mtime=3_000)
    watcher.check_once()
    assert rig.coach.answered_calls == [KEY]
    assert "answer" not in kinds(drain(mailbox))


def test_the_watchers_own_answer_is_not_an_outside_change(tmp_path: Path) -> None:
    rig, watcher, mailbox = start(tmp_path)
    write_save(rig.wow_dir, ("1-1", "How?"), mtime=2_000)
    watcher.check_once()
    drain(mailbox)
    rig.alerts.notified.clear()
    watcher.check_once()
    assert drain(mailbox) == [] and rig.alerts.notified == []


def test_notifications_follow_the_settings(tmp_path: Path) -> None:
    rig, watcher, _ = start(tmp_path, notify=False)
    write_save(rig.wow_dir, ("1-1", "How?"), mtime=2_000)
    watcher.check_once()
    assert rig.alerts.notified == []


def test_questions_are_left_alone_when_the_setting_is_off(tmp_path: Path) -> None:
    rig, watcher, mailbox = start(tmp_path, answer_questions_from_game=False)
    write_save(rig.wow_dir, ("1-1", "How?"), mtime=2_000)
    watcher.check_once()
    assert kinds(drain(mailbox)) == ["save", "question"]
    assert rig.coach.answered_calls == []


def test_questions_are_left_alone_when_signed_out(tmp_path: Path) -> None:
    rig, watcher, mailbox = start(tmp_path)
    rig.signin.signed_in = False
    write_save(rig.wow_dir, ("1-1", "How?"), mtime=2_000)
    watcher.check_once()
    assert kinds(drain(mailbox)) == ["save", "question"]
    assert rig.coach.answered_calls == []


def test_a_save_without_questions_only_says_saved(tmp_path: Path) -> None:
    rig, watcher, mailbox = start(tmp_path)
    write_save(rig.wow_dir, mtime=2_000)
    watcher.check_once()
    assert kinds(drain(mailbox)) == ["save"] and rig.coach.answered_calls == []


def test_an_ai_error_is_reported_and_the_question_is_tried_again_next_save(tmp_path: Path) -> None:
    rig, watcher, mailbox = start(tmp_path)
    rig.coach.error = PlanLimitReached("Your plan is used up.")
    write_save(rig.wow_dir, ("1-1", "How?"), mtime=2_000)
    watcher.check_once()
    errors = [e for e in drain(mailbox) if e.kind == "error"]
    assert [e.data["message"] for e in errors] == ["Your plan is used up."]
    rig.coach.error = None
    write_save(rig.wow_dir, ("1-1", "How?"), mtime=3_000)
    watcher.check_once()
    assert rig.coach.answered_calls == [KEY, KEY]
    assert "answer" in kinds(drain(mailbox))


def test_an_outside_change_notifies_without_the_ai(tmp_path: Path) -> None:
    rig, watcher, mailbox = start(tmp_path, notify=True)
    write_advice_file(rig.wow_dir, [make_answer("From Claude Code", 50)], mtime=4_000)
    watcher.check_once()
    events = drain(mailbox)
    assert kinds(events) == ["answer"]
    assert events[0].data["answer"]["title"] == "From Claude Code"  # type: ignore[index]
    assert rig.alerts.notified == [("Your coach answered", "From Claude Code")]
    assert rig.coach.answered_calls == [] and rig.coach.asked == []
    watcher.check_once()  # no second alert for the same change
    assert drain(mailbox) == []


def test_an_outside_change_with_notify_off_is_silent_but_still_shown(tmp_path: Path) -> None:
    rig, watcher, mailbox = start(tmp_path, notify=False)
    write_advice_file(rig.wow_dir, [make_answer("Hello", 50)], mtime=4_000)
    watcher.check_once()
    assert kinds(drain(mailbox)) == ["answer"] and rig.alerts.notified == []


def test_the_background_thread_starts_and_stops(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    watcher = Watcher(rig.core, rig.wow_dir, poll_seconds=0.05, settle_seconds=0)
    mailbox = rig.core.bus.subscribe()
    watcher.start()
    try:
        write_save(rig.wow_dir, mtime=9_000)
        deadline_event = None
        for _ in range(100):
            event = mailbox.get(timeout=5)
            if event is not None and event.kind == "save":
                deadline_event = event
                break
        assert deadline_event is not None
    finally:
        watcher.stop()
