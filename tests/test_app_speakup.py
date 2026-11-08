""" "When the game saves": a save turns into one notification and maybe one coach answer."""

from pathlib import Path

from test_app_support import Client, Rig, make_rig, write_save

from wow_coach.ai.base import PlanLimitReached
from wow_coach.app.events import Event, Mailbox
from wow_coach.app.server import CoachServer
from wow_coach.app.watcher import Watcher
from wow_coach.triggers.prompt import STATUS_UPDATED

NOW = 2_100


def setup(tmp_path: Path, triggers: dict[str, object]) -> tuple[Rig, Watcher, Mailbox]:
    rig = make_rig(tmp_path)
    rig.core.change_settings({"triggers": triggers})
    watcher = Watcher(rig.core, rig.wow_dir, clock=lambda: NOW)
    return rig, watcher, rig.core.bus.subscribe()


def events_of(mailbox: Mailbox, kind: str) -> list[Event]:
    found: list[Event] = []
    while not mailbox.empty():
        event = mailbox.get_nowait()
        if event is not None and event.kind == kind:
            found.append(event)
    return found


def test_by_default_a_death_gives_a_notification_and_no_ai_call(tmp_path: Path) -> None:
    rig, watcher, _ = setup(tmp_path, {})
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,))
    watcher.check_once()
    assert rig.alerts.notified == [("wow-coach", "Died in Brill (level 8).")]
    assert rig.coach.asked == []


def test_two_events_in_one_save_give_one_notification(tmp_path: Path) -> None:
    rig, watcher, _ = setup(tmp_path, {})
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,), levels_at=(1_600,))
    watcher.check_once()
    assert len(rig.alerts.notified) == 1
    text = rig.alerts.notified[0][1]
    assert "Died in Brill" in text and "level" in text.lower()


def test_a_save_with_nothing_new_says_nothing(tmp_path: Path) -> None:
    rig, watcher, _ = setup(tmp_path, {})
    write_save(rig.wow_dir, mtime=2_000)
    watcher.check_once()
    assert rig.alerts.notified == [] and rig.coach.asked == []


def test_notifications_respect_the_notifications_setting(tmp_path: Path) -> None:
    rig, watcher, _ = setup(tmp_path, {})
    rig.core.change_settings({"notify": False})
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,))
    watcher.check_once()
    assert rig.alerts.notified == []


def test_off_says_nothing(tmp_path: Path) -> None:
    rig, watcher, _ = setup(tmp_path, {"on_save": "off"})
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,))
    watcher.check_once()
    assert rig.alerts.notified == [] and rig.coach.asked == []


def test_advice_notifies_and_asks_the_coach_once(tmp_path: Path) -> None:
    rig, watcher, mailbox = setup(tmp_path, {"on_save": "advice"})
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,), levels_at=(1_600,), reason="coach")
    watcher.check_once()
    assert len(rig.coach.asked) == 1
    assert "Died" in rig.coach.asked[0] and "level" in rig.coach.asked[0].lower()
    assert len(events_of(mailbox, "answer")) == 1
    assert rig.alerts.notified[0][0] == "wow-coach"
    assert rig.alerts.notified[-1][0] == "Your coach answered"


def test_advice_asks_again_for_a_later_save_with_new_things(tmp_path: Path) -> None:
    rig, watcher, _ = setup(tmp_path, {"on_save": "advice"})
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,), reason="coach")
    watcher.check_once()
    write_save(rig.wow_dir, mtime=2_050, deaths_at=(1_500, 2_040), reason="coach")
    watcher.check_once()
    assert len(rig.coach.asked) == 2  # one per save, never more


def test_update_my_next_steps_asks_after_any_save_that_changed_something(
    tmp_path: Path,
) -> None:
    rig, watcher, mailbox = setup(tmp_path, {"on_save": "advice"})
    write_save(rig.wow_dir, mtime=2_000, zone="Silverpine Forest", reason="coach")  # moved
    watcher.check_once()
    assert len(rig.coach.asked) == 1
    assert rig.coach.asked[0].startswith("Status updated")
    assert len(events_of(mailbox, "answer")) == 1  # the chat and the small card show it
    assert rig.alerts.notified[-1][0] == "Your coach answered"


