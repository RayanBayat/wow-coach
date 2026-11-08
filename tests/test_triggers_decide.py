"""decide(): modes, quiet times, cooldown, timer, merging; and the coach request text."""

from dataclasses import replace

from wow_coach.triggers.contract import Decision, Event, EventKind, Mode, TriggerSettings
from wow_coach.triggers.decide import decide
from wow_coach.triggers.prompt import coach_request_for
from wow_coach.triggers.state import TriggerState

NOW = 1_000_000
KEY = "Test-Realm"


def event(kind: EventKind, at: int = NOW, summary: str = "Something happened.") -> Event:
    return Event(kind, KEY, at, summary)


def rules(**modes: Mode) -> TriggerSettings:
    base = TriggerSettings()
    return replace(base, modes={**base.modes, **modes})


def decisions_for(
    events: list[Event],
    settings: TriggerSettings,
    *,
    state: TriggerState | None = None,
    in_instance: bool = False,
    hour: int = 12,
    character_key: str | None = None,
) -> list[Decision]:
    return decide(
        events,
        settings,
        state=state or TriggerState(),
        now=NOW,
        in_instance=in_instance,
        local_hour=hour,
        character_key=character_key,
    )


def run(
    events: list[Event],
    settings: TriggerSettings,
    *,
    state: TriggerState | None = None,
    in_instance: bool = False,
    hour: int = 12,
) -> list[tuple[str, str]]:
    decisions = decisions_for(events, settings, state=state, in_instance=in_instance, hour=hour)
    return [(d.event.kind, d.action) for d in decisions]


def test_default_rules_do_nothing_unasked() -> None:
    assert run([event("died"), event("level_up")], TriggerSettings()) == [
        ("died", "off"),
        ("level_up", "off"),
    ]


def test_modes_apply_per_kind() -> None:
    settings = rules(died="notify", level_up="coach")
    assert run([event("died"), event("level_up")], settings) == [
        ("died", "notify"),
        ("level_up", "coach"),
    ]


def test_every_decision_has_a_plain_reason() -> None:
    decisions = decisions_for([event("died"), event("new_zone")], rules(died="notify"))
    assert decisions[0].reason == "your rule for deaths says notify"
    assert decisions[1].reason == "your rule for new zones is off"


def test_asked_is_always_coached() -> None:
    settings = replace(
        TriggerSettings(),
        modes={**TriggerSettings().modes, "asked": "off"},
        quiet_from_hour=0,
        quiet_to_hour=23,
        cooldown_minutes=240,
    )
    state = TriggerState(last_coach_at={KEY: NOW})
    assert run([event("asked")], settings, state=state, in_instance=True, hour=3) == [
        ("asked", "coach")
    ]


def test_quiet_in_instances() -> None:
    settings = rules(died="coach", level_up="notify")
    assert run([event("died"), event("level_up")], settings, in_instance=True) == [
        ("died", "off"),
        ("level_up", "off"),
    ]
    loud = replace(settings, quiet_in_instances=False)
    assert run([event("died")], loud, in_instance=True) == [("died", "coach")]


def test_quiet_hours_that_wrap_around_midnight() -> None:
    settings = replace(rules(died="notify"), quiet_from_hour=23, quiet_to_hour=7)
    for hour, expected in [(22, "notify"), (23, "off"), (0, "off"), (6, "off"), (7, "notify")]:
        assert run([event("died")], settings, hour=hour) == [("died", expected)], hour


def test_quiet_hours_in_one_day() -> None:
    settings = replace(rules(died="notify"), quiet_from_hour=9, quiet_to_hour=17)
    for hour, expected in [(8, "notify"), (9, "off"), (16, "off"), (17, "notify")]:
        assert run([event("died")], settings, hour=hour) == [("died", expected)], hour


def test_no_quiet_hours_when_unset_or_equal() -> None:
    notify = rules(died="notify")
    assert run([event("died")], replace(notify, quiet_from_hour=5), hour=5) == [("died", "notify")]
    equal = replace(notify, quiet_from_hour=5, quiet_to_hour=5)
    assert run([event("died")], equal, hour=5) == [("died", "notify")]


