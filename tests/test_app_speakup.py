"""'When should the coach speak up?': saves and the timer turn into notes or advice."""

import json
from pathlib import Path

from test_app_support import Client, Rig, make_rig, write_save

from wow_coach.ai.base import FakeProvider, PlanLimitReached, Provider
from wow_coach.app.events import Event, Mailbox
from wow_coach.app.server import CoachServer
from wow_coach.app.watcher import Watcher

NOW = 2_100


def setup(
    tmp_path: Path, triggers: dict[str, object], triage_provider: Provider | None = None
) -> tuple[Rig, Watcher, Mailbox]:
    rig = make_rig(tmp_path, triage_provider=triage_provider)
    rig.core.change_settings({"triggers": triggers})
    watcher = Watcher(rig.core, rig.wow_dir, clock=lambda: NOW, local_hour=lambda: 12)
    return rig, watcher, rig.core.bus.subscribe()


def events_of(mailbox: Mailbox, kind: str) -> list[Event]:
    found: list[Event] = []
    while not mailbox.empty():
        event = mailbox.get_nowait()
        if event is not None and event.kind == kind:
            found.append(event)
    return found


def test_a_death_on_notify_gives_a_notification_and_no_ai_call(tmp_path: Path) -> None:
    rig, watcher, mailbox = setup(tmp_path, {"modes": {"died": "notify"}})
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,))
    watcher.check_once()
    assert rig.alerts.notified == [("wow-coach", "Died in Brill (level 8).")]
    assert rig.coach.asked == []
    decision = events_of(mailbox, "decision")[0].data
    assert decision["kind"] == "died" and decision["action"] == "notify" and decision["reason"]
    assert decision["summary"] == "Died in Brill (level 8)."


def test_notify_decisions_respect_the_notifications_setting(tmp_path: Path) -> None:
    rig, watcher, _ = setup(tmp_path, {"modes": {"died": "notify"}})
    rig.core.change_settings({"notify": False})
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,))
    watcher.check_once()
    assert rig.alerts.notified == []


def test_a_death_on_coach_asks_once_and_starts_the_cooldown(tmp_path: Path) -> None:
    rig, watcher, mailbox = setup(tmp_path, {"modes": {"died": "coach"}})
    rig.core.change_settings({"speak": True})
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,))
    watcher.check_once()
    assert len(rig.coach.asked) == 1 and "Died in Brill" in rig.coach.asked[0]
    assert len(events_of(mailbox, "answer")) == 1
    assert rig.alerts.notified[-1][0] == "Your coach answered"
    assert rig.alerts.spoken  # speak is on
    state = json.loads(rig.core.trigger_state_file.read_text("utf-8"))
    assert state["last_coach_at"] == {"Testchar-Testrealm": NOW}
    # A second death inside the cooldown does not ask again.
    write_save(rig.wow_dir, mtime=2_050, deaths_at=(1_500, 2_040))
    watcher.check_once()
    assert len(rig.coach.asked) == 1
    reasons = [str(e.data["reason"]) for e in events_of(mailbox, "decision")]
    assert "cooldown" in reasons[-1]


def test_two_coach_events_in_one_save_make_one_call(tmp_path: Path) -> None:
    rig, watcher, _ = setup(tmp_path, {"modes": {"died": "coach", "level_up": "coach"}})
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,), levels_at=(1_600,))
    watcher.check_once()
    assert len(rig.coach.asked) == 1
    assert "Died" in rig.coach.asked[0] and "level" in rig.coach.asked[0].lower()


def test_quiet_in_an_instance(tmp_path: Path) -> None:
    rig, watcher, mailbox = setup(
        tmp_path, {"modes": {"died": "coach"}, "quiet_in_instances": True}
    )
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,), in_instance=True)
    watcher.check_once()
    assert rig.coach.asked == [] and rig.alerts.notified == []
    assert "dungeons" in str(events_of(mailbox, "decision")[0].data["reason"])