def test_every_reload_asks_even_when_nothing_changed(tmp_path: Path) -> None:
    # The owner asked for it: a /reload means "look at me again and tell me what's next".
    rig, watcher, _ = setup(tmp_path, {"on_save": "advice"})
    write_save(rig.wow_dir, mtime=2_000, zone="Silverpine Forest", reason="coach")
    watcher.check_once()
    write_save(rig.wow_dir, mtime=2_050, zone="Silverpine Forest", reason="logout")  # same
    watcher.check_once()
    assert len(rig.coach.asked) == 2
    assert rig.coach.asked[1] == STATUS_UPDATED


def test_a_question_from_the_game_gets_its_own_answer_not_a_second_one(tmp_path: Path) -> None:
    rig, watcher, _ = setup(tmp_path, {"on_save": "advice"})
    write_save(rig.wow_dir, ("q1", "Where is Brill?"), mtime=2_000, zone="Silverpine Forest")
    watcher.check_once()
    assert rig.coach.asked == []  # no "status updated" request on top of its own answer


def test_notify_only_never_asks_even_when_things_changed(tmp_path: Path) -> None:
    rig, watcher, _ = setup(tmp_path, {"on_save": "notify"})
    write_save(rig.wow_dir, mtime=2_000, zone="Silverpine Forest", reason="coach")
    watcher.check_once()
    assert rig.coach.asked == []  # notifications only, never an AI call


def test_quiet_in_an_instance(tmp_path: Path) -> None:
    rig, watcher, _ = setup(tmp_path, {"on_save": "advice", "quiet_in_instances": True})
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,), in_instance=True)
    watcher.check_once()
    assert rig.coach.asked == [] and rig.alerts.notified == []


def test_an_ai_error_becomes_an_error_event_but_the_notification_stays(tmp_path: Path) -> None:
    rig, watcher, mailbox = setup(tmp_path, {"on_save": "advice"})
    rig.coach.error = PlanLimitReached("Your plan is used up.")
    write_save(rig.wow_dir, mtime=2_000, deaths_at=(1_500,), reason="coach")
    watcher.check_once()
    assert [e.data["message"] for e in events_of(mailbox, "error")] == ["Your plan is used up."]
    assert rig.alerts.notified == [("wow-coach", "Died in Brill (level 8).")]


def test_the_settings_round_trip_through_the_api(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    server = CoachServer(rig.core, 0)
    server.start()
    try:
        page = Client(server)
        page.sign_in_page()
        _, state = page.json("GET", "/api/state")
        assert state["settings"]["triggers"] == {"on_save": "notify", "quiet_in_instances": True}
        triggers = {"on_save": "advice", "quiet_in_instances": False}
        status, _ = page.json("POST", "/api/settings", {"changes": {"triggers": triggers}})
        assert status == 200
        _, state = page.json("GET", "/api/state")
        assert state["settings"]["triggers"] == triggers
        page.json("POST", "/api/settings", {"changes": {"triggers": {"on_save": "off"}}})
        assert rig.core.settings.triggers.on_save == "off"
        assert rig.core.settings.triggers.quiet_in_instances is False  # a partial change stays
    finally:
        server.stop()


def test_the_automatic_question_is_marked_as_coming_from_a_save(tmp_path: Path) -> None:
    rig, watcher, _ = setup(tmp_path, {"on_save": "advice"})
    seen: list[str] = []
    original = rig.coach.ask

    def spy(question: str, *, character: str | None = None, source: str = "app") -> object:
        seen.append(source)
        return original(question, character=character, source=source)

    rig.coach.ask = spy  # type: ignore[method-assign]
    write_save(rig.wow_dir, mtime=2_000, reason="coach")
    watcher.check_once()
    assert seen == ["save"]