def test_cooldown_turns_coach_into_notify() -> None:
    settings = replace(rules(died="coach"), cooldown_minutes=10)
    state = TriggerState(last_coach_at={KEY: NOW - 6 * 60})
    decisions = decisions_for([event("died")], settings, state=state)
    assert decisions[0].action == "notify"
    assert "4 min left" in decisions[0].reason


def test_cooldown_over_or_other_character_or_zero() -> None:
    settings = replace(rules(died="coach"), cooldown_minutes=10)
    over = TriggerState(last_coach_at={KEY: NOW - 11 * 60})
    assert run([event("died")], settings, state=over) == [("died", "coach")]
    other = TriggerState(last_coach_at={"Someone-Else": NOW})
    assert run([event("died")], settings, state=other) == [("died", "coach")]
    none = replace(settings, cooldown_minutes=0)
    fresh = TriggerState(last_coach_at={KEY: NOW})
    assert run([event("died")], none, state=fresh) == [("died", "coach")]


def test_cooldown_does_not_touch_notify() -> None:
    state = TriggerState(last_coach_at={KEY: NOW})
    assert run([event("died")], rules(died="notify"), state=state) == [("died", "notify")]


def test_several_coach_events_become_one_request() -> None:
    settings = rules(died="coach", level_up="coach", new_zone="coach", quest_done="notify")
    events = [event("died"), event("level_up"), event("new_zone"), event("quest_done")]
    decisions = decisions_for(events, settings)
    assert [d.action for d in decisions] == ["coach", "coach", "coach", "notify"]
    assert "joined the one coach request" not in decisions[0].reason
    assert "joined the one coach request" in decisions[1].reason
    assert "joined the one coach request" in decisions[2].reason


def test_asked_is_not_merged_with_other_coach_events() -> None:
    decisions = decisions_for([event("asked"), event("died")], rules(died="coach"))
    assert "joined" not in decisions[0].reason
    assert "joined" not in decisions[1].reason


def test_death_loop_uses_the_repeat_rule_when_it_is_on() -> None:
    both = [event("died"), event("died_again_soon")]
    settings = rules(died="notify", died_again_soon="coach")
    assert run(both, settings) == [("died", "off"), ("died_again_soon", "coach")]
    only_died = rules(died="notify")
    assert run(both, only_died) == [("died", "notify"), ("died_again_soon", "off")]


def test_timer_fires_when_due() -> None:
    settings = replace(rules(timer="coach"), every_minutes=30)
    due = TriggerState(last_timer_at=NOW - 31 * 60)
    assert run([], settings, state=due) == []  # no character known: nothing to ask about
    decisions = decisions_for([], settings, state=due, character_key=KEY)
    assert [(d.event.kind, d.action) for d in decisions] == [("timer", "coach")]
    assert decisions[0].event.character_key == KEY


def test_timer_waits_and_respects_off_and_quiet() -> None:
    settings = replace(rules(timer="coach"), every_minutes=30)
    recent = TriggerState(last_timer_at=NOW - 10 * 60)
    assert run([event("died")], settings, state=recent) == [("died", "off")]
    off = replace(rules(timer="off"), every_minutes=30)
    assert run([event("died")], off) == [("died", "off")]
    assert run([event("died")], replace(settings, every_minutes=0)) == [("died", "off")]
    assert run([event("died")], settings, in_instance=True) == [("died", "off"), ("timer", "off")]


def test_timer_joins_the_merged_request() -> None:
    settings = replace(rules(timer="coach", died="coach"), every_minutes=30)
    assert [action for _, action in run([event("died")], settings)] == ["coach", "coach"]


# --- prompt ---


def test_coach_request_lists_only_coach_events() -> None:
    settings = rules(died="coach", level_up="coach", new_zone="notify")
    events = [
        event("died", summary="Died in Brill (level 9)."),
        event("level_up", summary="Reached level 10."),
        event("new_zone", summary="Now in Undercity."),
        event("asked", summary="Where to?"),
    ]
    text = coach_request_for(decisions_for(events, settings))
    assert text == (
        "These just happened: Died in Brill (level 9). Reached level 10. "
        "What should I do now? Keep it short."
    )


def test_coach_request_is_empty_without_coach_decisions() -> None:
    decisions = decisions_for([event("died")], rules(died="notify"))
    assert coach_request_for(decisions) == ""