def test_the_timer_fires_without_a_save(tmp_path: Path) -> None:
    rig, watcher, mailbox = setup(tmp_path, {"modes": {"timer": "coach"}, "every_minutes": 5})
    watcher.check_timer()
    assert len(rig.coach.asked) == 1
    assert events_of(mailbox, "decision")[0].data["kind"] == "timer"
    watcher.check_timer()  # it just fired: not due again
    assert len(rig.coach.asked) == 1


def test_the_timer_is_off_by_default(tmp_path: Path) -> None:
    rig, watcher, _ = setup(tmp_path, {})
    watcher.check_timer()
    assert rig.coach.asked == []


def test_triage_skip_turns_a_coach_decision_into_a_notification(tmp_path: Path) -> None:
    provider = FakeProvider(['{"wake": false, "reason": "just one death"}'])
    rig, watcher, mailbox = setup(
        tmp_path,
        {"modes": {"died": "coach"}, "use_triage": True, "rules_text": "only if I die twice"},
        provider,
    )
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,))
    watcher.check_once()
    assert rig.coach.asked == []
    assert len(provider.requests) == 1 and provider.requests[0][1] == "model-luna"
    assert rig.alerts.notified == [("wow-coach", "Died in Brill (level 8).")]
    decision = events_of(mailbox, "decision")[0].data
    assert decision["action"] == "notify" and "just one death" in str(decision["reason"])


def test_triage_wake_still_asks_the_coach(tmp_path: Path) -> None:
    provider = FakeProvider(['{"wake": true, "reason": "worth it"}'])
    rig, watcher, _ = setup(tmp_path, {"modes": {"died": "coach"}, "use_triage": True}, provider)
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,))
    watcher.check_once()
    assert len(rig.coach.asked) == 1


def test_an_ai_error_becomes_an_error_event_and_still_starts_the_cooldown(tmp_path: Path) -> None:
    rig, watcher, mailbox = setup(tmp_path, {"modes": {"died": "coach"}})
    rig.coach.error = PlanLimitReached("Your plan is used up.")
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,))
    watcher.check_once()
    assert [e.data["message"] for e in events_of(mailbox, "error")] == ["Your plan is used up."]
    assert rig.core.trigger_state_file.is_file()


def test_everything_is_off_by_default(tmp_path: Path) -> None:
    rig, watcher, mailbox = setup(tmp_path, {})
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,))
    watcher.check_once()
    assert rig.coach.asked == [] and rig.alerts.notified == []
    assert events_of(mailbox, "decision")[0].data["action"] == "off"


def test_the_settings_round_trip_through_the_api(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    server = CoachServer(rig.core, 0)
    server.start()
    try:
        page = Client(server)
        page.sign_in_page()
        _, state = page.json("GET", "/api/state")
        modes = state["settings"]["triggers"]["modes"]
        assert modes["died"] == "off" and modes["asked"] == "coach"
        triggers = {
            "modes": {"died": "notify", "timer": "coach"},
            "every_minutes": 30,
            "cooldown_minutes": 15,
            "quiet_in_instances": False,
            "quiet_from_hour": 23,
            "quiet_to_hour": 7,
            "use_triage": True,
            "rules_text": "only if I die twice",
        }
        status, _ = page.json("POST", "/api/settings", {"changes": {"triggers": triggers}})
        assert status == 200
        _, state = page.json("GET", "/api/state")
        got = state["settings"]["triggers"]
        assert got["modes"]["died"] == "notify" and got["modes"]["level_up"] == "off"
        assert got["every_minutes"] == 30 and got["quiet_from_hour"] == 23
        assert got["use_triage"] is True and got["rules_text"] == "only if I die twice"
        saved = json.loads(rig.settings_file.read_text("utf-8"))
        assert saved["triggers"]["cooldown_minutes"] == 15
        page.json("POST", "/api/settings", {"changes": {"triggers": {"quiet_from_hour": None}}})
        assert rig.core.settings.triggers.quiet_from_hour is None
        assert rig.core.settings.triggers.every_minutes == 30  # a partial change keeps the rest
    finally:
        server.stop()
