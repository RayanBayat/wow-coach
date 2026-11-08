"""worth_knowing(): the player's choice and quiet rule; the one text; the coach request."""

from dataclasses import replace

from wow_coach.triggers.contract import Event, EventKind, OnSave, TriggerSettings
from wow_coach.triggers.decide import MAX_NOTIFICATION_CHARS, notification_text, worth_knowing
from wow_coach.triggers.prompt import MAX_EVENTS, coach_request_for

NOW = 1_000_000
KEY = "Test-Realm"


def event(kind: EventKind, at: int = NOW, summary: str = "Something happened.") -> Event:
    return Event(kind, KEY, at, summary)


def rules(on_save: OnSave = "notify", *, quiet: bool = True) -> TriggerSettings:
    return replace(TriggerSettings(), on_save=on_save, quiet_in_instances=quiet)


def test_the_default_tells_what_is_worth_knowing() -> None:
    events = [event("died"), event("level_up")]
    assert worth_knowing(events, TriggerSettings(), in_instance=False) == events


def test_off_says_nothing() -> None:
    assert worth_knowing([event("died")], rules("off"), in_instance=False) == []


def test_advice_keeps_the_events_too() -> None:
    events = [event("level_up")]
    assert worth_knowing(events, rules("advice"), in_instance=False) == events


def test_quiet_in_a_dungeon_or_raid() -> None:
    assert worth_knowing([event("died")], rules(), in_instance=True) == []


def test_not_quiet_in_an_instance_when_the_player_turned_it_off() -> None:
    events = [event("died")]
    assert worth_knowing(events, rules(quiet=False), in_instance=True) == events


def test_a_death_loop_is_told_once() -> None:
    died, again = event("died", 5), event("died_again_soon", 5)
    other = event("died", 9)
    assert worth_knowing([died, again, other], rules(), in_instance=False) == [again, other]


def test_nothing_happened_means_nothing_to_say() -> None:
    assert worth_knowing([], rules("advice"), in_instance=False) == []


def test_the_notification_is_one_text_with_every_event() -> None:
    events = [
        event("level_up", summary="Reached level 9."),
        event("bags_nearly_full", summary="Bags are full."),
    ]
    assert notification_text(events) == "Reached level 9. Bags are full."


def test_a_very_long_notification_is_cut() -> None:
    text = notification_text([event("died", summary="x" * 1000)])
    assert len(text) == MAX_NOTIFICATION_CHARS and text.endswith("...")


def test_coach_request_lists_the_events() -> None:
    request = coach_request_for(
        [event("died", summary="Died in Brill."), event("level_up", summary="Reached level 9.")]
    )
    assert "Died in Brill." in request and "Reached level 9." in request
    assert request.endswith("Keep it short.")


def test_coach_request_is_empty_without_events() -> None:
    assert coach_request_for([]) == ""


def test_coach_request_lists_only_so_many_events() -> None:
    events = [event("died", summary=f"Event number {n}.") for n in range(MAX_EVENTS + 4)]
    request = coach_request_for(events)
    assert f"Event number {MAX_EVENTS - 1}." in request
    assert f"Event number {MAX_EVENTS}." not in request
